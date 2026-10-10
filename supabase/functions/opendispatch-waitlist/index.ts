const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

const PLANS = new Set(["hosted_monthly", "annual", "perpetual", "self_hosted", "undecided"]);
const MAX_BODY_BYTES = 8_192;
const LIMIT_PER_HOUR = 3;

function json(body: unknown, status = 200, extraHeaders: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json", ...extraHeaders },
  });
}

function clean(value: unknown, field: string, maxLength: number): string | null {
  if (value == null) return null;
  if (typeof value !== "string") throw new Error(`${field} must be text`);
  const result = value.trim();
  if (result.length > maxLength) throw new Error(`${field} must be ${maxLength} characters or fewer`);
  return result || null;
}

function getSecretKey(): string {
  const keys = Deno.env.get("SUPABASE_SECRET_KEYS");
  if (keys) {
    const parsed = JSON.parse(keys) as Record<string, string>;
    if (parsed.default) return parsed.default;
  }
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (legacy) return legacy;
  throw new Error("Database service key is unavailable");
}

function databaseHeaders() {
  const key = getSecretKey();
  return {
    apikey: key,
    // Legacy Supabase service-role keys are JWTs; the current sb_secret keys are not.
    ...(key.startsWith("eyJ") ? { Authorization: `Bearer ${key}` } : {}),
  };
}

async function databaseRpc(name: string, args: Record<string, unknown>) {
  const url = Deno.env.get("SUPABASE_URL");
  if (!url) throw new Error("Database URL is unavailable");
  const response = await fetch(`${url}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: { ...databaseHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(args),
  });
  if (!response.ok) {
    console.error("Waitlist database call failed", name, response.status);
    throw new Error("The waitlist is temporarily unavailable. Please try again.");
  }
  return response.json();
}

async function rateLimitHash(ip: string): Promise<string> {
  const keyBytes = new TextEncoder().encode(getSecretKey());
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(ip));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (request.method !== "GET" && request.method !== "POST") return json({ detail: "Method not allowed" }, 405);

  try {
    if (request.method === "GET") {
      return json(await databaseRpc("opendispatch_waitlist_status", {}));
    }

    const contentLength = Number(request.headers.get("content-length") || 0);
    if (contentLength > MAX_BODY_BYTES) return json({ detail: "Signup is too large" }, 413);
    const body = await request.json();
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return json({ detail: "Please check the signup details and try again." }, 422);
    }

    const website = clean(body.website, "Website", 500);
    if (website) {
      return json({ spot: 101, is_founding: false, already_on_list: false, spots_left: 0 }, 201);
    }

    const email = clean(body.email, "Email", 320)?.toLowerCase();
    if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return json({ detail: "Please give an email address we can reach you at" }, 422);
    }
    const name = clean(body.name, "Name", 200);
    const company = clean(body.company, "Business", 200);
    const trade = clean(body.trade, "Trade", 100);
    const crew_size = clean(body.crew_size, "Crew size", 40);
    const plan = clean(body.plan, "Plan", 40) || "undecided";
    const current_tool = clean(body.current_tool, "Current tool", 200);
    const region = clean(body.region, "City or region", 200);
    if (!PLANS.has(plan)) return json({ detail: "Choose one of the listed editions." }, 422);

    const ip = request.headers.get("cf-connecting-ip")
      || request.headers.get("x-real-ip")
      || request.headers.get("x-forwarded-for")?.split(",")[0].trim()
      || "unknown";
    const allowed = await databaseRpc("opendispatch_waitlist_consume_rate_limit", {
      p_subject_hash: await rateLimitHash(ip),
      p_limit: LIMIT_PER_HOUR,
    });
    if (allowed !== true) {
      return json(
        { detail: "Too many signups from your network. Please try again later." },
        429,
        { "Retry-After": "3600" },
      );
    }

    const result = await databaseRpc("opendispatch_waitlist_join", {
      p_email: email,
      p_name: name,
      p_company: company,
      p_trade: trade,
      p_crew_size: crew_size,
      p_plan: plan,
      p_current_tool: current_tool,
      p_region: region,
    });
    return json(result, 201);
  } catch (error) {
    if (error instanceof SyntaxError) return json({ detail: "Please submit valid signup details." }, 422);
    if (error instanceof Error && /must be text|characters or fewer/.test(error.message)) {
      return json({ detail: error.message }, 422);
    }
    return json({ detail: "The waitlist is temporarily unavailable. Please try again." }, 503);
  }
});
