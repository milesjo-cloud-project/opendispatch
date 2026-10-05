// The /reset-password page the emailed link opens.
import { useState } from "react";
import { post } from "../api.js";
import Gear from "../components/Gear.jsx";

export default function ResetPassword({ token, onDone }) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setError("");
    if (password !== confirm) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await post("/auth/password-reset/confirm", null, { token, new_password: password });
      onDone("Your password was changed. Sign in with the new one.");
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">
          <Gear />
          <div>
            <h1>OpenDispatch</h1>
            <p>Field service, in sync.</p>
          </div>
        </div>
        <h2>Choose a new password</h2>
        {!token ? (
          <p className="error">This reset link is incomplete. Request a new one from the sign-in page.</p>
        ) : (
          <>
            <label>
              New password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              Confirm new password
              <input
                type="password"
                autoComplete="new-password"
                minLength={12}
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>
            <p className="muted">At least 12 characters. You'll be signed out on every device.</p>
            {error && <p className="error">{error}</p>}
            <button className="primary wide" disabled={busy}>
              {busy ? "Saving…" : "Set new password"}
            </button>
          </>
        )}
        <button type="button" className="link-button" onClick={() => onDone("")}>
          Back to sign in
        </button>
      </form>
    </main>
  );
}
