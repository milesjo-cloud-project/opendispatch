# OpenDispatch

Open-source dispatch and job tracking for small service businesses.

## Customer guide

OpenDispatch is for small service teams. Owners and dispatchers manage customers, jobs,
and the team schedule. Technicians can use the web app on a phone to see their assigned
work and update job status. Customers can receive a private link to follow a job.

### Editions and availability

The product is intended to offer two choices:

- **Hosted:** OpenDispatch runs the service; the team signs in on the website or phone.
- **Self-hosted:** the business runs OpenDispatch on its own computer or office server.

Online purchase, hosted accounts, software activation, and a packaged customer installer
are not set up yet. The Windows instructions below are for a self-hosted preview from this
source project; they are not a finished commercial installation process.

### Start the Windows preview

Before starting, install and open Docker Desktop. The preview currently starts from the
OpenDispatch project folder; it does not install Docker Desktop or ship as a standalone
installer.

1. Open the project folder in File Explorer.
2. Double-click `start.bat`. The first run creates a private `.env` file with a random
   database password. The launcher starts Docker Desktop if needed and then starts the
   web app, API, and database. Leave the terminal window open while you use OpenDispatch.
3. On the computer, open [http://localhost:5173](http://localhost:5173).
4. Choose **New company? Sign up**. Enter your company name, email, and a password with at
   least 12 characters. This creates the owner account. Sign-up then closes on this server.
5. In **Team**, add dispatchers and technicians with their own starting passwords. Add
   customers, then create a job and assign it to a technician.

Keep `.env` private. It contains the database password; it is not your OpenDispatch login.
Do not delete it or change the database password by itself after setup.

### Day-to-day work

- **Team:** owners add dispatchers and technicians. Each technician has a personal schedule
  and a **Today** list on their phone.
- **Customers:** add and search customers, or create one while making a job.
- **New job:** a job with a scheduled time goes onto the schedule; without a time it waits
  in **Open shifts** as a draft.
- **Job progress:** office staff dispatch, invoice, mark paid, or cancel. Technicians use
  **On my way → Start work → Mark complete** from their assigned jobs.

### Use a phone on the shop Wi-Fi

Start OpenDispatch with `start.bat`. It prints a phone URL when Windows has an active
network marked **Private**. Connect the phone to that same trusted shop Wi-Fi and open the
printed URL in its browser. Sign in with the technician's own account. No separate phone
app is included in this preview.

**This preview serves the phone connection over unencrypted HTTP. Passwords and login
tokens are not encrypted in transit. Use demo data only on a trusted private network. Do
not use guest/public Wi-Fi, and do not forward port 5173 from the router.** A customer-ready
self-hosted release needs HTTPS before it should carry real business data over a network.

If no phone URL appears, set the shop computer's Wi-Fi network profile to **Private** in
Windows Network settings, then restart `start.bat`. Windows Firewall or Wi-Fi client
isolation may also prevent a phone from reaching the computer.

### Stop the preview and protect its data

Press **Ctrl+C** in the launcher window to stop the services. Starting `start.bat` again
brings them back. The database and uploaded files stay in Docker-managed volumes, but this
preview does not make automatic backups. It is not ready to be the only copy of business
records. Avoid `docker compose down -v`: the `-v` option deletes the database and uploaded
files.

### Start on macOS or Linux

Copy `.env.example` to `.env`, replace `change-me` with the same strong password in
`POSTGRES_PASSWORD` and `DATABASE_URL`, then run:

```
docker compose up --build
```

The service URLs are:

- Web: http://localhost:5173
- API health: http://localhost:8080/healthz and http://localhost:8080/readyz
- API docs: http://localhost:8080/docs
- Postgres: `127.0.0.1:5432` (local machine only)

## Developer guide

The rest of this README documents the source code and local development workflow.
For a customer, the preview setup above is the relevant section.

### Run the API tests without Docker

```
cd api
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
python -m pytest -v
ruff check .                    # lint; CI runs it too. `ruff check . --fix` fixes the easy ones
```

The web code is formatted with Prettier. After editing anything in `web/`, run
`npm run format` there (CI fails on unformatted code). VS Code's Prettier extension can do it on save.

Tests that need Postgres are skipped unless `TEST_DATABASE_URL` points at a migrated database,
e.g. with `docker compose up` running: `$env:TEST_DATABASE_URL = "postgresql://opendispatch:change-me@127.0.0.1:5432/opendispatch"`

### Job status flow

```
Requested → Scheduled → Dispatched → EnRoute → InProgress → Completed → Invoiced → Paid
Dispatched → Scheduled is allowed (reschedule).
Cancelled: reachable from anything before Completed. Paid and Cancelled are final.
```

The table lives in `api/app/shared/job_status.py`. The only way to change a job's status is
`job.transition_to(...)`, which returns a `JobEvent` to save in the same transaction.

Editing a job (`PATCH /jobs/{id}`) also depends on its stage. The rules are on `Job` in
`api/app/shared/models.py`:

- **Technician:** can change until the job is Completed. Can be removed only from a draft or
  scheduled job; pull a dispatched job back to Scheduled first.
- **Start time:** can change until the tech is en route. Only a draft can have no time.
- **Quote:** can change until the job is Invoiced.
- **Title and description:** can change until the job is Paid or Cancelled.

Sending a value the job already has is always fine. If any change is refused, nothing in that
request is saved.

### Expenses and job budgets

Money is stored as whole cents (`50_000` = $500.00), never floats.

- `job.add_expense(company, submitted_by, amount_cents, ...)` is the only way to record spend.
  Each expense belongs to exactly one job. Paid and cancelled jobs don't take new expenses.
- Expenses at or under the company's `expense_approval_limit_cents` ($500 by default) are
  approved on the spot. Anything over waits until the owner calls `approve()` or `reject()`.
  An owner's own spend is never held.
- `job_budget(job, expenses)` in `api/app/spend/budget.py` compares spend (approved + pending,
  not rejected) against `job.quoted_amount_cents`. `alert_for(...)` tells you when a new
  expense crosses 80% or 100%, once per threshold. Budgets warn; they never block spend.
- Labor counts too: `job.log_time(technician, started_at, ended_at)` records time for the
  assigned tech and copies their `hourly_rate_cents`, so a later raise doesn't change old jobs.
- `app/spend/service.py` is what the API will call: `submit_expense()` and `log_time()` lock the
  job, save the spend, and write a `budget_alerts` row in the same transaction if a threshold was
  crossed. After committing, `send_pending_alerts(session, notifier)` sends them to the owners.
  Locally the notifier just writes to the API log; email/SMS adapters come later.

### Logging in and using the API

Open http://localhost:8080/docs, call `POST /auth/signup` with a company name, email and password
(12+ characters), and copy the `token` from the response. Click **Authorize**, paste the token,
and every other endpoint works as that owner. `POST /auth/login` gets a new token later.

- Tokens last 14 days. `POST /auth/logout` ends one; changing your password ends all the others.
- 10 wrong passwords from one address lock the account for 15 minutes *from that address*; the
  owner can still sign in from anywhere else. 100 wrong in a row from anywhere lock it everywhere.
  A password reset unlocks it.
- Owners add people with `POST /users` (with a starting password). Include
  `"technician": {"display_name": ..., "hourly_rate_cents": ...}` to make them a technician in the
  same request, or do it later with `POST /technicians`.
- `POST /jobs` takes a `customer_id`, or a `new_customer` to create one in the same request, and
  `"schedule": true` to put the job straight on the schedule. If any part is refused, nothing is
  saved, so retrying never makes duplicates.
- When someone leaves, an owner calls `POST /users/{id}/disable` (**Disable** on the Team page).
  It signs them out everywhere, cancels their reset links and job links, stops them signing in,
  takes their technician profile off the schedule, and takes their current and upcoming jobs off
  their calendar. Their jobs and history stay. `POST /users/{id}/enable` undoes it, calendar
  included. Owners can't disable themselves.
- Deactivating a technician (`PATCH /technicians/{id}`) only takes them off the schedule: new jobs
  can't be assigned to them, but they can still sign in.

### Forgotten passwords

`POST /auth/password-reset/request` with an email sends a link that works once, for one hour.
It answers the same whether or not the account exists, and sends at most 5 links per account per hour.
`POST /auth/password-reset/confirm` with the token and a new password sets it, unlocks the account,
logs it out everywhere, and cancels any other reset links.

Without `SMTP_*` in `.env` (see `.env.example`), the email, link included, is written to the API log
(`docker compose logs api`), which is all you need locally.

### Job documents and customer tracking links

- `POST /jobs/{id}/attachments` stores a photo (any `image/*`, including HEIC) or a PDF, up to 12 MiB.
  Anyone who can see the job can upload and download; files always download rather than open in the
  browser. In compose they live in the `uploads` volume; without Docker, in `./uploads` (`UPLOAD_DIR`).
- `POST /jobs/{id}/tracking-link` (owners and dispatchers, scheduled jobs onward) makes a private
  90-day link, `/track/<token>`, for the customer. It shows only the job title, status, and scheduled
  time, needs no login, and making a new link replaces the old one. Only a hash of the token is stored.

### Scheduling and technician job links

Jobs are scheduled inside OpenDispatch. The schedule remains local to the self-hosted install;
external calendar invitations and sync are deferred. A technician can open a private `/j/<token>`
link on a phone with no login to see the job, customer, phone, address, and work notes. The link
never shows the quote.

- The token is signed, not stored. Changing `JOB_LINK_SECRET` invalidates every link at once,
  and no single link can be revoked on its own. It expires after `JOB_LINK_TTL_HOURS`, names
  one technician so reassignment kills the old link, and is read-only.
- Disabling someone's account kills their links at once. The jobs, expenses, and history stay.
- Set `JOB_LINK_SECRET` to a long random string outside local. Left blank it works locally
  with a built-in development key and is disabled elsewhere.
- `POST /jobs/{id}/job-link` gives the office a link to share manually.
- Customer tracking links use random tokens with only a hash stored. The office can replace
  them; `api/app/jobs/links.py` explains the difference.
### The launch waitlist

`/waitlist` is the public page for the Winter 2027 launch: the founding prices and a signup
form. Every route behind it is **off unless `WAITLIST=open`**, because your copy runs your
business and the waitlist collects signups for the OpenDispatch launch, not for you. With it
closed the page says so and the API answers 404.

- `GET /public/waitlist` tells the page the launch window (`LAUNCH_LABEL`) and how many of
  the 100 founding spots are left. `POST /public/waitlist` joins the list: email is the only
  required field, limited to `WAITLIST_LIMIT_PER_HOUR` per IP address, with a honeypot field
  for bots. Signing up twice is not an error and never takes a second spot — the same
  address gets its original number back, so a double tap or a forgetful visitor keeps the
  spot they already hold.
- Spots are handed out in order under an advisory lock and never reused, because the
  founding price is promised to the first 100 people on the list.
- `GET /waitlist` returns the list and the counts, and needs `WAITLIST_ADMIN_TOKEN` in the
  `X-Waitlist-Token` header. Not a user role: a signup has no `company_id` (it is the only
  table without one), so there is no owner it could belong to, and a company owner on a
  hosted server must never be able to read everyone else’s contact details.

#### Hosted launch site (deferred)

The local app and its FastAPI waitlist do not require Vercel or Supabase. A public hosted
launch site is outside this self-hosted release and can be planned separately later.

### SMS alerts

Budget alerts are texted to owners when all three are true: Twilio is set in `.env`
(`TWILIO_*`, see `.env.example`), the company has `sms_alerts_enabled` on (`PATCH /company`),
and the owner has a phone number (`PATCH /me`). Anyone else gets the alert in the API log.

### Who sees what

Rules live in `api/app/shared/access.py`; `api/app/db/queries.py` applies the same rules
in SQL. Owners and dispatchers see every job in their company, plus quotes and budgets.
Technicians see only jobs assigned to them, and only their own expenses on those jobs.

### Database migrations

After changing `api/app/db/tables.py`:

```
docker compose exec api alembic revision --autogenerate -m "describe the change"
```

Read the new file in `api/migrations/versions/`, then restart the API (or run
`docker compose exec api alembic upgrade head`). Never edit a migration that's already been applied.

### Layout

```
api/
  app/          grouped by feature: each folder has its routes, request/response shapes and logic
    auth/       sign-up, login, sessions, password reset
    company/    company settings, team (users, technicians), customers
    jobs/       jobs, status changes, files, expenses and time, and the private links:
                customer tracking and signed technician job links
    booking/    online booking: public link and form, the office's request inbox
    waitlist/   the launch waitlist: the public /waitlist page's API, and the copy of the
                signups in the local database. The only feature with no company_id, and off
                unless WAITLIST=open
    calendar/   local event details for technician job links
    outbox/     the worker that retries every queued write to an outside service
    spend/      budgets and budget alerts
    shared/     used by every feature: models, job status flow, who-sees-what, errors,
                ports (interfaces for outside services), the outbox pattern and its retry
                policy, login/session dependencies
    db/         Postgres: table definitions, sessions, tenant-scoped queries
    adapters/   outside services behind the ports: email,
                SMS, notifications, passwords, files
    main.py     FastAPI wiring
  migrations/   Alembic
  tests/
web/            React + Vite
ml/             Phase 7
deploy/         deploy docs, later
infra/terraform/
  modules/app/  APIs, Artifact Registry, service accounts, WIF, Secret Manager, Cloud Run
  envs/dev, envs/prod
```

### Cloud infrastructure (deferred)

The Terraform files are retained for a possible hosted deployment. They are not used by
the self-hosted release. No cloud account or cloud infrastructure is required for local setup.
