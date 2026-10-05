// Every job in one list (a technician sees only their own).
import JobCard from "./JobCard.jsx";

export default function JobsPage({ jobs, customerById, technicianById, isTechnician, setSelected }) {
  return jobs.length ? (
    <section className="jobs-list">
      {jobs.map((job) => (
        <JobCard
          key={job.id}
          job={job}
          customer={customerById[job.customer_id]}
          technician={technicianById[job.technician_id]}
          onClick={() => setSelected(job)}
          compact
        />
      ))}
    </section>
  ) : (
    <div className="empty-state">
      {isTechnician ? "No jobs are assigned to you yet." : "No jobs yet. Use “New job” to add one."}
    </div>
  );
}
