// The public /waitlist page: the launch offer and the signup form, no login needed.
// Prices and the comparison table are the launch pricing decided in October 2026; the
// launch window itself comes from the API (LAUNCH_LABEL) so it can move without a deploy.
import { useEffect, useState } from "react";
import { post, request } from "../api.js";
import Gear from "../components/Gear.jsx";

const CONTACT = "milesjosephson18@gmail.com";

// The founding monthly price is set exactly $75 under ServiceM8 Premium, the closest
// comparable plan (same unlimited-user shape, similar depth). Checked 7 October 2026;
// these are the vendors' own published list prices and want re-checking before launch.
const RIVALS = [
  { name: "OpenDispatch", plan: "Founding hosted", price: 74, limit: "Nothing — unlimited users and jobs", us: true },
  { name: "ServiceM8", plan: "Premium", price: 149, limit: "500 jobs a month, then per-job fees" },
  { name: "Kickserv", plan: "Run", price: 119, limit: "Up to 10 users" },
  { name: "Kickserv", plan: "Scale", price: 199, limit: "Up to 20 users" },
  {
    name: "Service Fusion",
    plan: "Starter, month to month",
    price: 245,
    limit: "Photo uploads and job costing cost extra",
  },
  { name: "Service Fusion", plan: "Plus, month to month", price: 382, limit: "Voice, portal and eSign cost extra" },
];

const TIERS = [
  {
    kicker: "Self-hosted",
    price: "$0",
    per: "forever",
    note: "The open-source core, on your own box",
    points: [
      "Docker Compose and Postgres, nothing else to buy",
      "The full dispatch core, not a crippled demo",
      "Unlimited users and jobs",
      "You own the database and the backups",
    ],
  },
  {
    kicker: "Founding · hosted monthly",
    price: "$74",
    per: "billed monthly",
    note: "$119 at launch — 38% off, for life. Cancel any time.",
    feature: true,
    points: [
      "We run it: backups, updates, uptime",
      "Unlimited users, unlimited jobs",
      "Shared dispatch schedule and technician job links",
      "Customer tracking links and SMS budget alerts",
      "Your rate never rises while you stay subscribed",
    ],
  },
  {
    kicker: "Founding · annual",
    price: "$740",
    per: "one payment each year",
    note: "Pay once a year. Two months free — equivalent to $61.67/mo.",
    points: [
      "Everything in the monthly plan",
      "One $740 charge per year; saves $148 vs. paying monthly",
      "Price locked the same way",
    ],
  },
  {
    kicker: "Founding · buy it outright",
    price: "$1,490",
    per: "one time",
    note: "About 20 months of the monthly plan",
    points: [
      "A perpetual licence to the 1.x line, self-hosted",
      "Every 1.x update included, no renewal",
      "Priority on feature requests before launch",
      "A major new line (2.x) is a paid upgrade, never a forced one",
    ],
  },
];

const BUILT = [
  "Jobs, customers and team roles — owner, dispatcher, technician — with a lane on the schedule for each tech",
  "A shared dispatch schedule with technician lanes, plus private job links that open on a phone",
  "Signed technician job links that open the job on a phone with no login, and never show the quote",
  "Private 90-day tracking links so a customer can follow their own job",
  "Quotes, expenses and labour kept in whole cents, with budget alerts at 80% and 100% of the quote",
  "Photo and PDF attachments per job, up to 12 MiB, HEIC included",
  "Lockout after repeated bad passwords, single-use resets, and one click to sign a leaver out everywhere",
];

const PLANNED = [
  "Optional calendar export for the providers crews already use",
  "An online booking page so customers raise their own job requests",
  "Optional day and week planning help for techs — never required, never in the way",
  "Managed hosting, help migrating off your current tool, and the founding prices above",
];

const TRADES = [
  "Plumbing",
  "HVAC / refrigeration",
  "Electrical",
  "Landscaping / lawn",
  "Roofing",
  "Cleaning / janitorial",
  "Pest control",
  "Appliance repair",
  "General contracting",
  "Another trade",
];
const CREWS = ["Just me", "2 to 5", "6 to 10", "11 to 20", "More than 20"];
const PLANS = [
  ["hosted_monthly", "Hosted monthly — $74, billed each month"],
  ["annual", "Hosted annual — one $740 payment each year"],
  ["perpetual", "Buy it outright, $1,490 once"],
  ["self_hosted", "Free self-hosted"],
  ["undecided", "Still deciding"],
];

const EMPTY = {
  email: "",
  name: "",
  company: "",
  trade: "",
  crew_size: "",
  plan: "undecided",
  current_tool: "",
  region: "",
  website: "", // honeypot: hidden from people, so only bots fill it in
};

