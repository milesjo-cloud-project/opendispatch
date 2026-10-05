// The public /track/<token> page a customer opens to follow their job.
import { useCallback, useEffect, useState } from "react";
import { request, statusName } from "../api.js";
import Gear from "../components/Gear.jsx";

export default function CustomerTracking({ token }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const value = await request(`/public/tracking/${encodeURIComponent(token)}`);
      setJob(value);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, [token]);
  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  const progress = ["requested", "scheduled", "dispatched", "en_route", "in_progress", "completed", "invoiced", "paid"];
  const activeIndex = progress.indexOf(job?.status);
  return (
    <main className="tracking-page">
      <header className="tracking-brand">
        <Gear />
        <span>OpenDispatch</span>
        <span className="customer-label">Customer job updates</span>
      </header>
      <section className="tracking-card">
        {error ? (
          <>
            <span className="tracking-symbol">!</span>
            <h1>We can’t open this update</h1>
            <p className="muted">
              This private link may have expired. Please contact your service provider for a new one.
            </p>
          </>
        ) : !job ? (
          <>
            <span className="tracking-symbol spinner">◌</span>
            <h1>Loading your job…</h1>
          </>
        ) : (
          <>
            <p className="eyebrow">LIVE JOB UPDATE</p>
            <h1>{job.title}</h1>
            <div className={`tracking-status status-${job.status}`}>
              <span className="live-dot" />
              {statusName(job.status)}
            </div>
            {job.status === "cancelled" ? (
              <p className="tracking-message">
                This job was cancelled. Please contact your service provider if you have questions.
              </p>
            ) : (
              <div className="progress-list">
                {progress.slice(0, 6).map((step, i) => (
                  <div className={`progress-step ${i <= activeIndex ? "done" : ""}`} key={step}>
                    <span className="progress-mark">{i < activeIndex ? "✓" : i + 1}</span>
                    <span>{statusName(step)}</span>
                  </div>
                ))}
              </div>
            )}
            {job.scheduled_start && (
              <div className="arrival-info">
                <span>Scheduled arrival</span>
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
            <p className="refresh-note">
              Updates automatically every 30 seconds
              {job.last_updated
                ? ` · Last update ${new Date(job.last_updated).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}`
                : ""}
            </p>
          </>
        )}
      </section>
      <footer className="tracking-footer">OpenDispatch · Secure customer updates</footer>
    </main>
  );
}
