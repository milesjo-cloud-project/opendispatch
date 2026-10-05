// The public /book/<booking_id> page: a customer asks for a job, no login needed.
// What they send waits in the office's Requests view; nothing is booked until the office accepts it.
import { useEffect, useState } from "react";
import { post, request } from "../api.js";
import Gear from "../components/Gear.jsx";

const EMPTY = {
  title: "",
  description: "",
  preferred_time: "",
  name: "",
  phone: "",
  email: "",
  address: "",
  website: "", // honeypot: hidden from people, so only bots fill it in
};

export default function BookingPage({ bookingId }) {
  const path = `/public/book/${encodeURIComponent(bookingId)}`;
  const [company, setCompany] = useState(null);
  const [unavailable, setUnavailable] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  useEffect(() => {
    request(path)
      .then((value) => setCompany(value.company_name))
      .catch((e) => {
        if (e.status === 404) setUnavailable(true);
        else setError("We can't reach the booking service right now. Please try again in a minute.");
      });
  }, [path]);

  async function submit(event) {
    event.preventDefault();
    setError("");
    if (!form.phone.trim() && !form.email.trim()) {
      setError("Leave a phone number or an email so we can reach you.");
      return;
    }
    setBusy(true);
    try {
      await post(path, null, Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null])));
      setSent(true);
    } catch (e) {
      // 404: the owner turned booking off while the page was open. 429 explains itself.
      if (e.status === 404) setUnavailable(true);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  let content;
  if (unavailable)
    content = (
      <>
        <span className="tracking-symbol">!</span>
        <h1>Online booking isn't available</h1>
        <p className="muted">This booking link isn't active. Please contact the business directly.</p>
      </>
    );
  else if (sent)
    content = (
      <>
        <span className="tracking-symbol">✓</span>
        <p className="eyebrow">REQUEST SENT</p>
        <h1>Thanks, {company} has your request</h1>
        <p className="tracking-message">
          They'll call or email you to confirm a time. Nothing is booked until they do.
        </p>
        <button
          className="quiet"
          onClick={() => {
            setForm(EMPTY);
            setSent(false);
          }}
        >
          Request another job
        </button>
      </>
    );
  else if (!company)
    content = error ? (
      <>
        <span className="tracking-symbol">!</span>
        <h1>Something went wrong</h1>
        <p className="muted">{error}</p>
      </>
    ) : (
      <>
        <span className="tracking-symbol spinner">◌</span>
        <h1>Loading…</h1>
      </>
    );
  else
    content = (
      <form onSubmit={submit}>
        <p className="eyebrow">REQUEST A JOB</p>
        <h1>{company}</h1>
        <p className="muted booking-intro">Tell us what you need. We'll call or email to confirm a time.</p>
        <div className="editor-grid">
          <label className="editor-field span-2">
            What do you need done?
            <input required maxLength={200} placeholder="e.g. Kitchen sink is clogged" {...field("title")} />
          </label>
          <label className="editor-field span-2">
            Details (optional)
            <textarea
              rows={4}
              maxLength={5000}
              placeholder="What's happening, since when, anything we should know before we arrive"
              {...field("description")}
            />
          </label>
          <label className="editor-field span-2">
            When works best? (optional)
            <input maxLength={200} placeholder="e.g. Weekday mornings, or after 3pm" {...field("preferred_time")} />
          </label>
          <label className="editor-field">
            Your name
            <input required maxLength={200} autoComplete="name" {...field("name")} />
          </label>
          <label className="editor-field">
            Phone
            <input type="tel" maxLength={40} autoComplete="tel" {...field("phone")} />
          </label>
          <label className="editor-field">
            Email
            <input type="email" maxLength={320} autoComplete="email" {...field("email")} />
          </label>
          <label className="editor-field">
            Service address
            <input maxLength={2000} autoComplete="street-address" {...field("address")} />
          </label>
          {/* Honeypot. Off screen rather than display:none (some bots skip hidden fields),
              out of the tab order, and hidden from screen readers so no person fills it in. */}
          <label className="honeypot" aria-hidden="true">
            Website
            <input tabIndex={-1} autoComplete="off" maxLength={500} {...field("website")} />
          </label>
        </div>
        <p className="muted form-hint">We need a phone number or an email to reach you.</p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button className="primary wide booking-submit" disabled={busy}>
          {busy ? "Sending…" : "Send request"}
        </button>
      </form>
    );

  return (
    <main className="tracking-page">
      <header className="tracking-brand">
        <Gear />
        <span>OpenDispatch</span>
        <span className="customer-label">Online booking</span>
      </header>
      <section className="tracking-card">{content}</section>
      <footer className="tracking-footer">Your details go only to the business you're booking with</footer>
    </main>
  );
}
