"""Used when no SMTP server is configured.

Locally it logs the whole email, so you can click the reset link from `docker compose logs api`.
Anywhere else it only logs that an email was dropped: reset links are secrets.
"""
import logging

log = logging.getLogger("opendispatch.email")


class LogEmail:
    def __init__(self, show_body: bool) -> None:
        self.show_body = show_body

    def send(self, to: str, subject: str, body: str) -> None:
        if self.show_body:
            log.warning("EMAIL (not sent, SMTP not configured)\nSubject: %s\n\n%s", subject, body)
        else:
            log.error("Email '%s' was not sent: SMTP is not configured", subject)
