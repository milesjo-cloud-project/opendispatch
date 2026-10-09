# OpenDispatch

Open-source dispatch and job tracking for small service businesses.

## Run it locally

You need Docker Desktop and Git.

```
copy .env.example .env        # Windows Command Prompt
cp .env.example .env          # macOS / Linux / Git Bash
```

Open `.env` and change `change-me` to a password in **both** places
(`POSTGRES_PASSWORD` and inside `DATABASE_URL`). Then:

```
docker compose up --build
```

- Web: http://localhost:5173 (shows whether the API and database are up)
- API: http://localhost:8080/healthz and http://localhost:8080/readyz
- API docs: http://localhost:8080/docs
- Postgres: 127.0.0.1:5432 (only reachable from your own machine)

Use `127.0.0.1`, not `localhost`, in database URLs on your machine. On Windows `localhost`
tries IPv6 first, and the containers only listen on IPv4.

The API container runs `alembic upgrade head` on startup, so the tables are created for you.
Code changes in `api/app` and `web/src` reload automatically.
Stop with Ctrl+C. `docker compose down -v` also wipes the database.

## Run the API tests without Docker

```
cd api
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
python -m pytest -v
ruff check .                    # lint; CI runs it too. `ruff check . --fix` fixes the easy ones
```

The web code is formatted with Prettier. After editing anything in `web/`, run
`npm run format` there (CI fails on unformatted code). VS Code's Prettier extension can do it on save.

Tests that need Postgres are skipped unless `TEST_DATABASE_URL` points at a migrated database,
e.g. with `docker compose up` running: `$env:TEST_DATABASE_URL = "postgresql://opendispatch:change-me@127.0.0.1:5432/opendispatch"`

## Job status flow

```
Requested → Scheduled → Dispatched → EnRoute → InProgress → Completed → Invoiced → Paid
Dispatched → Scheduled is allowed (reschedule).
Cancelled: reachable from anything before Completed. Paid and Cancelled are final.
```

The table lives in `api/app/shared/job_status.py`. The only way to change a job's status is
`job.transition_to(...)`, which returns a `JobEvent` to save in the same transaction.

Editing a job (`PATCH /jobs/{id}`) also depends on its stage. The rules are on `Job` in
`api/app/shared/models.py`:

- **Technician:** can change until the job is Completed. Can be removed only from a draft or
  scheduled job; pull a dispatched job back to Scheduled first.
- **Start time:** can change until the tech is en route. Only a draft can have no time.
- **Quote:** can change until the job is Invoiced.
- **Title and description:** can change until the job is Paid or Cancelled.

Sending a value the job already has is always fine. If any change is refused, nothing in that
request is saved.

## Expenses and job budgets

Money is stored as whole cents (`50_000` = $500.00), never floats.

- `job.add_expense(company, submitted_by, amount_cents, ...)` is the only way to record spend.
  Each expense belongs to exactly one job. Paid and cancelled jobs don't take new expenses.
- Expenses at or under the company's `expense_approval_limit_cents` ($500 by default) are
  approved on the spot. Anything over waits until the owner calls `approve()` or `reject()`.
  An owner's own spend is never held.
- `job_budget(job, expenses)` in `api/app/spend/budget.py` compares spend (approved + pending,
  not rejected) against `job.quoted_amount_cents`. `alert_for(...)` tells you when a new
  expense crosses 80% or 100%, once per threshold. Budgets warn; they never block spend.
- Labor counts too: `job.log_time(technician, started_at, ended_at)` records time for the
  assigned tech and copies their `hourly_rate_cents`, so a later raise doesn't change old jobs.
- `app/spend/service.py` is what the API will call: `submit_expense()` and `log_time()` lock the
  job, save the spend, and write a `budget_alerts` row in the same transaction if a threshold was
  crossed. After committing, `send_pending_alerts(session, notifier)` sends them to the owners.
  Locally the notifier just writes to the API log; email/SMS adapters come later.

## Using the app

Open http://localhost:5173 and choose **New company? Sign up**. You're the owner. By default
(`SIGNUP=first-run` in `.env`) that link then disappears: your server is yours, and nobody
else can create a company on it. Use `SIGNUP=open` for a hosted service with many companies,
or to run the demo seed more than once. Once you're in:

- **Team**: add dispatchers and technicians with a starting password (owners only).
  Technicians get a lane on the schedule and, on their phone, a **Today** list.
- **Customers**: add and search customers, or create one while making a job.
- **＋ New job**: a job with a time goes straight onto the schedule; without one it waits in
  **Open shifts** as a draft.
