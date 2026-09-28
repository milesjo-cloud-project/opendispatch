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
- Postgres: localhost:5432

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

Tests that need Postgres are skipped unless `TEST_DATABASE_URL` points at a migrated database.

## Job status flow

```
Requested → Scheduled → Dispatched → EnRoute → InProgress → Completed → Invoiced → Paid
Dispatched → Scheduled is allowed (reschedule).
Cancelled: reachable from anything before Completed. Paid and Cancelled are final.
```

The table lives in `api/app/domain/job_status.py`. The only way to change a job's status is
`job.transition_to(...)`, which returns a `JobEvent` to save in the same transaction.

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
