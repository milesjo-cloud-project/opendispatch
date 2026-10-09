FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

# The Google Sheets copy of the launch waitlist authenticates as a service account,
# which signs a JWT, which needs `cryptography`. Only the server taking signups wants it,
# so it's a build arg rather than a line in requirements.txt.
ARG WITH_SHEETS=false
COPY requirements.txt requirements-sheets.txt ./
RUN pip install --no-cache-dir -r requirements.txt     && if [ "$WITH_SHEETS" = "true" ]; then pip install --no-cache-dir -r requirements-sheets.txt; fi

COPY app ./app
COPY alembic.ini .
COPY migrations ./migrations

# Don't run as root
# and give it the one folder it writes to (job documents)
RUN useradd --uid 10001 --no-create-home app \
    && mkdir -p /srv/uploads && chown app /srv/uploads
USER app

# Cloud Run sets $PORT; locally it defaults to 8080
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
