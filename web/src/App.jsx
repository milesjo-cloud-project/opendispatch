import { useCallback, useEffect, useMemo, useState } from "react";
import { canCancel, post, request, saveToken, savedToken, statusActions, statusName } from "./api.js";
import { CustomersPage, NewJobDialog, TeamPage, initials } from "./pages.jsx";

function Gear() {
  const teeth = Array.from({ length: 8 }, (_, i) => (
    <rect key={i} x="21" y="2" width="6" height="9" rx="1" transform={`rotate(${i * 45} 24 24)`} />
  ));
  return <svg className="gear" viewBox="0 0 48 48" aria-hidden="true">{teeth}<circle cx="24" cy="24" r="14" /><circle cx="24" cy="24" r="5.5" className="gear-hole" /></svg>;
}

const dateKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const startOfWeek = (date) => { const d = new Date(date); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return d; };
const localInput = (value) => {
  if (!value) return "";
  const d = new Date(value);
  return `${dateKey(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
const clock = (value) => value ? new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "Time not set";

function Login({ onLogin, notice = "" }) {
  const [mode, setMode] = useState("login"); // login | signup | forgot
  const [form, setForm] = useState({ company_name: "", email: "", password: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(notice);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });
  const switchTo = (next) => { setMode(next); setError(""); setMessage(""); };
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      if (mode === "forgot") { const result = await post("/auth/password-reset/request", null, { email: form.email }); setMessage(result.detail); setMode("login"); }
      else if (mode === "signup") onLogin(await post("/auth/signup", null, { company_name: form.company_name.trim(), email: form.email.trim(), password: form.password, phone: form.phone.trim() || null }));
      else onLogin(await post("/auth/login", null, { email: form.email, password: form.password }));
    }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  const heading = { login: "Welcome back", signup: "Start your company", forgot: "Reset your password" }[mode];
  const action = { login: ["Sign in", "Signing in…"], signup: ["Create account", "Creating…"], forgot: ["Send reset link", "Sending…"] }[mode];
  return <main className="login-wrap"><form className="login-card" onSubmit={submit}><div className="brand"><Gear /><div><h1>OpenDispatch</h1><p>Field service, in sync.</p></div></div><h2>{heading}</h2>
    {mode === "forgot" && <p className="muted">Enter your email and we'll send you a link to choose a new password.</p>}
    {mode === "signup" && <p className="muted">You'll be the owner. Add your dispatchers and technicians after you're in.</p>}
    {mode === "signup" && <label>Company name<input required maxLength={200} autoComplete="organization" {...field("company_name")} /></label>}
    <label>Email<input type="email" autoComplete="username" required {...field("email")} /></label>
    {mode !== "forgot" && <label>Password<input type="password" autoComplete={mode === "signup" ? "new-password" : "current-password"} required minLength={mode === "signup" ? 12 : undefined} {...field("password")} /></label>}
    {mode === "signup" && <label>Mobile phone (optional, for budget alerts)<input type="tel" maxLength={32} autoComplete="tel" {...field("phone")} /></label>}
    {message && <p className="success" role="status">{message}</p>}{error && <p className="error">{error}</p>}
    <button className="primary wide" disabled={busy}>{busy ? action[1] : action[0]}</button>
    <div className="login-links">{mode === "login" ? <><button type="button" className="link-button" onClick={() => switchTo("forgot")}>Forgot password?</button><button type="button" className="link-button" onClick={() => switchTo("signup")}>New company? Sign up</button></> : <button type="button" className="link-button" onClick={() => switchTo("login")}>Back to sign in</button>}</div>
  </form></main>;
}

function ResetPassword({ token, onDone }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setError("");
    if (password !== confirm) { setError("The passwords don't match."); return; }
    setBusy(true);
    try { await post("/auth/password-reset/confirm", null, { token, new_password: password }); onDone("Your password was changed. Sign in with the new one."); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <main className="login-wrap"><form className="login-card" onSubmit={submit}><div className="brand"><Gear /><div><h1>OpenDispatch</h1><p>Field service, in sync.</p></div></div><h2>Choose a new password</h2>{!token ? <p className="error">This reset link is incomplete. Request a new one from the sign-in page.</p> : <><label>New password<input type="password" autoComplete="new-password" minLength={12} required value={password} onChange={(e) => setPassword(e.target.value)} /></label><label>Confirm new password<input type="password" autoComplete="new-password" minLength={12} required value={confirm} onChange={(e) => setConfirm(e.target.value)} /></label><p className="muted">At least 12 characters. You'll be signed out on every device.</p>{error && <p className="error">{error}</p>}<button className="primary wide" disabled={busy}>{busy ? "Saving…" : "Set new password"}</button></>}<button type="button" className="link-button" onClick={() => onDone("")}>Back to sign in</button></form></main>;
}

function JobEditor({ job, customer, technicians, onClose, onSave, onPublish, onChangeStatus, readOnly, onListAttachments, onUploadAttachment, onDownloadAttachment, onCreateTrackingLink }) {
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
  async function changeStatus(to) {
    if (to === "cancelled" && !window.confirm(`Cancel "${job.title}"? This can't be undone.`)) return;
    setStatusBusy(true); setError("");
    try { await onChangeStatus(job.id, to); }
    catch (e) { setError(e.message); }
    finally { setStatusBusy(false); }
  }
  useEffect(() => { onListAttachments(job.id).then(setAttachments).catch((e) => setError(e.message)); }, [job.id, onListAttachments]);
  async function save(publish = false) {
    setSaving(true); setError("");
    try {
      await onSave(job.id, { technician_id: technicianId || null, scheduled_start: scheduledStart ? new Date(scheduledStart).toISOString() : null });
      if (publish && job.status === "requested") await onPublish(job.id);
      onClose();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  }
  async function addFiles(files) {
    setError(""); setUploading(true);
    try {
      for (const file of files) await onUploadAttachment(job.id, file);
      setAttachments(await onListAttachments(job.id));
    } catch (e) { setError(e.message); }
    finally { setUploading(false); }
  }
  async function createTrackingLink() {
    setLinkBusy(true); setError("");
    try { const result = await onCreateTrackingLink(job.id); setTrackingLink(`${window.location.origin}${result.path}`); }
    catch (e) { setError(e.message); }
    finally { setLinkBusy(false); }
  }
  return <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><section className="editor" role="dialog" aria-modal="true" aria-labelledby="editor-title">
    <div className="editor-head"><div><span className={`status-pill ${job.status}`}>{statusName(job.status)}</span><h2 id="editor-title">{job.title}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close">×</button></div>
    <div className="editor-body"><div className="editor-grid"><div className="editor-field"><span>Customer</span><strong>{customer?.name || "Customer"}</strong>{customer?.phone && <a href={`tel:${customer.phone}`}>{customer.phone}</a>}</div>{readOnly ? <div className="editor-field"><span>Scheduled for</span><strong>{job.scheduled_start ? new Date(job.scheduled_start).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Not scheduled yet"}</strong></div> : <><label className="editor-field">Technician<select value={technicianId} onChange={(e) => setTechnicianId(e.target.value)}><option value="">Open shift · unassigned</option>{technicians.map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}</select></label><label className="editor-field">Date and start time<input type="datetime-local" value={scheduledStart} onChange={(e) => setScheduledStart(e.target.value)} /></label></>}<div className="editor-field"><span>Job status</span><strong>{statusName(job.status)}</strong></div></div>
      {(actions.length > 0 || canCancel(job.status, readOnly)) && <section className="status-actions" aria-label="Job progress"><div><h3>{readOnly ? "Update the customer and office" : "Move this job along"}</h3><p>{readOnly ? "Tap as you go. The office sees it right away." : "Each step is recorded in the job history."}</p></div><div className="status-buttons">{actions.map((a, i) => <button key={a.to} className={i === 0 ? "primary" : "quiet"} disabled={statusBusy} onClick={() => changeStatus(a.to)}>{a.label}</button>)}{canCancel(job.status, readOnly) && <button className="quiet danger" disabled={statusBusy} onClick={() => changeStatus("cancelled")}>Cancel job</button>}</div></section>}
      {job.description && <div className="description"><span>Job details</span><p>{job.description}</p></div>}
      <section className="attachments"><div className="attachment-heading"><div><h3>Job documents</h3><p>Photos and PDFs, up to 12 MB each</p></div><label className={`drop-zone ${uploading ? "busy" : ""}`} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); addFiles(e.dataTransfer.files); }}><input type="file" accept="image/*,application/pdf" multiple disabled={uploading} onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} /><span>{uploading ? "Uploading…" : "＋ Add images or PDFs"}</span></label></div>
        {attachments.length > 0 && <ul className="attachment-list">{attachments.map((file) => <li key={file.id}><span className="file-icon">{file.content_type.startsWith("image/") ? "▧" : "▤"}</span><span className="file-name"><strong>{file.filename}</strong><small>{formatBytes(file.size_bytes)}</small></span><button className="quiet small" onClick={() => onDownloadAttachment(job.id, file).catch((e) => setError(e.message))}>Download</button></li>)}</ul>}
      </section>
      {["invoiced", "paid"].includes(job.status) && !readOnly && <section className="tracking-tools"><div><h3>Customer tracking</h3><p>Create a private 90-day link for the invoice recipient. Creating a new link replaces the previous one.</p></div><button className="quiet" onClick={createTrackingLink} disabled={linkBusy}>{linkBusy ? "Creating…" : "Generate private link"}</button>{trackingLink && <div className="copy-link"><input readOnly value={trackingLink} aria-label="Customer tracking link" /><button className="primary" onClick={() => navigator.clipboard.writeText(trackingLink)}>Copy</button></div>}</section>}
      {error && <p className="error">{error}</p>}</div>
    <div className="editor-actions">{readOnly ? <><span className="muted">Your assigned job details</span><span className="actions-spacer" /><button className="quiet" onClick={onClose}>Close</button></> : <><button className="quiet" onClick={onClose} disabled={saving}>Cancel</button><span className="actions-spacer" />{job.status === "requested" && <button className="primary" onClick={() => save(true)} disabled={saving || !scheduledStart}>{saving ? "Saving…" : "Schedule job"}</button>}<button className="primary" onClick={() => save(false)} disabled={saving}>{saving ? "Saving…" : "Save changes"}</button></>}</div>
  </section></div>;
}