- Open any job to move it along. Office staff dispatch, invoice, mark paid or cancel;
  technicians tap **On my way → Start work → Mark complete**.

The login is kept in the browser for up to 14 days, so a reload doesn't sign you out.

## Logging in and using the API

Open http://localhost:8080/docs, call `POST /auth/signup` with a company name, email and password
(12+ characters), and copy the `token` from the response. Click **Authorize**, paste the token,
and every other endpoint works as that owner. `POST /auth/login` gets a new token later.

- Tokens last 14 days. `POST /auth/logout` ends one; changing your password ends all the others.
- 10 wrong passwords from one address lock the account for 15 minutes *from that address*; the
  owner can still sign in from anywhere else. 100 wrong in a row from anywhere lock it everywhere.
  A password reset unlocks it.
- Owners add people with `POST /users` (with a starting password). Include
  `"technician": {"display_name": ..., "hourly_rate_cents": ...}` to make them a technician in the
  same request, or do it later with `POST /technicians`.
- `POST /jobs` takes a `customer_id`, or a `new_customer` to create one in the same request, and
  `"schedule": true` to put the job straight on the schedule. If any part is refused, nothing is
  saved, so retrying never makes duplicates.
- When someone leaves, an owner calls `POST /users/{id}/disable` (**Disable** on the Team page).
  It signs them out everywhere, cancels their reset links and job links, stops them signing in,
  takes their technician profile off the schedule, and takes their current and upcoming jobs off
  their calendar. Their jobs and history stay. `POST /users/{id}/enable` undoes it, calendar
  included. Owners can't disable themselves.
- Deactivating a technician (`PATCH /technicians/{id}`) only takes them off the schedule: new jobs
  can't be assigned to them, but they can still sign in.

## Forgotten passwords

`POST /auth/password-reset/request` with an email sends a link that works once, for one hour.
It answers the same whether or not the account exists, and sends at most 5 links per account per hour.
`POST /auth/password-reset/confirm` with the token and a new password sets it, unlocks the account,
logs it out everywhere, and cancels any other reset links.

Without `SMTP_*` in `.env` (see `.env.example`), the email, link included, is written to the API log
(`docker compose logs api`), which is all you need locally.

## Job documents and customer tracking links

- `POST /jobs/{id}/attachments` stores a photo (any `image/*`, including HEIC) or a PDF, up to 12 MiB.
  Anyone who can see the job can upload and download; files always download rather than open in the
  browser. In compose they live in the `uploads` volume; without Docker, in `./uploads` (`UPLOAD_DIR`).
- `POST /jobs/{id}/tracking-link` (owners and dispatchers, scheduled jobs onward) makes a private
  90-day link, `/track/<token>`, for the customer. It shows only the job title, status, and scheduled
  time, needs no login, and making a new link replaces the old one. Only a hash of the token is stored.

## Calendars and technician job links

A job reaches the technician through the calendar they already use. When a job has a
technician, a start time and is past draft, OpenDispatch puts an event on the configured
Google calendar with the technician as an attendee, so Google sends them the invite —
they need no Google account of their own and nothing to install. Rescheduling moves that
event, reassigning or cancelling takes it off.

The event carries a **technician job link**: `/j/<token>`, which opens the job on a phone
with no login and shows the customer, the phone number, the address and what the work is.
Never the quote.

- The token is signed, not stored, so there's no table to leak. The signature is what
  makes it real, which means **changing `JOB_LINK_SECRET` invalidates every link at
  once**, and no single link can be revoked on its own. Three things keep that bounded: it
  expires (`JOB_LINK_TTL_HOURS`, counted from the job's scheduled time so a job three
  weeks out still has a working link on the day), it names one technician so reassigning
  the job kills the old link, and it is read-only.
- Disabling someone's account (`POST /users/{id}/disable`) kills their links at once and
  takes their current and upcoming jobs off their calendar. Merely taking a technician off
  the schedule (`PATCH /technicians/{id}`) does neither: the jobs already assigned to them
  are still theirs to finish, so they keep both the jobs and the links.
- Set `JOB_LINK_SECRET` to a long random string outside local. Left blank it works locally
  with a built-in dev key, and is off anywhere else — events still go out, just with no link.
- `POST /jobs/{id}/job-link` gives the office the same link to send by hand.
- Customer tracking links are the other shape on purpose: random tokens with only a hash
  stored, because a customer's link lives 90 days and the office needs to replace it.
  `api/app/jobs/links.py` explains when to pick which.

### Connecting Google Calendar

