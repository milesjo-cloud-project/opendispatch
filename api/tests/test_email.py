"""The SMTP adapter, against a stand-in for smtplib (no real mail server)."""
import logging

import pytest

from app.adapters import email as smtp_module
from app.adapters.email import LogEmail, SmtpEmail


class FakeSmtp:
    instances: list["FakeSmtp"] = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port
        self.tls = context is not None  # SMTP_SSL passes a context up front
        self.logged_in = None
        self.messages = []
        FakeSmtp.instances.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, user, password):
        assert self.tls, "never send a password before TLS"
        self.logged_in = (user, password)

    def send_message(self, msg):
        self.messages.append(msg)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def fake_smtplib(monkeypatch):
    FakeSmtp.instances = []
    monkeypatch.setattr(smtp_module.smtplib, "SMTP", FakeSmtp)
    monkeypatch.setattr(smtp_module.smtplib, "SMTP_SSL", FakeSmtp)


@pytest.mark.parametrize("port", [587, 465])
def test_smtp_sends_over_tls(port):
    SmtpEmail("smtp.example.com", port, "apikey", "s3cret", "OpenDispatch <no-reply@example.com>").send(
        "owner@example.com", "Hello", "Body text")
    server = FakeSmtp.instances[0]
    assert (server.host, server.port) == ("smtp.example.com", port)
    assert server.tls
    assert server.logged_in == ("apikey", "s3cret")
    msg = server.messages[0]
    assert msg["To"] == "owner@example.com" and msg["Subject"] == "Hello"
    assert msg.get_content().strip() == "Body text"


def test_smtp_without_username_skips_login():
    SmtpEmail("relay.internal", 587, None, None, "x@example.com").send("a@example.com", "s", "b")
    assert FakeSmtp.instances[0].logged_in is None


def test_log_email_hides_body_outside_local(caplog):
    with caplog.at_level(logging.WARNING):
        LogEmail(show_body=False).send("a@example.com", "Reset", "secret-link")
        assert "secret-link" not in caplog.text and "a@example.com" not in caplog.text
        LogEmail(show_body=True).send("a@example.com", "Reset", "secret-link")
        assert "secret-link" in caplog.text