export default function App() {
  const [auth, setAuth] = useState(null);
  const [restoring, setRestoring] = useState(() => Boolean(savedToken()));
  const [resetToken, setResetToken] = useState(() => window.location.pathname === "/reset-password" ? new URLSearchParams(window.location.hash.slice(1)).get("token") ?? "" : null);
  const [loginNotice, setLoginNotice] = useState("");
  const [page, setPage] = useState("Schedule");
  const [anchor, setAnchor] = useState(() => new Date());
  const [jobs, setJobs] = useState([]);
  const [technicians, setTechnicians] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const token = auth?.token;
  const isTechnician = auth?.user?.role === "technician";
  const isOwner = auth?.user?.role === "owner";

  const signIn = useCallback((result) => { saveToken(result.token); setLoginNotice(""); setAuth({ token: result.token, user: result.user }); }, []);
  const signedOut = useCallback((notice = "") => { saveToken(null); setAuth(null); setJobs([]); setSelected(null); setCreating(false); setPage("Schedule"); setLoginNotice(notice); }, []);

  // Pick up a saved login after a reload; /me says whether it's still good.
  useEffect(() => {
    const saved = savedToken();
    if (!saved) return;
    request("/me", saved)
      .then((user) => setAuth({ token: saved, user }))
      .catch((e) => { if (e.status === 401) saveToken(null); else setLoginNotice("Can't reach OpenDispatch right now. Check your connection and try again."); })
      .finally(() => setRestoring(false));
  }, []);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true); setError("");
    try {
      const nextJobs = await request("/jobs", token);
      const [nextTechs, nextCustomers] = await Promise.all(isTechnician
        ? [Promise.resolve([{ id: auth.user.technician_id, display_name: "My schedule", active: true }]), Promise.resolve(nextJobs.map((job) => ({ id: job.customer_id, name: job.customer_name, phone: job.customer_phone })))]
        : [request("/technicians", token), request("/customers", token)]);
      setJobs(nextJobs); setTechnicians(nextTechs); setCustomers(nextCustomers);
    } catch (e) { if (e.status === 401) signedOut("Your session ended. Please sign in again."); else setError(e.message); }
    finally { setLoading(false); }
  }, [token, isTechnician, auth?.user?.technician_id, signedOut]);

  useEffect(() => { if (token) load(); }, [load, token]);
  useEffect(() => { if (!token) return undefined; const timer = window.setInterval(load, 60_000); return () => window.clearInterval(timer); }, [load, token]);

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => { const d = startOfWeek(anchor); d.setDate(d.getDate() + i); return d; }), [anchor]);
  const customerById = useMemo(() => Object.fromEntries(customers.map((c) => [c.id, c])), [customers]);
  const technicianById = useMemo(() => Object.fromEntries(technicians.map((t) => [t.id, t])), [technicians]);
  const weekJobs = useMemo(() => jobs.filter((j) => j.scheduled_start && days.some((d) => dateKey(d) === dateKey(new Date(j.scheduled_start))) && !["cancelled", "paid"].includes(j.status)), [jobs, days]);
  const openJobs = useMemo(() => jobs.filter((j) => (isTechnician ? !j.scheduled_start : !j.technician_id || !j.scheduled_start)).filter((j) => !["cancelled", "paid", "completed", "invoiced"].includes(j.status)), [jobs, isTechnician]);
  const todayJobs = useMemo(() => jobs.filter((j) => j.scheduled_start && dateKey(new Date(j.scheduled_start)) === dateKey(new Date()) && j.status !== "cancelled").sort((a, b) => new Date(a.scheduled_start) - new Date(b.scheduled_start)), [jobs]);
  // Inactive techs keep their lane only while they still have jobs that week
  const lanes = useMemo(() => technicians.filter((t) => t.active || weekJobs.some((j) => j.technician_id === t.id)), [technicians, weekJobs]);

  async function updateJob(id, fields) { await request(`/jobs/${id}`, token, { method: "PATCH", body: JSON.stringify(fields) }); await load(); }
  async function publishJob(id) { await post(`/jobs/${id}/status`, token, { status: "scheduled" }); await load(); }
  async function changeStatus(id, status) { const updated = await post(`/jobs/${id}/status`, token, { status }); setSelected((current) => current?.id === id ? { ...current, ...updated } : current); await load(); }
  const listAttachments = useCallback((id) => request(`/jobs/${id}/attachments`, token), [token]);
  const uploadAttachment = useCallback((id, file) => { const body = new FormData(); body.append("file", file); return request(`/jobs/${id}/attachments`, token, { method: "POST", body }); }, [token]);
  const createTrackingLink = useCallback((id) => request(`/jobs/${id}/tracking-link`, token, { method: "POST" }), [token]);
  const downloadAttachment = useCallback(async (id, file) => { const response = await fetch(`/api/jobs/${id}/attachments/${file.id}`, { headers: { Authorization: `Bearer ${token}` } }); if (!response.ok) throw new Error("Could not download this file"); const url = URL.createObjectURL(await response.blob()); const a = document.createElement("a"); a.href = url; a.download = file.filename; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }, [token]);
  async function logout() { try { await request("/auth/logout", token, { method: "POST" }); } catch { /* signing out on this device is what matters */ } finally { signedOut(); } }

  const trackingToken = window.location.pathname.match(/^\/track\/([^/]+)\/?$/)?.[1];
  if (trackingToken) return <CustomerTracking token={trackingToken} />;
  if (resetToken !== null) return <ResetPassword token={resetToken} onDone={(notice) => { window.history.replaceState(null, "", "/"); setLoginNotice(notice); setResetToken(null); }} />;
  if (restoring) return <main className="login-wrap"><div className="brand"><Gear /><span>Opening OpenDispatch…</span></div></main>;
  if (!auth) return <Login key={loginNotice} notice={loginNotice} onLogin={signIn} />;

  const pages = isTechnician ? ["Schedule", "Jobs"] : ["Schedule", "Jobs", "Customers", "Team"];
  const headings = {
    Schedule: isTechnician ? ["My schedule", "Your assigned jobs for the week."] : ["Schedule by resource", "Plan the week and keep every crew moving."],
    Jobs: [isTechnician ? "My jobs" : "All jobs", `${jobs.length} job${jobs.length === 1 ? "" : "s"}${isTechnician ? " assigned to you" : " in your workspace"}`],
    Customers: ["Customers", `${customers.length} customer${customers.length === 1 ? "" : "s"}`],
    Team: ["Team", "Owners, dispatchers and technicians"],
  };
  const [title, subtitle] = headings[page];

  return <main className="app-shell">
    <header className="topbar"><div className="brand compact"><Gear /><span>OpenDispatch</span></div><nav aria-label="Main navigation">{pages.map((item) => <button key={item} className={`nav-link ${page === item ? "active" : ""}`} aria-current={page === item ? "page" : undefined} onClick={() => setPage(item)}>{item}</button>)}</nav><div className="top-actions"><span className="user-label">{auth.user?.email}</span><button className="quiet small" onClick={logout}>Sign out</button></div></header>
    <section className="workspace"><div className="page-heading"><div><p className="eyebrow">{isTechnician ? "MY WORK" : "DISPATCH DESK"}</p><h1>{title}</h1><p className="muted">{subtitle}</p></div><div className="heading-actions">{["Schedule", "Jobs"].includes(page) && <button className="quiet" onClick={load} disabled={loading}>{loading ? "Refreshing…" : "Refresh"}</button>}{!isTechnician && <button className="primary" onClick={() => setCreating(true)}>＋ New job</button>}</div></div>
    {error && <div className="notice" role="status">{error}<button onClick={() => setError("")} aria-label="Dismiss">×</button></div>}
    {page === "Schedule" && <>
      {isTechnician && <section className="today-panel" aria-label="Today"><div className="panel-title"><div><h2>Today</h2><p>{new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</p></div><span className="count">{todayJobs.length}</span></div>{todayJobs.length ? <div className="open-list">{todayJobs.map((job) => <JobCard key={job.id} job={job} customer={customerById[job.customer_id]} onClick={() => setSelected(job)} compact />)}</div> : <div className="empty-state">Nothing scheduled for you today.</div>}</section>}
      <div className="calendar-toolbar"><div className="date-controls"><button className="square" onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() - 7))} aria-label="Previous week">‹</button><button className="square" onClick={() => setAnchor((d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + 7))} aria-label="Next week">›</button><button className="quiet" onClick={() => setAnchor(new Date())}>Today</button><strong>{days[0].toLocaleDateString([], { month: "short", day: "numeric" })} – {days[6].toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}</strong></div><div className="view-label"><span className="live-dot" /> WEEK VIEW</div></div>
      <div className={`schedule-layout ${isTechnician && !openJobs.length ? "single" : ""}`}>{(!isTechnician || openJobs.length > 0) && <aside className="open-panel"><div className="panel-title"><div><h2>{isTechnician ? "Needs a time" : "Open shifts"}</h2><p>{isTechnician ? "Your jobs waiting to be scheduled" : "Jobs waiting for a time or technician"}</p></div><span className="count">{openJobs.length}</span></div>{openJobs.length ? <div className="open-list">{openJobs.map((job) => <JobCard key={job.id} job={job} customer={customerById[job.customer_id]} technician={technicianById[job.technician_id]} onClick={() => setSelected(job)} compact />)}</div> : <div className="empty-state">{jobs.length || isTechnician ? "All jobs are assigned and scheduled." : <>No jobs yet. <button className="link-button" onClick={() => setCreating(true)}>Create the first one</button></>}</div>}</aside>}
      <section className="calendar-panel" aria-label="Weekly resource calendar"><div className="calendar-grid"><div className="grid-corner">TEAM</div>{days.map((day) => <div key={dateKey(day)} className={`day-heading ${dateKey(day) === dateKey(new Date()) ? "today" : ""}`}><span>{day.toLocaleDateString([], { weekday: "short" })}</span><strong>{day.getDate()}</strong></div>)}
      {lanes.map((tech) => <div className="resource-row" key={tech.id}><div className="resource-name"><span className="avatar">{initials(tech.display_name)}</span><span>{tech.display_name}</span></div>{days.map((day) => { const assigned = weekJobs.filter((job) => job.technician_id === tech.id && dateKey(new Date(job.scheduled_start)) === dateKey(day)); return <div key={dateKey(day)} className="day-cell">{assigned.map((job) => <JobCard key={job.id} job={job} customer={customerById[job.customer_id]} technician={tech} onClick={() => setSelected(job)} />)}</div>; })}</div>)}
      {!lanes.length && <div className="no-resources">{isOwner ? <>Add technicians on the <button className="link-button" onClick={() => setPage("Team")}>Team page</button> to see their lanes here.</> : "Technician lanes appear here once the owner adds technicians."}</div>}</div></section></div>
      <div className="legend"><span><i className="legend-dot draft-dot" /> Draft</span><span><i className="legend-dot scheduled-dot" /> Scheduled</span><span><i className="legend-dot active-dot" /> In progress</span><span className="muted">Select any job to {isTechnician ? "see details and update its progress" : "edit its assignment, time or status"}.</span></div>
    </>}
    {page === "Jobs" && (jobs.length ? <section className="jobs-list">{jobs.map((job) => <JobCard key={job.id} job={job} customer={customerById[job.customer_id]} technician={technicianById[job.technician_id]} onClick={() => setSelected(job)} compact />)}</section> : <div className="empty-state">{isTechnician ? "No jobs are assigned to you yet." : "No jobs yet. Use “New job” to add one."}</div>)}
    {page === "Customers" && <CustomersPage token={token} customers={customers} onChanged={load} />}
    {page === "Team" && <TeamPage token={token} isOwner={isOwner} technicians={technicians} onChanged={load} />}
    <footer className="app-footer"><Gear /><span>OpenDispatch</span><span className="muted">Scheduling that works for the people doing the work.</span></footer>
    </section>
    {selected && <JobEditor key={selected.id} job={selected} customer={customerById[selected.customer_id]} technicians={technicians.filter((t) => t.active || t.id === selected.technician_id)} onClose={() => setSelected(null)} onSave={updateJob} onPublish={publishJob} onChangeStatus={changeStatus} readOnly={isTechnician} onListAttachments={listAttachments} onUploadAttachment={uploadAttachment} onDownloadAttachment={downloadAttachment} onCreateTrackingLink={createTrackingLink} />}
    {creating && <NewJobDialog token={token} customers={customers} technicians={technicians} onClose={() => setCreating(false)} onCreated={async (job) => { setCreating(false); await load(); setSelected(job); }} />}
  </main>;
}

