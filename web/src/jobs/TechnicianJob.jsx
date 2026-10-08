// The /j/<token> page a technician opens from their calendar event. No login.
// Read on a phone at the kerb, so the address and the phone number are the first things
// you can tap, and nothing here needs a second page.
import { useCallback, useEffect, useState } from "react";
import { request, statusName } from "../api.js";
import Gear from "../components/Gear.jsx";

export default function TechnicianJob({ token }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const value = await request(`/public/job-link/${encodeURIComponent(token)}`);
      setJob(value);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, [token]);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  return (
    <main className="tracking-page">
      <header className="tracking-brand">
        <Gear />
        <span>OpenDispatch</span>
        <span className="customer-label">Job details</span>
      </header>
      <section className="tracking-card job-link-card">
        {error ? (
          <>
            <span className="tracking-symbol">!</span>
            <h1>We can’t open this job</h1>
            <p className="muted">
              This link may have expired, or the job may have been given to someone else. Ask the office for a new one,
              or sign in to OpenDispatch.
            </p>
          </>
        ) : !job ? (
          <>
            <span className="tracking-symbol spinner">◌</span>
            <h1>Loading the job…</h1>
          </>
        ) : (
          <>
            <p className="eyebrow">YOUR JOB</p>
            <h1>{job.title}</h1>
            <div className={`tracking-status status-${job.status}`}>
              <span className="live-dot" />
              {statusName(job.status)}
            </div>
            {job.scheduled_start && (
              <div className="arrival-info">
                <span>Scheduled start</span>
                <strong>
                  {new Date(job.scheduled_start).toLocaleString([], {
                    weekday: "long",
                    month: "long",
                    day: "numeric",
                    hour: "numeric",
                    minute: "2-digit",
                  })}
                </strong>
              </div>
            )}
            <dl className="job-link-details">
              {job.customer_name && (
                <>
                  <dt>Customer</dt>
                  <dd>{job.customer_name}</dd>
                </>
              )}
              {job.customer_phone && (
                <>
                  <dt>Phone</dt>
                  <dd>
                    <a href={`tel:${job.customer_phone.replace(/[^+\d]/g, "")}`}>{job.customer_phone}</a>
                  </dd>
                </>
              )}
              {job.customer_address && (
                <>
                  <dt>Address</dt>
                  <dd>
                    <a
                      href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(job.customer_address)}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {job.customer_address}
                    </a>
                  </dd>
                </>
              )}
            </dl>
            {job.description && <p className="job-link-notes">{job.description}</p>}
            <p className="refresh-note">
              For {job.technician_name} · Link works until{" "}
              {new Date(job.expires_at).toLocaleDateString([], { month: "long", day: "numeric" })}
            </p>
          </>
        )}
      </section>
      <footer className="tracking-footer">OpenDispatch · Sign in to update this job</footer>
    </main>
  );
}
