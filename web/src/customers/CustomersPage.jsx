// The customer list, search and "Add customer".
import { useMemo, useState } from "react";
import { post } from "../api.js";
import { initials } from "../format.js";

export default function CustomersPage({ token, customers, onChanged }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", email: "", address: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q
      ? customers.filter((c) => [c.name, c.phone, c.email, c.address].some((v) => v?.toLowerCase().includes(q)))
      : customers;
  }, [customers, query]);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/customers", token, Object.fromEntries(Object.entries(form).map(([k, v]) => [k, v.trim() || null])));
      setForm({ name: "", phone: "", email: "", address: "" });
      setAdding(false);
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="page-panel">
      <div className="panel-toolbar">
        <input
          type="search"
          className="search"
          placeholder="Search name, phone, email or address"
          aria-label="Search customers"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="primary" onClick={() => setAdding(!adding)}>
          {adding ? "Close" : "＋ Add customer"}
        </button>
      </div>
      {adding && (
        <form className="inline-form" onSubmit={submit}>
          <div className="editor-grid">
            <label className="editor-field">
              Name
              <input required maxLength={200} {...field("name")} />
            </label>
            <label className="editor-field">
              Phone
              <input type="tel" maxLength={40} {...field("phone")} />
            </label>
            <label className="editor-field">
              Email
              <input type="email" maxLength={320} {...field("email")} />
            </label>
            <label className="editor-field">
              Address
              <input maxLength={2000} {...field("address")} />
            </label>
          </div>
          {error && <p className="error">{error}</p>}
          <div className="form-actions">
            <button className="primary" disabled={busy}>
              {busy ? "Saving…" : "Save customer"}
            </button>
          </div>
        </form>
      )}
      {shown.length ? (
        <ul className="data-list">
          {shown.map((c) => (
            <li key={c.id}>
              <span className="avatar">{initials(c.name)}</span>
              <span className="data-main">
                <strong>{c.name}</strong>
                <small>{c.address || "No address"}</small>
              </span>
              <span className="data-side">
                {c.phone && <a href={`tel:${c.phone}`}>{c.phone}</a>}
                {c.email && <a href={`mailto:${c.email}`}>{c.email}</a>}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-state">
          {customers.length
            ? "No customers match that search."
            : "No customers yet. Add your first one, or create it while making a job."}
        </div>
      )}
    </section>
  );
}
