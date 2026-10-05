// The job dialog: assignment, time, status buttons, documents and the customer tracking link.
import { useEffect, useState } from "react";
import {
  canCancel,
  canReassign,
  canReschedule,
  canUnassign,
  centsToDollars,
  statusActions,
  statusName,
} from "../api.js";
import { formatBytes, localInput } from "../format.js";

export default function JobEditor({
  job,
  customer,
  technicians,
  onClose,
  onSave,
  onPublish,
  onChangeStatus,
  readOnly,
  onListAttachments,
  onUploadAttachment,
  onDownloadAttachment,
  onCreateTrackingLink,
}) {
  const [technicianId, setTechnicianId] = useState(job.technician_id || "");
  const [scheduledStart, setScheduledStart] = useState(localInput(job.scheduled_start));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [trackingLink, setTrackingLink] = useState("");
  const [linkBusy, setLinkBusy] = useState(false);
  const [statusBusy, setStatusBusy] = useState(false);
  // Drafts are scheduled with the button at the bottom, which also saves the time and tech
  const actions = statusActions(job.status, readOnly).filter((a) => job.status !== "requested");
  // Past a certain stage the tech and time are what happened, so they're shown but locked
  const techLocked = !canReassign(job.status);
  const timeLocked = !canReschedule(job.status);
  const editable = !techLocked || !timeLocked;
  async function changeStatus(to) {
    if (to === "cancelled" && !window.confirm(`Cancel "${job.title}"? This can't be undone.`)) return;
    setStatusBusy(true);
    setError("");
    try {
      await onChangeStatus(job.id, to);
    } catch (e) {
      setError(e.message);
    } finally {
      setStatusBusy(false);
    }
  }
  useEffect(() => {
    onListAttachments(job.id)
      .then(setAttachments)
      .catch((e) => setError(e.message));
  }, [job.id, onListAttachments]);
  async function save(publish = false) {
    setSaving(true);
    setError("");
    try {
      // Only what changed: the API refuses some changes at later stages, so re-sending an untouched field must never count as one
      const changes = {};
      if (technicianId !== (job.technician_id || "")) changes.technician_id = technicianId || null;
      if (scheduledStart !== localInput(job.scheduled_start))
        changes.scheduled_start = scheduledStart ? new Date(scheduledStart).toISOString() : null;
      if (Object.keys(changes).length) await onSave(job.id, changes);
      if (publish && job.status === "requested") await onPublish(job.id);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }
  async function addFiles(files) {
    setError("");
    setUploading(true);
    try {
      for (const file of files) await onUploadAttachment(job.id, file);
      setAttachments(await onListAttachments(job.id));
    } catch (e) {
      setError(e.message);
    } finally {
      setUploading(false);
    }
  }
  async function createTrackingLink() {
    setLinkBusy(true);
    setError("");
    try {
      const result = await onCreateTrackingLink(job.id);
      setTrackingLink(`${window.location.origin}${result.path}`);
    } catch (e) {
      setError(e.message);
    } finally {
      setLinkBusy(false);
    }
  }
  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <section className="editor" role="dialog" aria-modal="true" aria-labelledby="editor-title">
        <div className="editor-head">
          <div>
            <span className={`status-pill ${job.status}`}>{statusName(job.status)}</span>
            <h2 id="editor-title">{job.title}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="editor-body">
          <div className="editor-grid">
            <div className="editor-field">
              <span>Customer</span>
              <strong>{customer?.name || "Customer"}</strong>
              {customer?.phone && <a href={`tel:${customer.phone}`}>{customer.phone}</a>}
            </div>
            {readOnly ? (
              <div className="editor-field">
                <span>Scheduled for</span>
                <strong>
                  {job.scheduled_start
                    ? new Date(job.scheduled_start).toLocaleString([], {
                        weekday: "short",
                        month: "short",
                        day: "numeric",
                        hour: "numeric",
                        minute: "2-digit",
                      })
                    : "Not scheduled yet"}
                </strong>
              </div>
            ) : (
              <>
                <label className="editor-field">
                  Technician
                  <select value={technicianId} disabled={techLocked} onChange={(e) => setTechnicianId(e.target.value)}>
                    <option value="" disabled={!canUnassign(job.status)}>
                      Open shift · unassigned
                    </option>
                    {technicians.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="editor-field">
                  Date and start time
                  <input
                    type="datetime-local"
                    value={scheduledStart}
                    disabled={timeLocked}
                    required={job.status !== "requested"}
                    onChange={(e) => setScheduledStart(e.target.value)}
                  />
                </label>
              </>
            )}
            <div className="editor-field">
              <span>Job status</span>
              <strong>{statusName(job.status)}</strong>
            </div>
            {/* The API leaves the quote out for techs, so this is office only */}
            {!readOnly && (
              <div className="editor-field">
                <span>Quote</span>
                <strong>
                  {job.quoted_amount_cents != null ? centsToDollars(job.quoted_amount_cents) : "No quote"}
                </strong>
              </div>
            )}
          </div>
          {(actions.length > 0 || canCancel(job.status, readOnly)) && (
            <section className="status-actions" aria-label="Job progress">
              <div>
                <h3>{readOnly ? "Update the customer and office" : "Move this job along"}</h3>
                <p>
                  {readOnly
                    ? "Tap as you go. The office sees it right away."
                    : "Each step is recorded in the job history."}
                </p>
              </div>
              <div className="status-buttons">
                {actions.map((a, i) => (
                  <button
                    key={a.to}
                    className={i === 0 ? "primary" : "quiet"}
                    disabled={statusBusy}
                    onClick={() => changeStatus(a.to)}
                  >
                    {a.label}
                  </button>
                ))}
                {canCancel(job.status, readOnly) && (
                  <button className="quiet danger" disabled={statusBusy} onClick={() => changeStatus("cancelled")}>
                    Cancel job
                  </button>
                )}
              </div>
            </section>
          )}
          {job.description && (
            <div className="description">
              <span>Job details</span>
              <p>{job.description}</p>
            </div>
          )}
          <section className="attachments">
            <div className="attachment-heading">
              <div>
                <h3>Job documents</h3>
                <p>Photos and PDFs, up to 12 MB each</p>
              </div>
              <label
                className={`drop-zone ${uploading ? "busy" : ""}`}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  addFiles(e.dataTransfer.files);
                }}
              >
                <input
                  type="file"
                  accept="image/*,application/pdf"
                  multiple
                  disabled={uploading}
                  onChange={(e) => {
                    addFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
                <span>{uploading ? "Uploading…" : "＋ Add images or PDFs"}</span>
              </label>
            </div>
            {attachments.length > 0 && (
              <ul className="attachment-list">
                {attachments.map((file) => (
                  <li key={file.id}>
                    <span className="file-icon">{file.content_type.startsWith("image/") ? "▧" : "▤"}</span>
                    <span className="file-name">
                      <strong>{file.filename}</strong>
                      <small>{formatBytes(file.size_bytes)}</small>
                    </span>
                    <button
                      className="quiet small"
                      onClick={() => onDownloadAttachment(job.id, file).catch((e) => setError(e.message))}
                    >
                      Download
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {/* Mirrors NOT_SHAREABLE in api/app/jobs/tracking.py */}
          {!["requested", "cancelled"].includes(job.status) && !readOnly && (
            <section className="tracking-tools">
              <div>
                <h3>Customer tracking</h3>
                <p>
                  Send the customer a private 90-day link to follow this job, from arrival time to payment. Creating a
                  new link replaces the previous one.
                </p>
              </div>
              <button className="quiet" onClick={createTrackingLink} disabled={linkBusy}>
                {linkBusy ? "Creating…" : "Generate private link"}
              </button>
              {trackingLink && (
                <div className="copy-link">
                  <input readOnly value={trackingLink} aria-label="Customer tracking link" />
                  <button className="primary" onClick={() => navigator.clipboard.writeText(trackingLink)}>
                    Copy
                  </button>
                </div>
              )}
            </section>
          )}
          {error && <p className="error">{error}</p>}
        </div>
        <div className="editor-actions">
          {readOnly ? (
            <>
              <span className="muted">Your assigned job details</span>
              <span className="actions-spacer" />
              <button className="quiet" onClick={onClose}>
                Close
              </button>
            </>
          ) : (
            <>
              {/* Not "Cancel": next to the status buttons that reads like cancelling the job */}
              <button className="quiet" onClick={onClose} disabled={saving}>
                Close
              </button>
              <span className="actions-spacer" />
              {job.status === "requested" && (
                <button className="primary" onClick={() => save(true)} disabled={saving || !scheduledStart}>
                  {saving ? "Saving…" : "Schedule job"}
                </button>
              )}
              {editable ? (
                <button
                  className="primary"
                  onClick={() => save(false)}
                  disabled={saving || (!scheduledStart && job.status !== "requested")}
                >
                  {saving ? "Saving…" : "Save changes"}
                </button>
              ) : (
                <span className="muted">The technician and time are final at this stage</span>
              )}
            </>
          )}
        </div>
      </section>
    </div>
  );
}
