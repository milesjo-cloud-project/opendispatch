// One job on the calendar or in a list.
import { statusName } from "../api.js";
import { clock } from "../format.js";

export default function JobCard({ job, customer, technician, onClick, compact = false }) {
  return (
    <button
      className={`job-card ${compact ? "compact-card" : ""} status-${job.status}`}
      onClick={onClick}
      title={`${job.title} · ${customer?.name || "Customer"}`}
    >
      <span className="job-time">{clock(job.scheduled_start)}</span>
      <strong>{job.title}</strong>
      <span className="job-customer">{customer?.name || "Customer"}</span>
      {!compact && <span className="job-technician">{technician?.display_name || "Unassigned"}</span>}
      <span className={`status-pill ${job.status}`}>{statusName(job.status)}</span>
    </button>
  );
}
