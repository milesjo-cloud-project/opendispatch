"""Jobs, their status flow and history, and spend on them (expenses, time, budget).

A job you can't see answers 404, the same as a job that doesn't exist.
"""
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4
import mimetypes
import re

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.db.job_repository import CustomerRepository, JobRepository
from app.adapters.db.tables import job_attachments
from app.adapters.storage.filesystem import FileSystemStorage
from app.adapters.db.queries import visible_expenses, visible_job, visible_jobs
from app.api.deps import Actor, current_actor, get_alert_sender, get_session, office_actor, owner_actor
from app.api.schemas import (
    BudgetOut,
    DecisionIn,
    ExpenseCreate,
    ExpenseOut,
    JobCreate,
    JobEventOut,
    JobOut,
    JobAttachmentOut,
    JobUpdate,
    SpendOut,
    StatusChangeIn,
    TimeEntryCreate,
    TimeEntryOut,
)
from app.domain.access import can_change_status, can_view_budget, is_office
from app.domain.budget import JobBudget, job_budget
from app.domain.entities import Customer, Expense, Job, JobAttachment, JobEvent, Technician, TimeEntry
from app.domain.errors import DomainRuleViolation
from app.services import spend
from app.services.spend import NotFound
from app.config import settings

router = APIRouter(tags=["jobs"])
MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024
_storage = FileSystemStorage(settings.upload_dir)


def _attachment_content_type(filename: str, declared: str | None) -> str | None:
    detected = declared or "application/octet-stream"
    guessed = mimetypes.guess_type(filename)[0] or ""
    content_type = detected if detected.startswith("image/") or detected == "application/pdf" else guessed
    return content_type if content_type.startswith("image/") or content_type == "application/pdf" else None


def _job(session: Session, actor: Actor, job_id: UUID) -> Job:
    job = visible_job(session, actor.user, job_id)
    if job is None:
        raise NotFound(f"Job {job_id}")
    return job


def _job_out(job: Job, actor: Actor, session: Session) -> JobOut:
    out = JobOut.model_validate(job)
    if not can_view_budget(actor.user, job):
        out.quoted_amount_cents = None
    customer = session.get(Customer, job.customer_id)
    if customer is not None and customer.company_id == job.company_id:
        out.customer_name = customer.name
        out.customer_phone = customer.phone
    return out


def _budget_out(b: JobBudget) -> BudgetOut:
    return BudgetOut(quoted_cents=b.quoted_cents, approved_cents=b.approved_cents,
                     pending_cents=b.pending_cents, labor_cents=b.labor_cents,
                     spent_cents=b.spent_cents, remaining_cents=b.remaining_cents, level=b.level)


def _check_refs(session: Session, company_id: UUID, customer_id=None, technician_id=None) -> None:
    """Friendly 422s for ids from another company (the database would refuse them anyway)."""
    if customer_id is not None:
        if CustomerRepository(session).get_for_company(customer_id, company_id) is None:
            raise DomainRuleViolation("Unknown customer")
    if technician_id is not None:
        t = session.get(Technician, technician_id)
        if t is None or t.company_id != company_id:
            raise DomainRuleViolation("Unknown technician")
        if not t.active:
            raise DomainRuleViolation(f"{t.display_name} is inactive and can't take new jobs")


# --- jobs