Calendar writes go to the API log until you set `GOOGLE_*` in `.env`, which is all you
need locally. For real events, as the Google account whose calendar the jobs go on:

1. In the Google Cloud console, enable the **Google Calendar API**, then create an OAuth
   client of type **Desktop app** and copy its client id and secret.
2. Consent once with the `https://www.googleapis.com/auth/calendar.events` scope and keep
   the **refresh token** that comes back. If you also want the waitlist spreadsheet below,
   consent with `.../auth/spreadsheets` at the same time and one token covers both.
3. Put all three in `.env` with `GOOGLE_CALENDAR_ID` (`primary`, or a calendar id).

A refresh token rather than a service account is deliberate: a service account can't
invite attendees without Google Workspace domain-wide delegation, so the technician would
never see the job in their own calendar. The adapter is plain HTTP
(`api/app/adapters/google_calendar.py`), so there's no Google SDK to install, and it's one
swap away from an Apple/ICS adapter later.

### Why writes to Google retry

Writes to an outside service never happen inside the request that caused them. A provider that's down would
make saving a job fail, and a write that went out just before a rollback would put an
event on a technician's calendar for a job that doesn't exist. So:

- `PATCH /jobs/{id}` and friends queue the job in `calendar_outbox` **in the same
  transaction as the edit**, then the API drains the queue in a background task once the
  response is out.
- `api/app/outbox/worker.py` (`python -m app.outbox.worker`, the `worker` service in
  compose) drains it again on a timer. That's what makes a failed write get retried when
  Google is down for an hour, or when the write that failed was the last request of the day.
- A failed write backs off (30s, doubling, capped at 6 hours) and gives up after 12 tries,
  which spreads over about 20 hours, so a token that expired overnight is fixed in the
  morning and the event still lands. The row stays with `last_error` to look at.

The queue, the backoff and the draining loop are `api/app/shared/outbox.py`, and the
waitlist's spreadsheet copy below uses the same ones, which is why one `worker` service
covers both. Each feature keeps its own table, so the columns can say what they are about.

An outbox row carries no payload: it only says *this job's event is out of date*, and the
event is rebuilt from the job when it's sent. So five edits in a minute collapse into one
write, a retry always sends current state rather than a stale snapshot, and there's no
create/update/cancel ordering to get wrong — the sync compares what the job wants with
what the provider has and closes the gap. `job_calendar_events` holds the provider's id
for the event a job currently has; no row means there's nothing out there.

## The launch waitlist

`/waitlist` is the public page for the Winter 2027 launch: the founding prices and a signup
form. Every route behind it is **off unless `WAITLIST=open`**, because your copy runs your
business and the waitlist collects signups for the OpenDispatch launch, not for you. With it
closed the page says so and the API answers 404.

- `GET /public/waitlist` tells the page the launch window (`LAUNCH_LABEL`) and how many of
  the 100 founding spots are left. `POST /public/waitlist` joins the list: email is the only
  required field, limited to `WAITLIST_LIMIT_PER_HOUR` per IP address, with a honeypot field
  for bots. Signing up twice is not an error and never takes a second spot — the same
  address gets its original number back, so a double tap or a forgetful visitor keeps the
  spot they already hold.
- Spots are handed out in order under an advisory lock and never reused, because the
  founding price is promised to the first 100 people on the list.
- `GET /waitlist` returns the list and the counts, and needs `WAITLIST_ADMIN_TOKEN` in the
  `X-Waitlist-Token` header. Not a user role: a signup has no `company_id` (it is the only
  table without one), so there is no owner it could belong to, and a company owner on a
  hosted server must never be able to read everyone else’s contact details.

### A copy of the waitlist in Google Sheets

Deciding what to build first, and emailing 100 people at launch, is spreadsheet work, so
every signup is copied into one. Set `GOOGLE_SHEETS_ID` and `GOOGLE_SHEETS_TAB` in `.env`
(see `.env.example`). Create the spreadsheet yourself and name a tab to match. Left blank,
the rows go to the API log instead, which is what every install that isn't taking signups
wants.

**Authenticate with a service account, not a refresh token.** Google expires the refresh
token of an *External* OAuth app in *Testing* status after 7 days when it uses sensitive
scopes, and `.../auth/spreadsheets` is one, so the OAuth path means re-consenting every
week until the app is published and verified. A service account's key doesn't expire.
This is also the one place a service account works: the calendar can't use one, because
it can't invite technicians as attendees without Workspace domain-wide delegation, and
writing cells needs nobody invited.

