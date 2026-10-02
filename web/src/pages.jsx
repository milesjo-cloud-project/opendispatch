import { useCallback, useEffect, useMemo, useState } from "react";
import { centsToDollars, dollarsToCents, post, request } from "./api.js";

const roleName = (role) => ({ owner: "Owner", dispatcher: "Dispatcher", technician: "Technician" }[role] || role);

export function NewJobDialog({ token, customers, technicians, onClose, onCreated }) {
  const [customerId, setCustomerId] = useState(customers.length ? "" : "new");
  const [customer, setCustomer] = useState({ name: "", phone: "", address: "" });
  const [job, setJob] = useState({ title: "", description: "", technician_id: "", start: "", quote: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const field = (key) => ({ value: job[key], onChange: (e) => setJob({ ...job, [key]: e.target.value }) });
  const customerField = (key) => ({ value: customer[key], onChange: (e) => setCustomer({ ...customer, [key]: e.target.value }) });

  async function submit(event) {
    event.preventDefault(); setError("");
    const quote = dollarsToCents(job.quote);
    if (Number.isNaN(quote)) { setError("Enter the quote as dollars, like 1250 or 1250.50."); return; }
    setBusy(true);
    try {
      let id = customerId;
      if (customerId === "new") id = (await post("/customers", token, { name: customer.name.trim(), phone: customer.phone.trim() || null, address: customer.address.trim() || null })).id;
      let created = await post("/jobs", token, { customer_id: id, title: job.title.trim(), description: job.description.trim() || null, technician_id: job.technician_id || null, scheduled_start: job.start ? new Date(job.start).toISOString() : null, quoted_amount_cents: quote });
      // A job with a time goes straight onto the schedule; without one it stays a draft in Open shifts.
      if (job.start) created = await post(`/jobs/${created.id}/status`, token, { status: "scheduled" });
      onCreated(created);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return <div className="overlay" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}><form className="editor" role="dialog" aria-modal="true" aria-labelledby="new-job-title" onSubmit={submit}>
    <div className="editor-head"><div><span className="status-pill requested">New</span><h2 id="new-job-title">New job</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Close">×</button></div>
    <div className="editor-body"><div className="editor-grid">
      <label className="editor-field span-2">What's the job?<input required maxLength={200} placeholder="e.g. Replace water heater" {...field("title")} /></label>
      <label className="editor-field">Customer<select required value={customerId} onChange={(e) => setCustomerId(e.target.value)}><option value="" disabled>Choose a customer</option>{customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}<option value="new">＋ New customer</option></select></label>
      <label className="editor-field">Technician<select {...field("technician_id")}><option value="">Unassigned for now</option>{technicians.filter((t) => t.active).map((t) => <option key={t.id} value={t.id}>{t.display_name}</option>)}</select></label>
      {customerId === "new" && <><label className="editor-field">Customer name<input required maxLength={200} {...customerField("name")} /></label><label className="editor-field">Customer phone<input type="tel" maxLength={40} {...customerField("phone")} /></label><label className="editor-field span-2">Address<input maxLength={2000} {...customerField("address")} /></label></>}
      <label className="editor-field">Date and start time<input type="datetime-local" {...field("start")} /></label>
      <label className="editor-field">Quote (optional)<input inputMode="decimal" placeholder="$0.00" {...field("quote")} /></label>
      <label className="editor-field span-2">Job details<textarea rows={3} maxLength={10000} placeholder="Access notes, parts, what the customer said…" {...field("description")} /></label>
    </div><p className="muted form-hint">{job.start ? "This job goes on the schedule right away." : "Without a time, the job waits in Open shifts as a draft."}</p>{error && <p className="error">{error}</p>}</div>
    <div className="editor-actions"><button type="button" className="quiet" onClick={onClose} disabled={busy}>Cancel</button><span className="actions-spacer" /><button className="primary" disabled={busy}>{busy ? "Creating…" : "Create job"}</button></div>
  </form></div>;
}

export function CustomersPage({ token, customers, onChanged }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const shown = useMemo(() => { const q = query.trim().toLowerCase(); return q ? customers.filter((c) => [c.name, c.phone, c.email, c.address].some((v) => v?.toLowerCase().includes(q))) : customers; }, [customers, query]);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      await post("/customers", token, Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null])));
      setForm({ name: "", phone: "", email: "", address: "" }); setAdding(false); await onChanged();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  return <section className="page-panel">
    <div className="panel-toolbar"><input type="search" className="search" placeholder="Search name, phone, email or address" aria-label="Search customers" value={query} onChange={(e) => setQuery(e.target.value)} /><button className="primary" onClick={() => setAdding(!adding)}>{adding ? "Close" : "＋ Add customer"}</button></div>
    {adding && <form className="inline-form" onSubmit={submit}><div className="editor-grid">
      <label className="editor-field">Name<input required maxLength={200} {...field("name")} /></label>
      <label className="editor-field">Phone<input type="tel" maxLength={40} {...field("phone")} /></label>
      <label className="editor-field">Email<input type="email" maxLength={320} {...field("email")} /></label>
      <label className="editor-field">Address<input maxLength={2000} {...field("address")} /></label>
    </div>{error && <p className="error">{error}</p>}<div className="form-actions"><button className="primary" disabled={busy}>{busy ? "Saving…" : "Save customer"}</button></div></form>}
    {shown.length ? <ul className="data-list">{shown.map((c) => <li key={c.id}><span className="avatar">{initials(c.name)}</span><span className="data-main"><strong>{c.name}</strong><small>{c.address || "No address"}</small></span><span className="data-side">{c.phone && <a href={`tel:${c.phone}`}>{c.phone}</a>}{c.email && <a href={`mailto:${c.email}`}>{c.email}</a>}</span></li>)}</ul>
      : <div className="empty-state">{customers.length ? "No customers match that search." : "No customers yet. Add your first one, or create it while making a job."}</div>}
  </section>;
}

