// Your own account: change your password, and sign out your other devices.
import { useState } from "react";
import { post, request } from "../api.js";

const EMPTY = { current: "", next: "", confirm: "" };
const NO_RESULT = { error: "", message: "" };

export default function AccountPage({ token }) {
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(""); // "password" | "devices" | ""
  const [passwordResult, setPasswordResult] = useState(NO_RESULT);
  const [devicesResult, setDevicesResult] = useState(NO_RESULT);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  async function changePassword(event) {
    event.preventDefault();
    if (form.next !== form.confirm) {
      setPasswordResult({ error: "The new passwords don't match.", message: "" });
      return;
    }
    setBusy("password");
    setPasswordResult(NO_RESULT);
    try {
      await post("/me/password", token, { current_password: form.current, new_password: form.next });
      setForm(EMPTY);
      setPasswordResult({
        error: "",
        message: "Password changed. Any other devices signed in to your account were signed out.",
      });
    } catch (e) {
      setPasswordResult({ error: e.message, message: "" });
    } finally {
      setBusy("");
    }
  }

  async function signOutOthers() {
    if (!window.confirm("Sign out every other device signed in to your account? This one stays signed in.")) return;
    setBusy("devices");
    setDevicesResult(NO_RESULT);
    try {
      const { signed_out: count } = await request("/auth/logout-others", token, { method: "POST" });
      setDevicesResult({
        error: "",
        message: count
          ? `Signed out ${count} other device${count === 1 ? "" : "s"}.`
          : "No other devices were signed in.",
      });
    } catch (e) {
      setDevicesResult({ error: e.message, message: "" });
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="page-panel account-page">
      <form className="inline-form" onSubmit={changePassword}>
        <h3>Change password</h3>
        <p className="muted">At least 12 characters. Your other devices are signed out when it changes.</p>
        <div className="editor-grid">
          <label className="editor-field">
            Current password
            <input type="password" autoComplete="current-password" required {...field("current")} />
          </label>
          <label className="editor-field">
            New password
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={128}
              {...field("next")}
            />
          </label>
          <label className="editor-field">
            Confirm new password
            <input type="password" autoComplete="new-password" required {...field("confirm")} />
          </label>
        </div>
        {passwordResult.error && <p className="error">{passwordResult.error}</p>}
        {passwordResult.message && (
          <p className="success" role="status">
            {passwordResult.message}
          </p>
        )}
        <div className="form-actions">
          <button className="primary" disabled={busy !== ""}>
            {busy === "password" ? "Changing…" : "Change password"}
          </button>
        </div>
      </form>
      <div className="inline-form">
        <h3>Signed-in devices</h3>
        <p className="muted">
          Lost a phone, or signed in on a shared computer? Sign out everywhere else. This device stays signed in.
        </p>
        {devicesResult.error && <p className="error">{devicesResult.error}</p>}
        {devicesResult.message && (
          <p className="success" role="status">
            {devicesResult.message}
          </p>
        )}
        <div className="form-actions">
          <button className="quiet" onClick={signOutOthers} disabled={busy !== ""}>
            {busy === "devices" ? "Signing out…" : "Sign out other devices"}
          </button>
        </div>
      </div>
    </section>
  );
}