@router.get("/jobs", response_model=list[JobOut])
def list_jobs(actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Owners and dispatchers get every job; technicians get the jobs assigned to them."""
    return [_job_out(j, actor, session) for j in visible_jobs(session, actor.user)]


@router.post("/jobs", response_model=JobOut, status_code=201)
def create_job(body: JobCreate, actor: Actor = Depends(office_actor),
               session: Session = Depends(get_session)):
    _check_refs(session, actor.user.company_id, body.customer_id, body.technician_id)
    job = Job(company_id=actor.user.company_id, **body.model_dump())
    JobRepository(session).add(job)
    session.commit()
    return _job_out(job, actor, session)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    return _job_out(_job(session, actor, job_id), actor, session)


@router.patch("/jobs/{job_id}", response_model=JobOut)
def update_job(job_id: UUID, body: JobUpdate, actor: Actor = Depends(office_actor),
               session: Session = Depends(get_session)):
    """Edit details, assign a technician, set the start time or the quote. Status has its own endpoint.

    What can change depends on the job's stage (see Job.assign/reschedule/set_quote);
    anything else answers 422 and nothing is saved."""
    job = _job(session, actor, job_id)
    sent = body.model_fields_set
    # Only a change of technician is checked, so a job still assigned to someone who's
    # since been deactivated can be edited until the office reassigns it.
    reassigned = "technician_id" in sent and body.technician_id != job.technician_id
    _check_refs(session, job.company_id, technician_id=body.technician_id if reassigned else None)
    try:
        if "title" in sent and body.title is not None:
            job.rename(body.title)
        if "description" in sent:
            job.set_description(body.description)
        if "technician_id" in sent:
            job.assign(body.technician_id)
        if "scheduled_start" in sent:
            job.reschedule(body.scheduled_start)
        if "quoted_amount_cents" in sent:
            job.set_quote(body.quoted_amount_cents)
    except DomainRuleViolation:
        session.rollback()  # undo the edits that were allowed before the one that wasn't
        raise
    session.commit()
    return _job_out(job, actor, session)


@router.post("/jobs/{job_id}/status", response_model=JobOut)
def change_status(job_id: UUID, body: StatusChangeIn, actor: Actor = Depends(current_actor),
                  session: Session = Depends(get_session)):
    """Move a job along its status flow. Techs can mark their own jobs en route, in progress
    and completed; everything else is office work. Illegal moves answer 409."""
    job = _job(session, actor, job_id)
    if not can_change_status(actor.user, job, body.status, actor.technician):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't make that change on this job")
    JobRepository(session).add_event(job.transition_to(body.status, actor_user_id=actor.user.id, note=body.note))
    session.commit()
    return _job_out(job, actor, session)


@router.get("/jobs/{job_id}/events", response_model=list[JobEventOut])
def job_history(job_id: UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    job = _job(session, actor, job_id)
    return session.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.occurred_at, JobEvent.id)
    ).all()


@router.get("/jobs/{job_id}/attachments", response_model=list[JobAttachmentOut], tags=["documents"])
def list_job_attachments(job_id: UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    job = _job(session, actor, job_id)
    return session.execute(
        select(job_attachments).where(job_attachments.c.job_id == job.id)
        .order_by(job_attachments.c.created_at, job_attachments.c.id)
    ).mappings().all()


@router.post("/jobs/{job_id}/attachments", response_model=JobAttachmentOut, status_code=201, tags=["documents"])
def upload_job_attachment(job_id: UUID, file: UploadFile = File(...), actor: Actor = Depends(current_actor),
                          session: Session = Depends(get_session)):
    """Store common images and PDFs. Bytes are capped and served back as downloads."""
    job = _job(session, actor, job_id)
    filename = Path((file.filename or "upload").replace("\\", "/")).name
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename)[:255] or "upload"
    content_type = _attachment_content_type(filename, file.content_type)
    if content_type is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload an image or PDF")
    content = file.file.read(MAX_ATTACHMENT_BYTES + 1)
    if not content or len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Files must be between 1 byte and 12 MiB")
    key = uuid4().hex
    _storage.save(key, content)
    attachment = JobAttachment(company_id=job.company_id, job_id=job.id,
                               uploaded_by_user_id=actor.user.id, filename=filename,
                               content_type=content_type, size_bytes=len(content), storage_key=key)
    session.add(attachment)
    try:
        session.commit()
    except Exception:
        _storage.path(key).unlink(missing_ok=True)
        raise
    return attachment


@router.get("/jobs/{job_id}/attachments/{attachment_id}", tags=["documents"])
def download_job_attachment(job_id: UUID, attachment_id: UUID, actor: Actor = Depends(current_actor),
                            session: Session = Depends(get_session)):
    job = _job(session, actor, job_id)
    row = session.execute(select(job_attachments).where(
        job_attachments.c.id == attachment_id,
        job_attachments.c.job_id == job.id,
        job_attachments.c.company_id == actor.user.company_id,
    )).mappings().one_or_none()
    if row is None:
        raise NotFound(f"Attachment {attachment_id}")
    path = _storage.path(row["storage_key"])
    if not path.is_file():
        raise NotFound(f"Attachment file {attachment_id}")
    return FileResponse(path, media_type="application/octet-stream", filename=row["filename"],
                        headers={"X-Content-Type-Options": "nosniff"})


@router.get("/jobs/{job_id}/budget", response_model=BudgetOut)
def budget(job_id: UUID, actor: Actor = Depends(office_actor), session: Session = Depends(get_session)):
    """Quote vs. approved + pending expenses + labor."""
    job = _job(session, actor, job_id)
    expenses = session.scalars(select(Expense).where(Expense.job_id == job.id))
    entries = session.scalars(select(TimeEntry).where(TimeEntry.job_id == job.id))
    return _budget_out(job_budget(job, expenses, entries))


# --- spend

def _spend_out(result: spend.SpendResult, job: Job, actor: Actor) -> SpendOut:
    if not can_view_budget(actor.user, job):
        return SpendOut(budget=None, alert=None)
    return SpendOut(budget=_budget_out(result.budget), alert=result.alert.level if result.alert else None)


class ExpenseCreated(ExpenseOut):
    spend: SpendOut


class TimeEntryCreated(TimeEntryOut):
    spend: SpendOut


@router.get("/jobs/{job_id}/expenses", response_model=list[ExpenseOut], tags=["spend"])
def list_expenses(job_id: UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Office sees every expense on the job; a technician sees their own."""
    _job(session, actor, job_id)
    return visible_expenses(session, actor.user, job_id)


@router.post("/jobs/{job_id}/expenses", response_model=ExpenseCreated, status_code=201, tags=["spend"])
def add_expense(job_id: UUID, body: ExpenseCreate, background: BackgroundTasks,
                actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
                send_alerts: Callable[[], None] = Depends(get_alert_sender)):
    """Over the company's approval limit, the expense waits for the owner."""
    job = _job(session, actor, job_id)
    result = spend.submit_expense(session, job_id=job.id, submitted_by_user_id=actor.user.id,
                                  **body.model_dump())
    session.commit()
    if result.alert:
        background.add_task(send_alerts)
    return ExpenseCreated(**ExpenseOut.model_validate(result.item).model_dump(),
                          spend=_spend_out(result, job, actor))


def _expense(session: Session, actor: Actor, expense_id: UUID) -> Expense:
    expense = session.get(Expense, expense_id)
    if expense is None or expense.company_id != actor.user.company_id:
        raise NotFound(f"Expense {expense_id}")
    return expense


@router.post("/expenses/{expense_id}/approve", response_model=ExpenseOut, tags=["spend"])
def approve_expense(expense_id: UUID, body: DecisionIn, actor: Actor = Depends(owner_actor),
                    session: Session = Depends(get_session)):
    expense = _expense(session, actor, expense_id)
    expense.approve(actor.user, body.note)
    session.commit()
    return expense


@router.post("/expenses/{expense_id}/reject", response_model=ExpenseOut, tags=["spend"])
def reject_expense(expense_id: UUID, body: DecisionIn, actor: Actor = Depends(owner_actor),
                   session: Session = Depends(get_session)):
    expense = _expense(session, actor, expense_id)
    expense.reject(actor.user, body.note)
    session.commit()
    return expense


@router.get("/jobs/{job_id}/time", response_model=list[TimeEntryOut], tags=["spend"])
def list_time(job_id: UUID, actor: Actor = Depends(current_actor), session: Session = Depends(get_session)):
    """Office sees all time on the job; a technician sees their own."""
    job = _job(session, actor, job_id)
    stmt = select(TimeEntry).where(TimeEntry.job_id == job.id)
    if not is_office(actor.user):
        if actor.technician is None:
            return []
        stmt = stmt.where(TimeEntry.technician_id == actor.technician.id)
    return session.scalars(stmt.order_by(TimeEntry.started_at, TimeEntry.id)).all()


@router.post("/jobs/{job_id}/time", response_model=TimeEntryCreated, status_code=201, tags=["spend"])
def add_time(job_id: UUID, body: TimeEntryCreate, background: BackgroundTasks,
             actor: Actor = Depends(current_actor), session: Session = Depends(get_session),
             send_alerts: Callable[[], None] = Depends(get_alert_sender)):
    """The assigned technician logs their own time on the job."""
    job = _job(session, actor, job_id)
    if actor.technician is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only technicians log time")
    result = spend.log_time(session, job_id=job.id, technician_id=actor.technician.id, **body.model_dump())
    session.commit()
    if result.alert:
        background.add_task(send_alerts)
    return TimeEntryCreated(**TimeEntryOut.model_validate(result.item).model_dump(),
                            spend=_spend_out(result, job, actor))
