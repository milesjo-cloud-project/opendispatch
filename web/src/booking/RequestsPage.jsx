// The office's Requests view: the public booking link (owner controls) and, below it,
// the requests customers sent through it.
import { useCallback, useEffect, useMemo, useState } from "react";
import { post, request } from "../api.js";

export function RequestsPage({ token, isOwner, requests, customers, onChanged, onAccepted }) {
  return (
    <>
      <BookingLinkPanel token={token} isOwner={isOwner} />
      <section className="page-panel" aria-label="New requests">
        {requests.length ? (
          <ul className="request-list">
            {requests.map((r) => (
              <RequestCard
                key={r.id}
                item={r}
                token={token}
                customers={customers}
                onChanged={onChanged}
                onAccepted={onAccepted}
              />
            ))}
          </ul>
        ) : (
          <div className="empty-state">
            No new requests. When a customer uses your booking link, their request shows up here.
          </div>
        )}
      </section>
    </>
  );
}

// Same person? Only a hint for the office: the last 10 digits of a phone, or an email ignoring case.
const digits = (phone) => (phone || "").replace(/\D/g, "").slice(-10);
function looksLike(customer, item) {
  const phone = digits(item.phone);
  const email = (item.email || "").trim().toLowerCase();
  return (
    (phone.length >= 7 && digits(customer.phone) === phone) ||
    (email !== "" && (customer.email || "").trim().toLowerCase() === email)
  );
}

const received = (value) =>
  new Date(value).toLocaleString([], {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });

function RequestCard({ item, token, customers, onChanged, onAccepted }) {
  const [choosing, setChoosing] = useState(false);
  const [customerId, setCustomerId] = useState(""); // "" = new customer from this request
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const matches = useMemo(() => customers.filter((c) => looksLike(c, item)), [customers, item]);
  const others = useMemo(() => customers.filter((c) => !looksLike(c, item)), [customers, item]);

  async function accept() {
    setBusy(true);
    setError("");
    try {
      const job = await post(`/booking-requests/${item.id}/accept`, token, { customer_id: customerId || null });
      await onAccepted(job);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  async function decline() {
    if (!window.confirm(`Decline "${item.title}" from ${item.name}? It's removed from this list.`)) return;
    setBusy(true);
    setError("");
    try {
      await post(`/booking-requests/${item.id}/decline`, token);
      await onChanged();
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  }

  return (
    <li className="request-card">
      <div className="request-head">
        <strong>{item.title}</strong>
        <small className="muted">Received {received(item.created_at)}</small>
      </div>
      <div className="request-contact">
        <span>{item.name}</span>
        {item.phone && <a href={`tel:${item.phone}`}>{item.phone}</a>}
        {item.email && <a href={`mailto:${item.email}`}>{item.email}</a>}
        {item.address && <span className="muted">{item.address}</span>}
      </div>
      {item.description && <p className="request-details">{item.description}</p>}
      {item.preferred_time && (
        <p className="request-when">
          <span>When works best:</span> {item.preferred_time}
        </p>
      )}
      {choosing ? (
        <div className="request-accept">
          <label className="editor-field">
            Customer for this job
            <select value={customerId} disabled={busy} onChange={(e) => setCustomerId(e.target.value)}>
              <option value="">New customer: {item.name} (details from this request)</option>
              {matches.length > 0 && (
                <optgroup label="Same phone or email">
                  {matches.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                      {c.phone ? ` · ${c.phone}` : ""}
                    </option>
                  ))}
                </optgroup>
              )}
              {others.length > 0 && (
                <optgroup label="Other customers">
                  {others.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </label>
          {matches.length > 0 && !customerId && (
            <p className="muted form-hint">
              {matches.length === 1 ? "A customer has" : `${matches.length} customers have`} the same phone or email.
              Pick them above if it's the same person.
            </p>
          )}
          <div className="request-actions">
            <button className="primary" disabled={busy} onClick={accept}>
              {busy ? "Creating…" : "Create job and schedule it"}
            </button>
            <button className="quiet" disabled={busy} onClick={() => setChoosing(false)}>
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="request-actions">
          <button className="primary" disabled={busy} onClick={() => setChoosing(true)}>
            Accept…
          </button>
          <button className="quiet danger" disabled={busy} onClick={decline}>
            Decline
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </li>
  );
}

// Everyone in the office can see and copy the link; only the owner can turn it on, replace or turn it off.
function BookingLinkPanel({ token, isOwner }) {
  const [bookingId, setBookingId] = useState(undefined); // undefined = loading, null = off
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const url = bookingId ? `${window.location.origin}/book/${bookingId}` : "";

  const load = useCallback(
    () =>
      request("/company", token)
        .then((company) => setBookingId(company.booking_id))
        .catch((e) => setError(e.message)),
    [token],
  );
  useEffect(() => {
    load();
  }, [load]);

  async function change(method, question) {
    if (question && !window.confirm(question)) return;
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const result = await request("/company/booking-link", token, { method });
      setBookingId(result ? result.booking_id : null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function copy(event) {
    const input = event.currentTarget.parentElement.querySelector("input");
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      input.select(); // no clipboard access (e.g. plain http): leave it selected to copy by hand
    }
  }

  if (bookingId === undefined && !error) return null;
  return (
    <section className="page-panel booking-link-panel" aria-label="Online booking link">
      <div className="panel-toolbar">
        <div>
          <h2>Online booking</h2>
          <p className="muted">
            {bookingId
              ? "Customers use this link to request a job. Share it on your website, flyers or truck."
              : isOwner
                ? "Off. Turn it on to get a link customers can use to request jobs."
                : "Off. The owner can turn it on."}
          </p>
        </div>
        {isOwner && !bookingId && (
          <button className="primary" disabled={busy} onClick={() => change("POST")}>
            {busy ? "Turning on…" : "Turn on online booking"}
          </button>
        )}
      </div>
      {bookingId && (
        <div className="booking-link-body">
          <div className="copy-link">
            <input readOnly value={url} aria-label="Booking link" onFocus={(e) => e.target.select()} />
            <button className="primary" onClick={copy}>
              {copied ? "Copied" : "Copy"}
            </button>
            <a className="quiet" href={url} target="_blank" rel="noreferrer">
              Open
            </a>
          </div>
          {isOwner && (
            <div className="booking-link-actions">
              <button
                className="quiet small"
                disabled={busy}
                onClick={() =>
                  change(
                    "POST",
                    "Replace the link? The current one stops working right away, including on anything already printed.",
                  )
                }
              >
                Replace link
              </button>
              <button
                className="quiet small danger"
                disabled={busy}
                onClick={() =>
                  change("DELETE", "Turn off online booking? The link stops working. Requests already sent stay here.")
                }
              >
                Turn off
              </button>
            </div>
          )}
        </div>
      )}
      {error && <p className="error page-message">{error}</p>}
    </section>
  );
}