export default function WaitlistPage() {
  const [status, setStatus] = useState(null);
  const [closed, setClosed] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [joined, setJoined] = useState(null);
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) });

  useEffect(() => {
    request("/public/waitlist")
      .then(setStatus)
      .catch((e) => {
        if (e.status === 404) setClosed(true);
        else setError("We can't reach the waitlist right now. Please try again in a minute.");
      });
  }, []);

  async function submit(event) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, k === "plan" ? v : v.trim() || null]));
      setJoined(await post("/public/waitlist", null, body));
    } catch (e) {
      // 404: the waitlist closed while the page was open. 422 and 429 explain themselves.
      if (e.status === 404) setClosed(true);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const launch = status?.launch ?? "Winter 2027";
  const left = status?.spots_left;

  if (closed)
    return (
      <Frame launch={launch}>
        <section className="wl-card wl-closed">
          <p className="eyebrow">WAITLIST CLOSED</p>
          <h1>The waitlist isn't open on this server</h1>
          <p className="muted">
            This is a self-hosted copy of OpenDispatch, so it isn't collecting signups. Email <Contact /> if you want to
            hear about the launch.
          </p>
        </section>
      </Frame>
    );

  return (
    <Frame launch={launch}>
      <section className="wl-hero">
        <p className="eyebrow">FIELD SERVICE DISPATCH · OPEN SOURCE CORE</p>
        <h1>Stop paying per seat to send a tech down the street.</h1>
        <p className="wl-lede">
          OpenDispatch is job intake, dispatch and status tracking for small contractors. Jobs land on the calendar your
          crew already uses. <strong>Unlimited users. Unlimited jobs. No per-seat bill.</strong>
        </p>
        <ol className="wl-pipeline" aria-label="The job lifecycle">
          {["Requested", "Scheduled", "Dispatched", "En route", "In progress", "Completed", "Invoiced", "Paid"].map(
            (step) => (
              <li key={step}>{step}</li>
            ),
          )}
        </ol>
        <p className="wl-pipeline-note">
          The whole job lifecycle, enforced in one place. A reschedule steps back. Paid and cancelled are final.
        </p>
        <a className="primary wl-jump" href="#join">
          Claim a founding price
        </a>
      </section>

      <section className="wl-section">
        <header className="wl-section-head">
          <h2>The founding deal</h2>
          <span className="wl-stamp">
            {left == null
              ? `First ${status?.founding_spots ?? 100} on the waitlist`
              : left > 0
                ? `${left} of ${status.founding_spots} founding spots left`
                : "Founding spots full — general list open"}
          </span>
        </header>
        <div className="wl-banner">
          <p className="wl-banner-big">$74 billed monthly, or $740 in one payment each year.</p>
          <p>
            That is <strong>$75 a month less</strong> than the closest comparable plan on the market today, and $45
            under our own planned launch price. The annual option saves <strong>$148 per year</strong> compared with
            monthly billing. Unlimited users and unlimited jobs at every tier — how many people log in never changes
            your bill.
          </p>
        </div>
        <div className="wl-tiers">
          {TIERS.map((tier) => (
            <article key={tier.kicker} className={`wl-tier ${tier.feature ? "feature" : ""}`}>
              <p className="wl-kicker">{tier.kicker}</p>
              <p className="wl-price">
                {tier.price} <span>{tier.per}</span>
              </p>
              <p className="wl-tier-note">{tier.note}</p>
              <ul>
                {tier.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
        <p className="wl-fine">
          Choose the edition you are interested in; joining the waitlist does not start a subscription or collect a
          payment. Founding prices are held for people on the waitlist and charged only at launch in {launch}. The
          monthly plan bills each month; the annual plan is one payment per year. Cancel the monthly plan any time; the
          self-hosted core stays free whatever you choose.
        </p>
      </section>

      <section className="wl-section">
        <header className="wl-section-head">
          <h2>Against what you are paying now</h2>
        </header>
        <p className="muted wl-lede-narrow">
          Published list prices for the plan a small crew actually ends up on, checked 7 October 2026. Most of these
          meter you by job count or by head count. We do neither.
        </p>
        <div className="wl-table-scroll">
          <table className="wl-table">
            <caption>Monthly cost, comparable tier</caption>
            <thead>
              <tr>
                <th scope="col">Product</th>
                <th scope="col">Plan</th>
                <th scope="col">Per month</th>
                <th scope="col">What limits you</th>
                <th scope="col">You save</th>
              </tr>
            </thead>
            <tbody>
              {RIVALS.map((row) => (
                <tr key={`${row.name} ${row.plan}`} className={row.us ? "wl-us" : ""}>
                  <td>{row.name}</td>
                  <td>{row.plan}</td>
                  <td className="wl-num">${row.price}</td>
                  <td>{row.limit}</td>
                  <td className="wl-num">{row.us ? "—" : <span className="wl-delta">−${row.price - 74}/mo</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="wl-fine">
          These are the vendors' own published rates and can change. ServiceM8 Premium is the tightest real comparison —
          the same unlimited-user shape, similar feature depth — so the founding price is set exactly $75 under it.
        </p>
      </section>

      <section className="wl-section">
        <header className="wl-section-head">
          <h2>What already runs, and what lands by launch</h2>
        </header>
        <p className="muted wl-lede-narrow">
          This is not a pitch for software nobody has written yet. The dispatch core works today, and you can read every
          line of it.
        </p>
        <div className="wl-cols">
          <div>
            <p className="eyebrow">WORKING NOW</p>
            <ul className="wl-check">
              {BUILT.map((item) => (
                <li key={item}>
                  <span className="wl-tick" aria-hidden="true">
                    ✓
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="eyebrow">BY LAUNCH, {launch.toUpperCase()}</p>
            <ul className="wl-check">
              {PLANNED.map((item) => (
                <li key={item}>
                  <span className="wl-todo" aria-hidden="true">
                    ○
                  </span>
                  {item}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="wl-section" id="join">
        <div className="wl-card">
          {joined ? (
            <div className="wl-joined">
              <p className="eyebrow">YOU ARE ON THE LIST</p>
              <p className="wl-spot">#{joined.spot}</p>
              <h2>{joined.already_on_list ? "You were already on the list" : "Spot held"}</h2>
              <p className="wl-lede">
                {joined.is_founding
                  ? `Spot ${joined.spot} of ${status?.founding_spots ?? 100}. Your selected founding offer — $74 monthly, $740 billed once each year, or $1,490 to own it outright — is held for you until launch in ${launch}.`
                  : `The founding spots are taken, so you are on the general list. We will still write to you first when the beta opens.`}
              </p>
              <p className="wl-fine">
                Nothing has been charged. We will write once when the beta opens, and once more before {launch} pricing
                goes live. Questions in the meantime: <Contact />
              </p>
            </div>
          ) : (
            <form onSubmit={submit}>
              <p className="eyebrow">CLAIM A FOUNDING PRICE</p>
              <h2>Tell us the trade and the crew size</h2>
              <p className="muted wl-form-intro">
                No card, no sales call, no drip campaign — one email when the beta opens, and one before launch pricing
                goes live.
              </p>
              <div className="editor-grid">
                <label className="editor-field span-2">
                  Email
                  <input required type="email" maxLength={320} autoComplete="email" {...field("email")} />
                </label>
                <label className="editor-field">
                  Your name
                  <input maxLength={200} autoComplete="name" {...field("name")} />
                </label>
                <label className="editor-field">
                  Business
                  <input maxLength={200} autoComplete="organization" {...field("company")} />
                </label>
                <label className="editor-field">
                  Trade
                  <select {...field("trade")}>
                    <option value="">Choose one</option>
                    {TRADES.map((trade) => (
                      <option key={trade}>{trade}</option>
                    ))}
                  </select>
                </label>
                <label className="editor-field">
                  Crew size
                  <select {...field("crew_size")}>
                    <option value="">Choose one</option>
                    {CREWS.map((crew) => (
                      <option key={crew}>{crew}</option>
                    ))}
                  </select>
                </label>
                <label className="editor-field">
                  Which deal interests you
                  <select {...field("plan")}>
                    {PLANS.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="editor-field">
                  What you dispatch with today
                  <input maxLength={200} placeholder="Paper, texts, ServiceM8…" {...field("current_tool")} />
                </label>
                <label className="editor-field span-2">
                  City or region
                  <input maxLength={200} placeholder="Boise, ID" {...field("region")} />
                </label>
                {/* Honeypot. Off screen rather than display:none (some bots skip hidden fields),
                    out of the tab order, and hidden from screen readers so no person fills it in. */}
                <label className="honeypot" aria-hidden="true">
                  Website
                  <input tabIndex={-1} autoComplete="off" maxLength={500} {...field("website")} />
                </label>
              </div>
              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}
              <button className="primary wide wl-submit" disabled={busy}>
                {busy ? "Saving your spot…" : "Hold my spot"}
              </button>
              <p className="form-hint">
                We use your signup details to manage this waitlist and contact you about the beta and launch. We do not
                sell your information. To update or remove your signup, email <Contact />.
              </p>
            </form>
          )}
        </div>
      </section>
    </Frame>
  );
}

function Contact() {
  return <a href={`mailto:${CONTACT}`}>{CONTACT}</a>;
}

function Frame({ launch, children }) {
  return (
    <main className="wl-page">
      <header className="wl-brand">
        <Gear />
        <span>OpenDispatch</span>
        <span className="customer-label">Launching {launch}</span>
      </header>
      <div className="wl-body">{children}</div>
      <footer className="wl-footer">
        <a href="https://github.com/milesjo-cloud-project/opendispatch">Source on GitHub</a>
        <span>Open-source field service dispatch</span>
      </footer>
    </main>
  );
}
