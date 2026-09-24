import { useCallback, useEffect, useState } from "react";

function Gear() {
  const teeth = Array.from({ length: 8 }, (_, i) => (
    <rect key={i} x="21" y="2" width="6" height="9" rx="1" transform={`rotate(${i * 45} 24 24)`} />
  ));
  return (
    <svg className="gear" viewBox="0 0 48 48" aria-hidden="true">
      {teeth}
      <circle cx="24" cy="24" r="14" />
      <circle cx="24" cy="24" r="5.5" className="gear-hole" />
    </svg>
  );
}

async function check(path) {
  try {
    const r = await fetch(path);
    const body = await r.json().catch(() => ({}));
    return { ok: r.ok, body };
  } catch {
    return { ok: false, body: {} };
  }
}

export default function App() {
  const [api, setApi] = useState(null);
  const [db, setDb] = useState(null);
  const [checkedAt, setCheckedAt] = useState(null);

  const run = useCallback(async () => {
    setApi(null);
    setDb(null);
    const [a, d] = await Promise.all([check("/api/healthz"), check("/api/readyz")]);
    setApi(a);
    setDb(d);
    setCheckedAt(new Date());
  }, []);

  useEffect(() => {
    run();
  }, [run]);

  const rows = [
    {
      name: "Frontend",
      state: "up",
      detail: "You're looking at it.",
    },
    {
      name: "API",
      state: api === null ? "checking" : api.ok ? "up" : "down",
      detail: api?.ok ? `Running in ${api.body.env} mode.` : "Start it with docker compose up, then check the api logs.",
    },
    {
      name: "Database",
      state: db === null ? "checking" : db.ok ? "up" : "down",
      detail: db?.ok
        ? "Postgres answered."
        : "The API can't reach Postgres. Check DATABASE_URL in .env matches the POSTGRES_ values.",
    },
  ];

  return (
    <main className="sheet">
      <header>
        <Gear />
        <div>
          <h1>OpenDispatch</h1>
          <p className="sub">Local stack check</p>
        </div>
      </header>

      <ul className="rows">
        {rows.map((r) => (
          <li key={r.name} className={`row ${r.state}`}>
            <span className="name">{r.name}</span>
            <span className="state">{r.state === "up" ? "Up" : r.state === "down" ? "Down" : "Checking"}</span>
            {r.state !== "checking" && <span className="detail">{r.detail}</span>}
          </li>
        ))}
      </ul>

      <footer>
        <button onClick={run}>Check again</button>
        {checkedAt && <span className="stamp">Last checked {checkedAt.toLocaleTimeString()}</span>}
      </footer>
    </main>
  );
}
