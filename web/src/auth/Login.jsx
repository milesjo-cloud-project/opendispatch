// Sign in, sign up and "forgot password" on one card.
import { useEffect, useState } from "react";
import { post, request } from "../api.js";
import Gear from "../components/Gear.jsx";

export default function Login({ onLogin, notice = "" }) {
  const [mode, setMode] = useState("login"); // login | signup | forgot
  const [form, setForm] = useState({ company_name: "", email: "", password: "", phone: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState(notice);
  // Only offer "Sign up" when this server takes new companies (the SIGNUP setting)
  const [signupOpen, setSignupOpen] = useState(false);
  useEffect(() => {
    request("/auth/signup")
      .then((status) => setSignupOpen(status.open))
      .catch(() => setSignupOpen(false));
  }, []);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });
  const switchTo = (next) => {
    setMode(next);
    setError("");
    setMessage("");
  };
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (mode === "forgot") {
        const result = await post("/auth/password-reset/request", null, { email: form.email });
        setMessage(result.detail);
        setMode("login");
      } else if (mode === "signup")
        onLogin(
          await post("/auth/signup", null, {
            company_name: form.company_name.trim(),
            email: form.email.trim(),
            password: form.password,
            phone: form.phone.trim() || null,
          }),
        );
      else onLogin(await post("/auth/login", null, { email: form.email, password: form.password }));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const heading = { login: "Welcome back", signup: "Start your company", forgot: "Reset your password" }[mode];
  const action = {
    login: ["Sign in", "Signing in…"],
    signup: ["Create account", "Creating…"],
    forgot: ["Send reset link", "Sending…"],
  }[mode];
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
        <h2>{heading}</h2>
        {mode === "forgot" && (
          <p className="muted">Enter your email and we'll send you a link to choose a new password.</p>
        )}
        {mode === "signup" && (
          <p className="muted">You'll be the owner. Add your dispatchers and technicians after you're in.</p>
        )}
        {mode === "signup" && (
          <label>
            Company name
            <input required maxLength={200} autoComplete="organization" {...field("company_name")} />
          </label>
        )}
        <label>
          Email
          <input type="email" autoComplete="username" required {...field("email")} />
        </label>
        {mode !== "forgot" && (
          <label>
            Password
            <input
              type="password"
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              required
              minLength={mode === "signup" ? 12 : undefined}
              {...field("password")}
            />
          </label>
        )}
        {mode === "signup" && (
          <label>
            Mobile phone (optional, for budget alerts)
            <input type="tel" maxLength={32} autoComplete="tel" {...field("phone")} />
          </label>
        )}
        {message && (
          <p className="success" role="status">
            {message}
          </p>
        )}
        {error && <p className="error">{error}</p>}
        <button className="primary wide" disabled={busy}>
          {busy ? action[1] : action[0]}
        </button>
        <div className="login-links">
          {mode === "login" ? (
            <>
              <button type="button" className="link-button" onClick={() => switchTo("forgot")}>
                Forgot password?
              </button>
              {signupOpen && (
                <button type="button" className="link-button" onClick={() => switchTo("signup")}>
                  New company? Sign up
                </button>
              )}
            </>
          ) : (
            <button type="button" className="link-button" onClick={() => switchTo("login")}>
              Back to sign in
            </button>
          )}
        </div>
      </form>
    </main>
  );
}