1. **IAM & Admin → Service Accounts → Create**, then **Keys → Add key → JSON**.
2. Put the downloaded file in `./secrets/` — gitignored, and mounted read-only into the
   API and worker containers — and set `GOOGLE_SERVICE_ACCOUNT_FILE=/srv/secrets/<name>.json`.
   In a deployment, put the JSON itself in `GOOGLE_SERVICE_ACCOUNT_JSON` from a secret store.
3. Share the spreadsheet with the account's own address
   (`…@….iam.gserviceaccount.com`) as an **Editor**. That one share is the account's
   entire reach: it can touch that file and nothing else in your Drive.

Signing the account's JWT needs `cryptography`, which isn't in `requirements.txt` because
only this feature uses it — `api/requirements-sheets.txt`, installed by compose through
the `WITH_SHEETS` build arg. The refresh-token path (`GOOGLE_SHEETS_REFRESH_TOKEN`, or
reusing `GOOGLE_REFRESH_TOKEN`) still works and needs no extra package; a service account,
when configured, wins over it.

- `POST /public/waitlist` queues the row in `waitlist_outbox` in the signup's own
  transaction, and the write happens after the response. Nobody waits on Google to be told
  their spot, and a spreadsheet that's down can't turn a signup into an error.
- **A signup's row number is its spot plus one** (the header is row 1), so a write is
  always an overwrite of cells that belong to that one person. That is what makes retrying
  free: appending rows could never promise the same, because a call that timed out after
  Google acted would add somebody twice.
- The header goes out with every write, so a brand-new empty spreadsheet comes out
  labelled with no setup step to forget.
- Cells are written `RAW`, so anything typed into the public form stays text. A name
  starting with `=` is a name, not a formula.
- `POST /waitlist/resync` (same `X-Waitlist-Token` header) queues every signup again, for
  a spreadsheet set up after people had already joined, or one that was replaced. Every
  row goes back where it was, so it's safe to run as often as you like.
- The spreadsheet is only ever written to. The database is where a signup lives, so
  editing a cell changes nothing here, and losing the sheet loses nothing: resync rebuilds it.

## SMS alerts

Budget alerts are texted to owners when all three are true: Twilio is set in `.env`
(`TWILIO_*`, see `.env.example`), the company has `sms_alerts_enabled` on (`PATCH /company`),
and the owner has a phone number (`PATCH /me`). Anyone else gets the alert in the API log.

## Who sees what

Rules live in `api/app/shared/access.py`; `api/app/db/queries.py` applies the same rules
in SQL. Owners and dispatchers see every job in their company, plus quotes and budgets.
Technicians see only jobs assigned to them, and only their own expenses on those jobs.

## Database migrations

After changing `api/app/db/tables.py`:

```
docker compose exec api alembic revision --autogenerate -m "describe the change"
```

Read the new file in `api/migrations/versions/`, then restart the API (or run
`docker compose exec api alembic upgrade head`). Never edit a migration that's already been applied.

## Layout

```
api/
  app/          grouped by feature: each folder has its routes, request/response shapes and logic
    auth/       sign-up, login, sessions, password reset
    company/    company settings, team (users, technicians), customers
    jobs/       jobs, status changes, files, expenses and time, and the private links:
                customer tracking and signed technician job links
    booking/    online booking: public link and form, the office's request inbox
    waitlist/   the launch waitlist: the public /waitlist page's API, and the copy of the
                signups in Google Sheets. The only feature with no company_id, and off
                unless WAITLIST=open
    calendar/   what a job looks like on a calendar, and keeping the provider in step
    outbox/     the worker that retries every queued write to an outside service
    spend/      budgets and budget alerts
    shared/     used by every feature: models, job status flow, who-sees-what, errors,
                ports (interfaces for outside services), the outbox pattern and its retry
                policy, login/session dependencies
    db/         Postgres: table definitions, sessions, tenant-scoped queries
    adapters/   outside services behind the ports: Google Calendar, Google Sheets, email,
                SMS, notifications, passwords, files
    main.py     FastAPI wiring
  migrations/   Alembic
  tests/
web/            React + Vite
ml/             Phase 7
deploy/         deploy docs, later
infra/terraform/
  modules/app/  APIs, Artifact Registry, service accounts, WIF, Secret Manager, Cloud Run
  envs/dev, envs/prod
```

## Terraform (offline for now)

```
cd infra/terraform/envs/dev
terraform init -backend=false
terraform fmt -recursive ../..
terraform validate
```

Don't run `plan` or `apply` until billing is on. `init` downloads the Google
provider but doesn't touch your GCP account.
