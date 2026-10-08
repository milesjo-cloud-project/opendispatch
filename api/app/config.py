import logging
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("opendispatch.config")

# Signs technician job links when JOB_LINK_SECRET isn't set and APP_ENV is "local", so the
# links work out of the box on your own machine. Everyone's copy of the repo has this value,
# so it is never used anywhere else: outside local, no secret means no links.
LOCAL_JOB_LINK_SECRET = "local-development-only-not-a-secret"


class Settings(BaseSettings):
    """Read from environment variables (.env locally, Secret Manager on GCP later)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql://opendispatch:change-me@127.0.0.1:5432/opendispatch"

    # SMS alerts. Leave unset and alerts go to the API log instead.
    twilio_account_sid: str | None = None
    twilio_auth_token: SecretStr | None = None
    twilio_from_number: str | None = None

    # Email (password resets). Leave SMTP_HOST unset and emails go to the API log instead.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    email_from: str = "OpenDispatch <no-reply@localhost>"

    # Who may create a new company (POST /auth/signup). "first-run": only while the server
    # has no company yet, so a contractor's own install is theirs alone once set up.
    # "open": anyone, for a hosted service or local demos. "closed": nobody; owners add people.
    signup: Literal["open", "first-run", "closed"] = "first-run"

    # Where the web app lives, for links in emails
    app_base_url: str = "http://localhost:5173"
    upload_dir: str = "./uploads"

    # Technician job links: the signed /j/<token> link in a calendar event that opens the
    # job with no login. Nothing is stored, so the secret is what makes a link real;
    # changing it invalidates every link ever issued.
    job_link_secret: SecretStr | None = None
    # How long a link lasts past the job's scheduled time (see jobs/links.py).
    job_link_ttl_hours: int = 72

    # Google Calendar (optional). Leave GOOGLE_REFRESH_TOKEN unset and calendar writes go to
    # the API log instead. These belong to the Google account whose calendar the jobs go on;
    # README says how to get the refresh token.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None
    google_refresh_token: SecretStr | None = None
    google_calendar_id: str = "primary"

    # Google Sheets (optional), and only for the launch waitlist: a copy of the signups in
    # a spreadsheet the project's own team can read without the API. Leave GOOGLE_SHEETS_ID
    # unset and the rows go to the API log instead, which is right for every install that
    # isn't taking signups. The spreadsheet must already exist and be shared with the
    # Google account below, and GOOGLE_SHEETS_TAB must name a tab that's in it.
    google_sheets_id: str | None = None
    google_sheets_tab: str = "Waitlist"
    # Sheets needs the .../auth/spreadsheets scope, which the calendar token doesn't have
    # unless it was consented with both. Set this to use a second token for Sheets; leave
    # it blank to use GOOGLE_REFRESH_TOKEN (see the README).
    google_sheets_refresh_token: SecretStr | None = None

    # How long a job blocks out on a calendar. Jobs have a start time but no end yet.
    default_job_minutes: int = 120
    # How often app/outbox/worker.py looks for writes to retry (calendar, waitlist
    # spreadsheet), when it has nothing to do.
    outbox_poll_seconds: int = 30

    # The launch waitlist (app/waitlist/). "closed" on purpose: most installs are a
    # contractor running OpenDispatch for their own business, and they shouldn't collect
    # signups for someone else's launch. Only the project's own server sets "open".
    waitlist: Literal["open", "closed"] = "closed"
    # Reading the list needs this in the X-Waitlist-Token header. Unset means nobody can,
    # because a signup has no company and so no owner who could be trusted with it.
    waitlist_admin_token: SecretStr | None = None
    # Shown on the public page as the launch window, so it moves without a code change.
    launch_label: str = "Winter 2027"
    # Signups one IP address can send per hour. Lower than booking: a visitor needs one.
    waitlist_limit_per_hour: int = 3

    # Online booking spam control: bookings one IP address can send per hour, across every
    # company's link. Raise it if many customers share one address (an office, a campus).
    booking_limit_per_hour: int = 5
    # Password-guessing control, also per IP address across every account. Only WRONG
    # passwords count, so a whole office signing in from one address never hits it.
    login_failures_per_15_minutes: int = 10
    # New companies, and password reset emails, one IP address can ask for per hour.
    signup_limit_per_hour: int = 5
    reset_limit_per_hour: int = 5
    # How many proxies sit in front of the API and add to X-Forwarded-For (a load balancer,
    # a dev server). 0 = clients connect directly. Too high lets a client pick its own address
    # (fewer limits); too low puts everyone behind the proxy in one shared limit.
    trusted_proxy_hops: int = 0

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host)

    @property
    def sms_configured(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number)

    @property
    def is_local(self) -> bool:
        return self.app_env == "local"

    @property
    def waitlist_open(self) -> bool:
        return self.waitlist == "open"

    @property
    def google_calendar_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_refresh_token)

    @property
    def sheets_refresh_token(self) -> str | None:
        """The token Sheets uses: its own if there is one, otherwise the calendar's."""
        token = self.google_sheets_refresh_token or self.google_refresh_token
        return token.get_secret_value() if token is not None else None

    @property
    def google_sheets_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret
                    and self.sheets_refresh_token and self.google_sheets_id)

    @property
    def job_link_key(self) -> bytes | None:
        """The key technician job links are signed with, or None when they're turned off."""
        if self.job_link_secret is not None:
            return self.job_link_secret.get_secret_value().encode()
        return LOCAL_JOB_LINK_SECRET.encode() if self.is_local else None

    @model_validator(mode="after")
    def _warn_about_the_development_signing_key(self) -> "Settings":
        """APP_ENV defaults to "local", so a deployment that forgets to set it signs job
        links with the key published in this repo. Forging one still needs a job and a
        technician UUID, but those leak more easily than a secret does, so say so loudly."""
        if self.job_link_secret is None and self.is_local:
            log.warning(
                "Technician job links are signed with the development key from config.py. "
                "That is fine on your own machine. Anywhere else, set APP_ENV and "
                "JOB_LINK_SECRET, or anyone who learns a job's id can forge a link to it."
            )
        return self

    @model_validator(mode="after")
    def _warn_about_a_spreadsheet_with_no_account(self) -> "Settings":
        """A spreadsheet id with no OAuth client behind it means the waitlist rows quietly
        go to the log, which looks exactly like it working until launch day."""
        if self.google_sheets_id and not self.google_sheets_configured:
            log.warning(
                "GOOGLE_SHEETS_ID is set but the Google account isn't: waitlist signups "
                "will be written to the log, not the spreadsheet. Set GOOGLE_CLIENT_ID, "
                "GOOGLE_CLIENT_SECRET and a refresh token."
            )
        return self

    @model_validator(mode="after")
    def _require_database_url_outside_local(self) -> "Settings":
        # The default above is for local dev only; anywhere else a missing URL is a mistake.
        if not self.is_local and "database_url" not in self.model_fields_set:
            raise ValueError("DATABASE_URL must be set when APP_ENV is not 'local'")
        return self


settings = Settings()
