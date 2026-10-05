// People in the company: adding them, technician profiles, deactivating and disabling sign-in.
import { useCallback, useEffect, useMemo, useState } from "react";
import { centsToDollars, dollarsToCents, post, request } from "../api.js";
import { initials } from "../format.js";

const roleName = (role) => ({ owner: "Owner", dispatcher: "Dispatcher", technician: "Technician" })[role] || role;

export default function TeamPage({ token, isOwner, meId, technicians, onChanged }) {
  const [users, setUsers] = useState([]);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({
    email: "",
    role: "technician",
    password: "",
    phone: "",
    display_name: "",
    rate: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const loadUsers = useCallback(
    () =>
      request("/users", token)
        .then(setUsers)
        .catch((e) => setError(e.message)),
    [token],
  );
  useEffect(() => {
    loadUsers();
  }, [loadUsers]);
  const techByUser = useMemo(() => Object.fromEntries(technicians.map((t) => [t.user_id, t])), [technicians]);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  async function makeTechnician(user, displayName, rateText) {
    const rate = dollarsToCents(rateText);
    if (Number.isNaN(rate)) throw new Error("Enter the hourly rate as dollars, like 45 or 45.50.");
    await post("/technicians", token, {
      user_id: user.id,
      display_name: displayName.trim(),
      phone: user.phone,
      hourly_rate_cents: rate,
    });
  }

  async function submit(event) {
    event.preventDefault();
    setError("");
    setMessage("");
    if (form.role === "technician" && Number.isNaN(dollarsToCents(form.rate))) {
      setError("Enter the hourly rate as dollars, like 45 or 45.50.");
      return;
    }
    setBusy(true);
    try {
      // The technician profile comes in the same request, so a problem with it doesn't leave a half-added person behind
      const technician =
        form.role === "technician"
          ? {
              display_name: form.display_name.trim() || form.email.split("@")[0],
              hourly_rate_cents: dollarsToCents(form.rate),
            }
          : null;
      const user = await post("/users", token, {
        email: form.email.trim(),
        role: form.role,
        password: form.password,
        phone: form.phone.trim() || null,
        technician,
      });
      setMessage(`Added ${user.email}. Give them their starting password; they can change it after signing in.`);
      setForm({ email: "", role: "technician", password: "", phone: "", display_name: "", rate: "" });
      setAdding(false);
      await Promise.all([loadUsers(), onChanged()]);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function setUpTechnician(user) {
    const name = window.prompt(`Name to show on the schedule for ${user.email}:`, user.email.split("@")[0]);
    if (!name) return;
    setError("");
    try {
      await makeTechnician(user, name, "");
      await onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  async function setActive(tech, active) {
    setError("");
    try {
      await request(`/technicians/${tech.id}`, token, { method: "PATCH", body: JSON.stringify({ active }) });
      await onChanged();
    } catch (e) {
      setError(e.message);
    }
  }

  // Disabling is about sign-in; deactivating a technician only takes them off the schedule.
  async function setAccess(user, enable) {
    if (
      !enable &&
      !window.confirm(
        `Disable ${user.email}? They're signed out on every device and can't sign in until you enable them again. Their jobs and history stay.`,
      )
    )
      return;
    setError("");
    setMessage("");
    try {
      await post(`/users/${user.id}/${enable ? "enable" : "disable"}`, token);
      await Promise.all([loadUsers(), onChanged()]);
      if (enable && techByUser[user.id])
        setMessage(`${user.email} can sign in again. Use Reactivate to put them back on the schedule.`);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <section className="page-panel">
      <div className="panel-toolbar">
        <p className="muted">
          {isOwner
            ? "Add the people who dispatch and do the work. Technicians get their own schedule."
            : "Only the owner can add people or change pay."}
        </p>
        {isOwner && (
          <button className="primary" onClick={() => setAdding(!adding)}>
            {adding ? "Close" : "＋ Add person"}
          </button>
        )}
      </div>
      {message && (
        <p className="success page-message" role="status">
          {message}
        </p>
      )}
      {adding && (
        <form className="inline-form" onSubmit={submit}>
          <div className="editor-grid">
            <label className="editor-field">
              Email
              <input type="email" required maxLength={320} autoComplete="off" {...field("email")} />
            </label>
            <label className="editor-field">
              Role
              <select {...field("role")}>
                <option value="technician">Technician</option>
                <option value="dispatcher">Dispatcher</option>
                <option value="owner">Owner</option>
              </select>
            </label>
            <label className="editor-field">
              Starting password
              <input
                type="text"
                required
                minLength={12}
                maxLength={1024}
                autoComplete="off"
                placeholder="At least 12 characters"
                {...field("password")}
              />
            </label>
            <label className="editor-field">
              Mobile phone
              <input type="tel" maxLength={32} {...field("phone")} />
            </label>
            {form.role === "technician" && (
              <>
                <label className="editor-field">
                  Name on the schedule
                  <input maxLength={200} placeholder="e.g. Sam R." {...field("display_name")} />
                </label>
                <label className="editor-field">
                  Hourly rate (optional)
                  <input inputMode="decimal" placeholder="$0.00" {...field("rate")} />
                </label>
              </>
            )}
          </div>
          <div className="form-actions">
            <button className="primary" disabled={busy}>
              {busy ? "Adding…" : "Add person"}
            </button>
          </div>
        </form>
      )}
      {error && <p className="error page-message">{error}</p>}
      <ul className="data-list">
        {users.map((u) => {
          const tech = techByUser[u.id];
          return (
            <li key={u.id} className={u.disabled_at || (tech && !tech.active) ? "inactive" : ""}>
              <span className="avatar">{initials(tech?.display_name || u.email)}</span>
              <span className="data-main">
                <strong>{tech?.display_name || u.email}</strong>
                <small>
                  {tech ? u.email : ""}
                  {u.phone ? `${tech ? " · " : ""}${u.phone}` : ""}
                </small>
              </span>
              <span className="data-side">
                <span className="role-pill">{roleName(u.role)}</span>
                {tech && tech.hourly_rate_cents != null && <small>{centsToDollars(tech.hourly_rate_cents)}/h</small>}
                {u.disabled_at ? <small>Can't sign in</small> : tech && !tech.active && <small>Inactive</small>}
              </span>
              {isOwner && (
                <span className="data-actions">
                  {u.role === "technician" && !tech && !u.disabled_at && (
                    <button className="quiet small" onClick={() => setUpTechnician(u)}>
                      Add to schedule
                    </button>
                  )}
                  {tech && !u.disabled_at && (
                    <button className="quiet small" onClick={() => setActive(tech, !tech.active)}>
                      {tech.active ? "Deactivate" : "Reactivate"}
                    </button>
                  )}
                  {u.id !== meId && (
                    <button
                      className={`quiet small ${u.disabled_at ? "" : "danger"}`}
                      onClick={() => setAccess(u, Boolean(u.disabled_at))}
                    >
                      {u.disabled_at ? "Enable sign-in" : "Disable"}
                    </button>
                  )}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
