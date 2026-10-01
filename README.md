# OpenDispatch

Open-source dispatch and job tracking for small service businesses.

## Run it locally

You need Docker Desktop and Git.

```
copy .env.example .env        # Windows Command Prompt
cp .env.example .env          # macOS / Linux / Git Bash
```

Open `.env` and change `change-me` to a password in **both** places
(`POSTGRES_PASSWORD` and inside `DATABASE_URL`). Then:

```
docker compose up --build
```

- Web: http://localhost:5173 (shows whether the API and database are up)
- API: http://localhost:8080/healthz and http://localhost:8080/readyz
- API docs: http://localhost:8080/docs
- Postgres: 127.0.0.1:5432 (only reachable from your own machine)

Use `127.0.0.1`, not `localhost`, in database URLs on your machine. On Windows `localhost`
tries IPv6 first, and the containers only listen on IPv4.

The API container runs `alembic upgrade head` on startup, so the tables are created for you.
Code changes in `api/app` and `web/src` reload automatically.
Stop with Ctrl+C. `docker compose down -v` also wipes the database.

## Run the API tests without Docker

```
cd api
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements-dev.txt
python -m pytest -v
```

Tests that need Postgres are skipped unless `TEST_DATABASE_URL` points at a migrated database,
e.g. with `docker compose up` running: `$env:TEST_DATABASE_URL = "postgresql://opendispatch:change-me@127.0.0.1:5432/opendispatch"`

## Job status flow

```
Requested → Scheduled → Dispatched → EnRoute → InProgress → Completed → Invoiced → Paid
Dispatched → Scheduled is allowed (reschedule).
Cancelled: reachable from anything before Completed. Paid and Cancelled are final.
```

The table lives in `api/app/domain/job_status.py`. The only way to change a job's status is
`job.transition_to(...)`, which returns a `JobEvent` to save in the same transaction.

## Expenses and job budgets

Money is stored as whole cents (`50_000` = $500.00), never floats.

- `job.add_expense(company, submitted_by, amount_cents, ...)` is the only way to record spend.
  Each expense belongs to exactly one job. Paid and cancelled jobs don't take new expenses.
- Expenses at or under the company's `expense_approval_limit_cents` ($500 by default) are
  approved on the spot. Anything over waits until the owner calls `approve()` or `reject()`.
  An owner's own spend is never held.
- `job_budget(job, expenses)` in `api/app/domain/budget.py` compares spend (approved + pending,
  not rejected) against `job.quoted_amount_cents`. `alert_for(...)` tells you when a new
  expense crosses 80% or 100%, once per threshold. Budgets warn; they never block spend.
- Labor counts too: `job.log_time(technician, started_at, ended_at)` records time for the
  assigned tech and copies their `hourly_rate_cents`, so a later raise doesn't change old jobs.
- `app/services/spend.py` is what the API will call: `submit_expense()` and `log_time()` lock the
  job, save the spend, and write a `budget_alerts` row in the same transaction if a threshold was
  crossed. After committing, `send_pending_alerts(session, notifier)` sends them to the owners.
  Locally the notifier just writes to the API log; email/SMS adapters come later.

## Logging in and using the API

Open http://localhost:8080/docs, call `POST /auth/signup` with a company name, email and password
(12+ characters), and copy the `token` from the response. Click **Authorize**, paste the token,
and every other endpoint works as that owner. `POST /auth/login` gets a new token later.

- Tokens last 14 days. `POST /auth/logout` ends one; changing your password ends all the others.
- 10 wrong passwords in a row lock the account for 15 minutes.
- Owners add people with `POST /users` (with a starting password) and turn a user into a
  technician with `POST /technicians`.

## Forgotten passwords

`POST /auth/password-reset/request` with an email sends a link that works once, for one hour.
It answers the same whether or not the account exists, and sends at most 5 links per account per hour.
`POST /auth/password-reset/confirm` with the token and a new password sets it, unlocks the account,
logs it out everywhere, and cancels any other reset links.

Without `SMTP_*` in `.env` (see `.env.example`), the email, link included, is written to the API log
(`docker compose logs api`), which is all you need locally.

## SMS alerts

Budget alerts are texted to owners when all three are true: Twilio is set in `.env`
(`TWILIO_*`, see `.env.example`), the company has `sms_alerts_enabled` on (`PATCH /company`),
and the owner has a phone number (`PATCH /me`). Anyone else gets the alert in the API log.

## Who sees what

Rules live in `api/app/domain/access.py`; `api/app/adapters/db/queries.py` applies the same rules
in SQL. Owners and dispatchers see every job in their company, plus quotes and budgets.
Technicians see only jobs assigned to them, and only their own expenses on those jobs.
Login itself isn't built yet; these rules take the user the login step will provide.

## Database migrations

After changing `api/app/adapters/db/tables.py`:

```
docker compose exec api alembic revision --autogenerate -m "describe the change"
```

Read the new file in `api/migrations/versions/`, then restart the API (or run
`docker compose exec api alembic upgrade head`). Never edit a migration that's already been applied.

## Layout

```
api/
  app/
    domain/     business rules, plain Python (entities, job status flow)
    ports/      interfaces the domain needs (calendar, health, ...)
    adapters/   implementations of ports (postgres tables/session, fake calendar, later Google/Stripe/SMS)
    services/   use cases the API calls (record spend, send alerts); they call the domain
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

## Terraform (offline for now)

```
cd infra/terraform/envs/dev
terraform init -backend=false
terraform fmt -recursive ../..
terraform validate
```

Don't run `plan` or `apply` until billing is on. `init` downloads the Google
provider but doesn't touch your GCP account.
