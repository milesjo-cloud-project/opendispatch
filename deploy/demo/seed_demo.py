"""Set up a ready-to-demo company through the API: logins, techs, customers, a job on the
board, online booking turned on, and requests waiting in the inbox.

    python deploy/demo/seed_demo.py                     # API at http://127.0.0.1:8080
    python deploy/demo/seed_demo.py --api http://127.0.0.1:8090 --tag rehearsal2

Each run makes a NEW company with its own logins (the --tag goes in every email), so it
never touches existing data and can be run again before every rehearsal. Standard library
only. Online booking counts per IP address, so set BOOKING_LIMIT_PER_HOUR=50 in .env for
rehearsals: each run sends 3 bookings, and the demo sends one more.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

PASSWORD = "demo-password-2026"
COMPANY = "Riverside Plumbing"


class Api:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, token: str | None = None, body: dict | None = None, ok=(200, 201, 204)):
        req = urllib.request.Request(
            self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        except urllib.error.URLError as e:
            sys.exit(f"Can't reach the API at {self.base} ({e.reason}). Is it running?")
        if status not in ok:
            sys.exit(f"{method} {path} failed: {status} {raw.decode(errors='replace')[:300]}")
        return json.loads(raw) if raw else None


def tomorrow_at(hour: int) -> str:
    local = datetime.now().astimezone()
    day = (local + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return day.astimezone(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8080", help="the API's address (not the web app's)")
    parser.add_argument("--tag", default=datetime.now().strftime("%m%d-%H%M"),
                        help="goes in every email so each run is a fresh company (default: date and time)")
    args = parser.parse_args()
    api, tag = Api(args.api), args.tag
    email = lambda who: f"{who}-{tag}@riverside.example"  # noqa: E731  (.example never delivers mail)

    owner = api.call("POST", "/auth/signup", body={"company_name": COMPANY, "email": email("owner"),
                                                   "password": PASSWORD})["token"]
    api.call("POST", "/users", owner, {"email": email("dispatch"), "role": "dispatcher", "password": PASSWORD})
    techs = {}
    for name, who, rate in [("Sam R.", "sam", 4_500), ("Alex P.", "alex", 5_000)]:
        user = api.call("POST", "/users", owner, {"email": email(who), "role": "technician", "password": PASSWORD,
                                                  "technician": {"display_name": name, "hourly_rate_cents": rate}})
        techs[name] = next(t["id"] for t in api.call("GET", "/technicians", owner) if t["user_id"] == user["id"])

    customers = {}
    for c in [{"name": "Dana Lee", "phone": "(555) 010-2222", "email": "dana.lee@example.com",
               "address": "48 Birch Ln"},
              {"name": "Mike Chen", "phone": "(555) 010-3333", "address": "7 Oak St"}]:
        customers[c["name"]] = api.call("POST", "/customers", owner, c)["id"]

    # Something already on the board, so the schedule isn't empty
    job = api.call("POST", "/jobs", owner, {
        "customer_id": customers["Mike Chen"], "title": "Replace kitchen faucet", "technician_id": techs["Alex P."],
        "scheduled_start": tomorrow_at(13), "quoted_amount_cents": 32_000, "schedule": True})
    api.call("POST", f"/jobs/{job['id']}/status", owner, {"status": "dispatched"})

    booking_id = api.call("POST", "/company/booking-link", owner)["booking_id"]
    for request in [
        # A returning customer who types her number differently: the office is offered Dana, not forced to her
        {"name": "Dana", "phone": "555.010.2222", "title": "Annual furnace check",
         "preferred_time": "Any weekday after 3pm"},
        # Obvious spam, to decline
        {"name": "xx", "email": "deals@spam.example", "title": "CHEAP PILLS ONLINE"},
    ]:
        api.call("POST", f"/public/book/{booking_id}", body=request)

    web = args.api.replace(":8080", ":5173").replace(":8090", ":5180")
    print(f"""
Demo company ready: {COMPANY} (tag {tag})

  Web app           {web}
  Booking page      {web}/book/{booking_id}

  Owner             {email('owner')}
  Dispatcher        {email('dispatch')}
  Tech Sam R.       {email('sam')}
  Tech Alex P.      {email('alex')}
  Password (all)    {PASSWORD}

On the board: "Replace kitchen faucet" for Mike Chen, Alex P., tomorrow 1:00 PM (dispatched).
In the inbox: Dana's furnace check (matches customer Dana Lee) and one spam request.
During the demo, book the water heater job yourself from the booking page.
""")


if __name__ == "__main__":
    main()