function JobCard({ job, customer, technician, onClick, compact = false }) {
  return <button className={`job-card ${compact ? "compact-card" : ""} status-${job.status}`} onClick={onClick} title={`${job.title} · ${customer?.name || "Customer"}`}>
    <span className="job-time">{clock(job.scheduled_start)}</span><strong>{job.title}</strong><span className="job-customer">{customer?.name || "Customer"}</span>{!compact && <span className="job-technician">{technician?.display_name || "Unassigned"}</span>}<span className={`status-pill ${job.status}`}>{statusName(job.status)}</span>
  </button>;
}

function formatBytes(value) { return value < 1_048_576 ? `${Math.round(value / 1024)} KB` : `${(value / 1_048_576).toFixed(1)} MB`; }

function CustomerTracking({ token }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try { const value = await request(`/public/tracking/${encodeURIComponent(token)}`); setJob(value); setError(""); }
    catch (e) { setError(e.message); }
  }, [token]);
  useEffect(() => { refresh(); const timer = window.setInterval(refresh, 30_000); return () => window.clearInterval(timer); }, [refresh]);
  const progress = ["requested", "scheduled", "dispatched", "en_route", "in_progress", "completed", "invoiced", "paid"];
  const activeIndex = progress.indexOf(job?.status);
  return <main className="tracking-page"><header className="tracking-brand"><Gear /><span>OpenDispatch</span><span className="customer-label">Customer job updates</span></header>
    <section className="tracking-card">{error ? <><span className="tracking-symbol">!</span><h1>We can’t open this update</h1><p className="muted">This private link may have expired. Please contact your service provider for a new one.</p></> : !job ? <><span className="tracking-symbol spinner">◌</span><h1>Loading your job…</h1></> : <>
      <p className="eyebrow">LIVE JOB UPDATE</p><h1>{job.title}</h1><div className={`tracking-status status-${job.status}`}><span className="live-dot" />{statusName(job.status)}</div>
      {job.status === "cancelled" ? <p className="tracking-message">This job was cancelled. Please contact your service provider if you have questions.</p> : <div className="progress-list">{progress.slice(0, 6).map((step, i) => <div className={`progress-step ${i <= activeIndex ? "done" : ""}`} key={step}><span className="progress-mark">{i < activeIndex ? "✓" : i + 1}</span><span>{statusName(step)}</span></div>)}</div>}
      {job.scheduled_start && <div className="arrival-info"><span>Scheduled arrival</span><strong>{new Date(job.scheduled_start).toLocaleString([], { weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit" })}</strong></div>}
      <p className="refresh-note">Updates automatically every 30 seconds{job.last_updated ? ` · Last update ${new Date(job.last_updated).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : ""}</p>
    </>}</section><footer className="tracking-footer">OpenDispatch · Secure customer updates</footer>
  </main>;
}
