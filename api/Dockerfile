FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

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
