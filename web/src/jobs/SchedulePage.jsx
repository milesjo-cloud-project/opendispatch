// The week calendar: a lane per technician, Open shifts beside it, and Today for technicians.
import { useMemo } from "react";
import { dateKey, initials, startOfWeek } from "../format.js";
import JobCard from "./JobCard.jsx";

export default function SchedulePage({
  jobs,
  technicians,
  customerById,
  technicianById,
  isTechnician,
  isOwner,
  anchor,
  setAnchor,
  setSelected,
  setCreating,
  setPage,
}) {
  const days = useMemo(
    () =>
      Array.from({ length: 7 }, (_, i) => {
        const d = startOfWeek(anchor);
        d.setDate(d.getDate() + i);
        return d;
      }),
    [anchor],
  );
  const weekJobs = useMemo(
    () =>
      jobs.filter(
        (j) =>
          j.scheduled_start &&
          days.some((d) => dateKey(d) === dateKey(new Date(j.scheduled_start))) &&
          !["cancelled", "paid"].includes(j.status),
      ),
    [jobs, days],
  );
  const openJobs = useMemo(
    () =>
      jobs
        .filter((j) => (isTechnician ? !j.scheduled_start : !j.technician_id || !j.scheduled_start))
        .filter((j) => !["cancelled", "paid", "completed", "invoiced"].includes(j.status)),
    [jobs, isTechnician],
  );
  const todayJobs = useMemo(
    () =>
      jobs
        .filter(
          (j) =>
            j.scheduled_start &&
            dateKey(new Date(j.scheduled_start)) === dateKey(new Date()) &&
            j.status !== "cancelled",
        )
        .sort((a, b) => new Date(a.scheduled_start) - new Date(b.scheduled_start)),
    [jobs],
  );
  // Inactive techs keep their lane only while they still have jobs that week
  const lanes = useMemo(
    () => technicians.filter((t) => t.active || weekJobs.some((j) => j.technician_id === t.id)),
    [technicians, weekJobs],
  );
  return (
    <>
      {isTechnician && (
        <section className="today-panel" aria-label="Today">
          <div className="panel-title">
            <div>
              <h2>Today</h2>
              <p>{new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</p>
            </div>
            <span className="count">{todayJobs.length}</span>
          </div>
          {todayJobs.length ? (
            <div className="open-list">
              {todayJobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  customer={customerById[job.customer_id]}
                  onClick={() => setSelected(job)}
                  compact
                />
              ))}
            </div>
          ) : (
            <div className="empty-state">Nothing scheduled for you today.</div>
          )}
        </section>
      )}
      <div className="calendar-toolbar">
        <div className="date-controls">
          <button
            className="square"
            onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() - 7))}
            aria-label="Previous week"
          >
            ‹
          </button>
          <button
            className="square"
            onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7))}
            aria-label="Next week"
          >
            ›
          </button>
          <button className="quiet" onClick={() => setAnchor(new Date())}>
            Today
          </button>
          <strong>
            {days[0].toLocaleDateString([], { month: "short", day: "numeric" })} –{" "}
            {days[6].toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}
          </strong>
        </div>
        <div className="view-label">
          <span className="live-dot" /> WEEK VIEW
        </div>
      </div>
      <div className={`schedule-layout ${isTechnician && !openJobs.length ? "single" : ""}`}>
        {(!isTechnician || openJobs.length > 0) && (
          <aside className="open-panel">
            <div className="panel-title">
              <div>
                <h2>{isTechnician ? "Needs a time" : "Open shifts"}</h2>
                <p>{isTechnician ? "Your jobs waiting to be scheduled" : "Jobs waiting for a time or technician"}</p>
              </div>
              <span className="count">{openJobs.length}</span>
            </div>
            {openJobs.length ? (
              <div className="open-list">
                {openJobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    customer={customerById[job.customer_id]}
                    technician={technicianById[job.technician_id]}
                    onClick={() => setSelected(job)}
                    compact
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state">
                {jobs.length || isTechnician ? (
                  "All jobs are assigned and scheduled."
                ) : (
                  <>
                    No jobs yet.{" "}
                    <button className="link-button" onClick={() => setCreating(true)}>
                      Create the first one
                    </button>
                  </>
                )}
              </div>
            )}
          </aside>
        )}
        <section className="calendar-panel" aria-label="Weekly resource calendar">
          <div className="calendar-grid">
            <div className="grid-corner">TEAM</div>
            {days.map((day) => (
              <div key={dateKey(day)} className={`day-heading ${dateKey(day) === dateKey(new Date()) ? "today" : ""}`}>
                <span>{day.toLocaleDateString([], { weekday: "short" })}</span>
                <strong>{day.getDate()}</strong>
              </div>
            ))}
            {lanes.map((tech) => (
              <div className="resource-row" key={tech.id}>
                <div className="resource-name">
                  <span className="avatar">{initials(tech.display_name)}</span>
                  <span>{tech.display_name}</span>
                </div>
                {days.map((day) => {
                  const assigned = weekJobs.filter(
                    (job) => job.technician_id === tech.id && dateKey(new Date(job.scheduled_start)) === dateKey(day),
                  );
                  return (
                    <div key={dateKey(day)} className="day-cell">
                      {assigned.map((job) => (
                        <JobCard
                          key={job.id}
                          job={job}
                          customer={customerById[job.customer_id]}
                          technician={tech}
                          onClick={() => setSelected(job)}
                        />
                      ))}
                    </div>
                  );
                })}
              </div>
            ))}
            {!lanes.length && (
              <div className="no-resources">
                {isOwner ? (
                  <>
                    Add technicians on the{" "}
                    <button className="link-button" onClick={() => setPage("Team")}>
                      Team page
                    </button>{" "}
                    to see their lanes here.
                  </>
                ) : (
                  "Technician lanes appear here once the owner adds technicians."
                )}
              </div>
            )}
          </div>
        </section>
      </div>
      <div className="legend">
        <span>
          <i className="legend-dot draft-dot" /> Draft
        </span>
        <span>
          <i className="legend-dot scheduled-dot" /> Scheduled
        </span>
        <span>
          <i className="legend-dot active-dot" /> In progress
        </span>
        <span className="muted">
          Select any job to{" "}
          {isTechnician ? "see details and update its progress" : "edit its assignment, time or status"}.
        </span>
      </div>
    </>
  );
}
