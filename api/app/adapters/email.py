"""Email adapters (shared.ports.EmailPort): SMTP for real mail, the log when SMTP isn't
configured, and a fake for tests."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger("opendispatch.email")


class SmtpEmail:
    """Sends email through any SMTP server: Gmail, Postmark, Resend, SendGrid, SES, ...

    Port 465 uses TLS from the start; anything else (usually 587) upgrades with STARTTLS.
    TLS is always required, so the password never crosses the network in the clear.
    """

    def __init__(self, host: str, port: int, username: str | None, password: str | None,
                 sender: str, timeout: float = 10) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.sender = sender
        self.timeout = timeout

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.port == 465:
            return smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
        smtp = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        smtp.starttls(context=context)
        return smtp

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with self._connect() as smtp:
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)


class LogEmail:
    """Used when no SMTP server is configured.

    Locally it logs the whole email, so you can click the reset link from `docker compose logs api`.
    Anywhere else it only logs that an email was dropped: reset links are secrets.
    """

    def __init__(self, show_body: bool) -> None:
        self.show_body = show_body

    def send(self, to: str, subject: str, body: str) -> None:
        if self.show_body:
            log.warning("EMAIL (not sent, SMTP not configured)\nSubject: %s\n\n%s", subject, body)
        else:
            log.error("Email '%s' was not sent: SMTP is not configured", subject)


class FakeEmail:
    """In-memory email for tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))
