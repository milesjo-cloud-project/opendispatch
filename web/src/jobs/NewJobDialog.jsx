// Creating a job, with a new or existing customer, in one step.
import { useState } from "react";
import { dollarsToCents, post } from "../api.js";

export default function NewJobDialog({ token, customers, technicians, onClose, onCreated }) {
  const [customerId, setCustomerId] = useState(customers.length ? "" : "new");
  const [customer, setCustomer] = useState({ name: "", phone: "", address: "" });
  const [job, setJob] = useState({ title: "", description: "", technician_id: "", start: "", quote: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (key) => ({ value: job[key], onChange: (e) => setJob({ ...job, [key]: e.target.value }) });
  const customerField = (key) => ({
    value: customer[key],
    onChange: (e) => setCustomer({ ...customer, [key]: e.target.value }),
  });

  async function submit(event) {
    event.preventDefault();
    setError("");
    const quote = dollarsToCents(job.quote);
    if (Number.isNaN(quote)) {
      setError("Enter the quote as dollars, like 1250 or 1250.50.");
      return;
    }
    setBusy(true);
    try {
      // One request: the customer, the job and scheduling are saved together or not at all, so a retry can't duplicate anything.
      // A job with a time goes straight onto the schedule; without one it stays a draft in Open shifts.
      const who =
        customerId === "new"
          ? {
              new_customer: {
                name: customer.name.trim(),
                phone: customer.phone.trim() || null,
                address: customer.address.trim() || null,
              },
            }
          : { customer_id: customerId };
      onCreated(
        await post("/jobs", token, {
          ...who,
          title: job.title.trim(),
          description: job.description.trim() || null,
          technician_id: job.technician_id || null,
          scheduled_start: job.start ? new Date(job.start).toISOString() : null,
          quoted_amount_cents: quote,
          schedule: Boolean(job.start),
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="editor" role="dialog" aria-modal="true" aria-labelledby="new-job-title" onSubmit={submit}>
        <div className="editor-head">
          <div>
            <span className="status-pill requested">New</span>
            <h2 id="new-job-title">New job</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="editor-body">
          <div className="editor-grid">
            <label className="editor-field span-2">
              What's the job?
              <input required maxLength={200} placeholder="e.g. Replace water heater" {...field("title")} />
            </label>
            <label className="editor-field">
              Customer
              <select required value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="" disabled>
                  Choose a customer
                </option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
                <option value="new">＋ New customer</option>
              </select>
            </label>
            <label className="editor-field">
              Technician
              <select {...field("technician_id")}>
                <option value="">Unassigned for now</option>
                {technicians
                  .filter((t) => t.active)
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.display_name}
                    </option>
                  ))}
              </select>
            </label>
            {customerId === "new" && (
              <>
                <label className="editor-field">
                  Customer name
                  <input required maxLength={200} {...customerField("name")} />
                </label>
                <label className="editor-field">
                  Customer phone
                  <input type="tel" maxLength={40} {...customerField("phone")} />
                </label>
                <label className="editor-field span-2">
                  Address
                  <input maxLength={2000} {...customerField("address")} />
                </label>
              </>
            )}
            <label className="editor-field">
              Date and start time
              <input type="datetime-local" {...field("start")} />
            </label>
            <label className="editor-field">
              Quote (optional)
              <input inputMode="decimal" placeholder="$0.00" {...field("quote")} />
            </label>
            <label className="editor-field span-2">
              Job details
              <textarea
                rows={3}
                maxLength={10000}
                placeholder="Access notes, parts, what the customer said…"
                {...field("description")}
              />
            </label>
          </div>
          <p className="muted form-hint">
            {job.start
              ? "This job goes on the schedule right away."
              : "Without a time, the job waits in Open shifts as a draft."}
          </p>
          {error && <p className="error">{error}</p>}
        </div>
        <div className="editor-actions">
          <button type="button" className="quiet" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <span className="actions-spacer" />
          <button className="primary" disabled={busy}>
            {busy ? "Creating…" : "Create job"}
          </button>
        </div>
      </form>
    </div>
  );
}