export function TeamPage({ token, isOwner, meId, technicians, onChanged }) {
  const [users, setUsers] = useState([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ email: "", role: "technician", password: "", phone: "", display_name: "", rate: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const loadUsers = useCallback(() => request("/users", token).then(setUsers).catch((e) => setError(e.message)), [token]);
  useEffect(() => { loadUsers(); }, [loadUsers]);
  const techByUser = useMemo(() => Object.fromEntries(technicians.map((t) => [t.user_id, t])), [technicians]);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  async function makeTechnician(user, displayName, rateText) {
    const rate = dollarsToCents(rateText);
    if (Number.isNaN(rate)) throw new Error("Enter the hourly rate as dollars, like 45 or 45.50.");
    await post("/technicians", token, { user_id: user.id, display_name: displayName.trim(), phone: user.phone, hourly_rate_cents: rate });
  }

  async function submit(event) {
    event.preventDefault(); setError(""); setMessage("");
    if (form.role === "technician" && Number.isNaN(dollarsToCents(form.rate))) { setError("Enter the hourly rate as dollars, like 45 or 45.50."); return; }
    setBusy(true);
    try {
      const user = await post("/users", token, { email: form.email.trim(), role: form.role, password: form.password, phone: form.phone.trim() || null });
      try { if (form.role === "technician") await makeTechnician(user, form.display_name || form.email.split("@")[0], form.rate); }
      catch (e) { setError(`${user.email} was added, but their technician profile wasn't: ${e.message}`); }
      setMessage(`Added ${user.email}. Give them their starting password; they can change it after signing in.`);
      setForm({ email: "", role: "technician", password: "", phone: "", display_name: "", rate: "" }); setAdding(false);
      await Promise.all([loadUsers(), onChanged()]);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }

  async function setUpTechnician(user) {
    const name = window.prompt(`Name to show on the schedule for ${user.email}:`, user.email.split("@")[0]);
    if (!name) return;
    setError("");
    try { await makeTechnician(user, name, ""); await onChanged(); } catch (e) { setError(e.message); }
  }

  async function setActive(tech, active) {
    setError("");
    try { await request(`/technicians/${tech.id}`, token, { method: "PATCH", body: JSON.stringify({ active }) }); await onChanged(); } catch (e) { setError(e.message); }
  }

  // Disabling is about sign-in; deactivating a technician only takes them off the schedule.
  async function setAccess(user, enable) {
    if (!enable && !window.confirm(`Disable ${user.email}? They're signed out on every device and can't sign in until you enable them again. Their jobs and history stay.`)) return;
    setError(""); setMessage("");
    try {
      await post(`/users/${user.id}/${enable ? "enable" : "disable"}`, token);
      await Promise.all([loadUsers(), onChanged()]);
      if (enable && techByUser[user.id]) setMessage(`${user.email} can sign in again. Use Reactivate to put them back on the schedule.`);
    } catch (e) { setError(e.message); }
  }

  return <section className="page-panel">
    <div className="panel-toolbar"><p className="muted">{isOwner ? "Add the people who dispatch and do the work. Technicians get their own schedule." : "Only the owner can add people or change pay."}</p>{isOwner && <button className="primary" onClick={() => setAdding(!adding)}>{adding ? "Close" : "＋ Add person"}</button>}</div>
    {message && <p className="success page-message" role="status">{message}</p>}
    {adding && <form className="inline-form" onSubmit={submit}><div className="editor-grid">
      <label className="editor-field">Email<input type="email" required maxLength={320} autoComplete="off" {...field("email")} /></label>
      <label className="editor-field">Role<select {...field("role")}><option value="technician">Technician</option><option value="dispatcher">Dispatcher</option><option value="owner">Owner</option></select></label>
      <label className="editor-field">Starting password<input type="text" required minLength={12} maxLength={1024} autoComplete="off" placeholder="At least 12 characters" {...field("password")} /></label>
      <label className="editor-field">Mobile phone<input type="tel" maxLength={32} {...field("phone")} /></label>
      {form.role === "technician" && <><label className="editor-field">Name on the schedule<input maxLength={200} placeholder="e.g. Sam R." {...field("display_name")} /></label><label className="editor-field">Hourly rate (optional)<input inputMode="decimal" placeholder="$0.00" {...field("rate")} /></label></>}
    </div><div className="form-actions"><button className="primary" disabled={busy}>{busy ? "Adding…" : "Add person"}</button></div></form>}
    {error && <p className="error page-message">{error}</p>}
    <ul className="data-list">{users.map((u) => { const tech = techByUser[u.id]; return <li key={u.id} className={u.disabled_at || (tech && !tech.active) ? "inactive" : ""}>
      <span className="avatar">{initials(tech?.display_name || u.email)}</span>
      <span className="data-main"><strong>{tech?.display_name || u.email}</strong><small>{tech ? u.email : ""}{u.phone ? `${tech ? " · " : ""}${u.phone}` : ""}</small></span>
      <span className="data-side"><span className="role-pill">{roleName(u.role)}</span>{tech && tech.hourly_rate_cents != null && <small>{centsToDollars(tech.hourly_rate_cents)}/h</small>}{u.disabled_at ? <small>Can't sign in</small> : tech && !tech.active && <small>Inactive</small>}</span>
      {isOwner && <span className="data-actions">
        {u.role === "technician" && !tech && !u.disabled_at && <button className="quiet small" onClick={() => setUpTechnician(u)}>Add to schedule</button>}
        {tech && !u.disabled_at && <button className="quiet small" onClick={() => setActive(tech, !tech.active)}>{tech.active ? "Deactivate" : "Reactivate"}</button>}
        {u.id !== meId && <button className={`quiet small ${u.disabled_at ? "" : "danger"}`} onClick={() => setAccess(u, Boolean(u.disabled_at))}>{u.disabled_at ? "Enable sign-in" : "Disable"}</button>}
      </span>}
    </li>; })}</ul>
  </section>;
}

export const initials = (name) => name.split(/[\s@._-]+/).filter(Boolean).map((part) => part[0]).join("").slice(0, 2).toUpperCase();
