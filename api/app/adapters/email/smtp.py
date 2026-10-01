"""Sends email through any SMTP server: Gmail, Postmark, Resend, SendGrid, SES, ...

Port 465 uses TLS from the start; anything else (usually 587) upgrades with STARTTLS.
TLS is always required, so the password never crosses the network in the clear.
"""
import smtplib
import ssl
from email.message import EmailMessage


class SmtpEmail:
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
