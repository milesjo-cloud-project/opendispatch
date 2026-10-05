// The app shell: the saved login, loading the company's data, the top nav, and which page shows.
import { useCallback, useEffect, useMemo, useState } from "react";
import { post, request, saveToken, savedToken } from "./api.js";
import Login from "./auth/Login.jsx";
import ResetPassword from "./auth/ResetPassword.jsx";
import BookingPage from "./booking/BookingPage.jsx";
import { RequestsPage } from "./booking/RequestsPage.jsx";
import Gear from "./components/Gear.jsx";
import CustomersPage from "./customers/CustomersPage.jsx";
import CustomerTracking from "./jobs/CustomerTracking.jsx";
import JobEditor from "./jobs/JobEditor.jsx";
import JobsPage from "./jobs/JobsPage.jsx";
import NewJobDialog from "./jobs/NewJobDialog.jsx";
import SchedulePage from "./jobs/SchedulePage.jsx";
import TeamPage from "./team/TeamPage.jsx";

export default function App() {
  const [auth, setAuth] = useState(null);
  const [restoring, setRestoring] = useState(() => Boolean(savedToken()));
  const [resetToken, setResetToken] = useState(() =>
    window.location.pathname === "/reset-password"
      ? (new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "")
      : null,
  );
  const [loginNotice, setLoginNotice] = useState("");
  const [page, setPage] = useState("Schedule");
  const [anchor, setAnchor] = useState(() => new Date());
  const [jobs, setJobs] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [bookingRequests, setBookingRequests] = useState([]); // new ones only, office only
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const token = auth?.token;
  const isTechnician = auth?.user?.role === "technician";
  const isOwner = auth?.user?.role === "owner";

  const signIn = useCallback((result) => {
    saveToken(result.token);
    setLoginNotice("");
    setAuth({ token: result.token, user: result.user });
  }, []);
  const signedOut = useCallback((notice = "") => {
    saveToken(null);
    setAuth(null);
    setJobs([]);
    setBookingRequests([]);
    setSelected(null);
    setCreating(false);
    setPage("Schedule");
    setLoginNotice(notice);
  }, []);

  // Pick up a saved login after a reload; /me says whether it's still good.
  useEffect(() => {
    const saved = savedToken();
    if (!saved) return;
    request("/me", saved)
      .then((user) => setAuth({ token: saved, user }))
      .catch((e) => {
        if (e.status === 401) saveToken(null);
        else setLoginNotice("Can't reach OpenDispatch right now. Check your connection and try again.");
      })
      .finally(() => setRestoring(false));
  }, []);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const nextJobs = await request("/jobs", token);
      const [nextTechs, nextCustomers, nextRequests] = await Promise.all(
        isTechnician
          ? [
              Promise.resolve([{ id: auth.user.technician_id, display_name: "My schedule", active: true }]),
              Promise.resolve(
                nextJobs.map((job) => ({ id: job.customer_id, name: job.customer_name, phone: job.customer_phone })),
              ),
              Promise.resolve([]),
            ]
          : [request("/technicians", token), request("/customers", token), request("/booking-requests", token)],
      );
      setJobs(nextJobs);
      setTechnicians(nextTechs);
      setCustomers(nextCustomers);
      setBookingRequests(nextRequests);
    } catch (e) {
      if (e.status === 401) signedOut("Your session ended. Please sign in again.");
      else setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [token, isTechnician, auth?.user?.technician_id, signedOut]);

  useEffect(() => {
    if (token) load();
  }, [load, token]);
  useEffect(() => {
    if (!token) return undefined;
    const timer = window.setInterval(load, 60_000);
    return () => window.clearInterval(timer);
  }, [load, token]);

  const customerById = useMemo(() => Object.fromEntries(customers.map((c) => [c.id, c])), [customers]);
  const technicianById = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t])), [technicians]);

  async function updateJob(id, fields) {
    await request(`/jobs/${id}`, token, { method: "PATCH", body: JSON.stringify(fields) });
    await load();
  }
  async function publishJob(id) {
    await post(`/jobs/${id}/status`, token, { status: "scheduled" });
    await load();
  }
  async function changeStatus(id, status) {
    const updated = await post(`/jobs/${id}/status`, token, { status });
    setSelected((current) => (current?.id === id ? { ...current, ...updated } : current));
    await load();
  }
  const listAttachments = useCallback((id) => request(`/jobs/${id}/attachments`, token), [token]);
  const uploadAttachment = useCallback(
    (id, file) => {
      const body = new FormData();
      body.append("file", file);
      return request(`/jobs/${id}/attachments`, token, { method: "POST", body });
    },
    [token],
  );
  const createTrackingLink = useCallback(
    (id) => request(`/jobs/${id}/tracking-link`, token, { method: "POST" }),
    [token],
  );
  const downloadAttachment = useCallback(
    async (id, file) => {
      const response = await fetch(`/api/jobs/${id}/attachments/${file.id}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error("Could not download this file");
      const url = URL.createObjectURL(await response.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = file.filename;
      a.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    [token],
  );
  async function logout() {
    try {
      await request("/auth/logout", token, { method: "POST" });
    } catch {
      /* signing out on this device is what matters */
    } finally {
      signedOut();
    }
  }

  const trackingToken = window.location.pathname.match(/^\/track\/([^/]+)\/?$/)?.[1];
  if (trackingToken) return <CustomerTracking token={trackingToken} />;
  const bookingId = window.location.pathname.match(/^\/book\/([^/]+)\/?$/)?.[1];
  if (bookingId) return <BookingPage bookingId={bookingId} />;
  if (resetToken !== null)
    return (
      <ResetPassword
        token={resetToken}
        onDone={(notice) => {
          window.history.replaceState(null, "", "/");
          setLoginNotice(notice);
          setResetToken(null);
        }}
      />
    );
  if (restoring)
    return (
      <main className="login-wrap">
        <div className="brand">
          <Gear />
          <span>Opening OpenDispatch…</span>
        </div>
      </main>
    );
  if (!auth) return <Login key={loginNotice} notice={loginNotice} onLogin={signIn} />;

  const pages = isTechnician ? ["Schedule", "Jobs"] : ["Schedule", "Jobs", "Requests", "Customers", "Team"];
  const headings = {
    Schedule: isTechnician
      ? ["My schedule", "Your assigned jobs for the week."]
      : ["Schedule by resource", "Plan the week and keep every crew moving."],
    Jobs: [
      isTechnician ? "My jobs" : "All jobs",
      `${jobs.length} job${jobs.length === 1 ? "" : "s"}${isTechnician ? " assigned to you" : " in your workspace"}`,
    ],
    Requests: [
      "Requests",
      bookingRequests.length
        ? `${bookingRequests.length} new request${bookingRequests.length === 1 ? "" : "s"} from your booking link`
        : "Jobs customers asked for through your booking link",
    ],
    Customers: ["Customers", `${customers.length} customer${customers.length === 1 ? "" : "s"}`],
    Team: ["Team", "Owners, dispatchers and technicians"],
  };
  const [title, subtitle] = headings[page];

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand compact">
          <Gear />
          <span>OpenDispatch</span>
        </div>
        <nav aria-label="Main navigation">
          {pages.map((item) => (
            <button
              key={item}
              className={`nav-link ${page === item ? "active" : ""}`}
              aria-current={page === item ? "page" : undefined}
              onClick={() => setPage(item)}
            >
              {item}
              {item === "Requests" && bookingRequests.length > 0 && (
                <span className="nav-count" aria-label={`${bookingRequests.length} new`}>
                  {bookingRequests.length}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="top-actions">
          <span className="user-label">{auth.user?.email}</span>
          <button className="quiet small" onClick={logout}>
            Sign out
          </button>
        </div>
      </header>
      <section className="workspace">
        <div className="page-heading">
          <div>
            <p className="eyebrow">{isTechnician ? "MY WORK" : "DISPATCH DESK"}</p>
            <h1>{title}</h1>
            <p className="muted">{subtitle}</p>
          </div>
          <div className="heading-actions">
            {["Schedule", "Jobs", "Requests"].includes(page) && (
              <button className="quiet" onClick={load} disabled={loading}>
                {loading ? "Refreshing…" : "Refresh"}
              </button>
            )}
            {!isTechnician && (
              <button className="primary" onClick={() => setCreating(true)}>
                ＋ New job
              </button>
            )}
          </div>
        </div>
        {error && (
          <div className="notice" role="status">
            {error}
            <button onClick={() => setError("")} aria-label="Dismiss">
              ×
            </button>
          </div>
        )}
        {page === "Schedule" && (
          <SchedulePage
            jobs={jobs}
            technicians={technicians}
            customerById={customerById}
            technicianById={technicianById}
            isTechnician={isTechnician}
            isOwner={isOwner}
            anchor={anchor}
            setAnchor={setAnchor}
            setSelected={setSelected}
            setCreating={setCreating}
            setPage={setPage}
          />
        )}
        {page === "Jobs" && (
          <JobsPage
            jobs={jobs}
            customerById={customerById}
            technicianById={technicianById}
            isTechnician={isTechnician}
            setSelected={setSelected}
          />
        )}
        {page === "Requests" && (
          <RequestsPage
            token={token}
            isOwner={isOwner}
            requests={bookingRequests}
            customers={customers}
            onChanged={load}
            onAccepted={async (job) => {
              await load(); // picks up the job and, if one was made, the new customer
              setSelected(job); // straight into the editor to give it a tech and a time
            }}
          />
        )}
        {page === "Customers" && <CustomersPage token={token} customers={customers} onChanged={load} />}
        {page === "Team" && (
          <TeamPage token={token} isOwner={isOwner} meId={auth.user?.id} technicians={technicians} onChanged={load} />
        )}
        <footer className="app-footer">
          <Gear />
          <span>OpenDispatch</span>
          <span className="muted">Scheduling that works for the people doing the work.</span>
        </footer>
      </section>
      {selected && (
        <JobEditor
          key={selected.id}
          job={selected}
          customer={customerById[selected.customer_id]}
          technicians={technicians.filter((t) => t.active || t.id === selected.technician_id)}
          onClose={() => setSelected(null)}
          onSave={updateJob}
          onPublish={publishJob}
          onChangeStatus={changeStatus}
          readOnly={isTechnician}
          onListAttachments={listAttachments}
          onUploadAttachment={uploadAttachment}
          onDownloadAttachment={downloadAttachment}
          onCreateTrackingLink={createTrackingLink}
        />
      )}
      {creating && (
        <NewJobDialog
          token={token}
          customers={customers}
          technicians={technicians}
          onClose={() => setCreating(false)}
          onCreated={async (job) => {
            setCreating(false);
            await load();
            setSelected(job);
          }}
        />
      )}
    </main>
  );
}
