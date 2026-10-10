// Talking to the API, the saved login, and the job status rules the screens need.

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function request(path, token, options = {}) {
  const isForm = typeof FormData !== "undefined" && options.body instanceof FormData;
  return requestUrl(`/api${path}`, token, options, isForm);
}

async function requestUrl(url, token, options = {}, isForm = false) {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...(options.body && !isForm ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (response.status === 204) return null;
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new ApiError(
      (Array.isArray(data.detail) ? data.detail[0]?.msg : data.detail) || `Request failed (${response.status})`,
      response.status,
    );
  return data;
}

export const post = (path, token, body) => request(path, token, { method: "POST", body: JSON.stringify(body) });

// The hosted launch page can point only its public waitlist calls at the launch API.
// Self-hosted installations keep using their local FastAPI endpoint.
export function publicWaitlistRequest(method = "GET", body) {
  const endpoint = import.meta.env.VITE_WAITLIST_ENDPOINT;
  const options = {
    method,
    ...(body ? { body: JSON.stringify(body) } : {}),
  };
  if (!endpoint) return request("/public/waitlist", null, options);
  return requestUrl(endpoint, null, options);
}

// Field workers shouldn't have to sign in again every time the phone reloads the page.
// The token lasts 14 days on the server and is checked with /me on every load.
const TOKEN_KEY = "opendispatch.token";
export function savedToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}
export function saveToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: stay signed in for this tab only */
  }
}

export const statusName = (value) =>
  ({
    requested: "Draft",
    scheduled: "Scheduled",
    dispatched: "Dispatched",
    en_route: "En route",
    in_progress: "In progress",
    completed: "Completed",
    invoiced: "Invoiced",
    paid: "Paid",
    cancelled: "Cancelled",
  })[value] || value;

// Mirrors ALLOWED in api/app/shared/job_status.py; the API still has the final say.
const NEXT = {
  requested: ["scheduled"],
  scheduled: ["dispatched"],
  dispatched: ["en_route", "scheduled"],
  en_route: ["in_progress"],
  in_progress: ["completed"],
  completed: ["invoiced"],
  invoiced: ["paid"],
};
// Mirrors TECH_STATUS_MOVES in api/app/shared/access.py
const TECH_MOVES = ["en_route", "in_progress", "completed"];
const CANCELLABLE = ["requested", "scheduled", "dispatched", "en_route", "in_progress"];
const ACTION_LABEL = {
  scheduled: "Put on schedule",
  dispatched: "Dispatch to tech",
  en_route: "On my way",
  in_progress: "Start work",
  completed: "Mark complete",
  invoiced: "Mark invoiced",
  paid: "Mark paid",
};

export function statusActions(status, isTechnician) {
  const moves = (NEXT[status] || []).filter((to) => !isTechnician || TECH_MOVES.includes(to));
  return moves.map((to) => ({
    to,
    label: status === "dispatched" && to === "scheduled" ? "Pull back to scheduled" : ACTION_LABEL[to],
  }));
}
export const canCancel = (status, isTechnician) => !isTechnician && CANCELLABLE.includes(status);

// Mirrors REASSIGNABLE, UNASSIGNABLE and RESCHEDULABLE in api/app/shared/models.py
export const canReassign = (status) =>
  ["requested", "scheduled", "dispatched", "en_route", "in_progress"].includes(status);
export const canUnassign = (status) => ["requested", "scheduled"].includes(status);
export const canReschedule = (status) => ["requested", "scheduled", "dispatched"].includes(status);

// "1,250.50" -> 125050. Returns null for blank, NaN for nonsense.
export function dollarsToCents(text) {
  const clean = String(text ?? "").replace(/[$,\s]/g, "");
  if (!clean) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(clean)) return NaN;
  return Math.round(Number(clean) * 100);
}
export const centsToDollars = (cents) =>
  cents == null ? "" : (cents / 100).toLocaleString([], { style: "currency", currency: "USD" });
