"""Authenticating to Google as a service account, for the launch waitlist's spreadsheet.

The other way in is adapters/google_auth.py: a person consents once and we keep their
refresh token. That is the only option for the calendar, because a service account cannot
invite attendees without Google Workspace domain-wide delegation, and an invite is the
whole point there.

Writing cells needs no attendees, so Sheets can use a service account instead, and should:
an External OAuth app in Testing status has its refresh token expired by Google after 7
days, which would mean re-consenting every week forever. A service account's credentials
do not expire. The spreadsheet is shared with the service account's own email address, so
it is the one file the account can touch.

The cost is one dependency. A service account proves who it is by signing a JWT with its
private key (RS256), and signing needs real crypto, so this module imports `cryptography`
-- requirements-sheets.txt, not requirements.txt. The import is deliberately inside
__init__ so that a self-hoster who never configures a service account never needs it and
gets a plain explanation if they half-configure one.
"""
import base64
import json
import time
from datetime import datetime, timedelta, timezone

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
# Google refuses an assertion that asks for more than an hour.
ASSERTION_LIFETIME = timedelta(hours=1)

MISSING_CRYPTOGRAPHY = (
    "Authenticating as a service account needs the `cryptography` package, which isn't "
    "in requirements.txt because only the Google Sheets copy of the launch waitlist uses "
    "it. Install it with `pip install -r requirements-sheets.txt`, or leave "
    "GOOGLE_SERVICE_ACCOUNT_FILE unset and use GOOGLE_REFRESH_TOKEN instead."
)


def _b64(raw: bytes) -> bytes:
    """base64url with no padding, which is what JWS uses."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


class ServiceAccountToken:
    """Turns a service account's private key into short-lived access tokens, and keeps one
    until it's nearly up. Same shape as google_auth.GoogleToken, so adapters can take
    either without caring which."""

    # Refresh a minute early, so a token can't expire between the check and the call.
    EARLY = timedelta(seconds=60)

    def __init__(self, client_email: str, private_key: str, scope: str,
                 http: httpx.Client | None = None) -> None:
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:  # pragma: no cover - depends on what's installed
            raise RuntimeError(MISSING_CRYPTOGRAPHY) from exc

        self._hashes, self._padding = hashes, padding
        self.client_email = client_email
        self.scope = scope
        self.http = http or httpx.Client(timeout=10)
        self._token: str | None = None
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)
        # Parsed once, at startup rather than at the first write, so a mangled key is a
        # loud error when the process starts instead of a mystery in an outbox row.
        self._key = serialization.load_pem_private_key(private_key.encode(), password=None)

    @classmethod
    def from_json(cls, blob: str, scope: str, http: httpx.Client | None = None) -> "ServiceAccountToken":
        """Build one from the JSON key file Google hands you when you create the account."""
        try:
            info = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise RuntimeError("The Google service account key isn't valid JSON") from exc
        missing = [k for k in ("client_email", "private_key") if not info.get(k)]
        if missing:
            raise RuntimeError(
                f"The Google service account key is missing {', '.join(missing)}. "
                "Use the JSON file Google gives you when you add a key to the account."
            )
        return cls(info["client_email"], info["private_key"], scope, http=http)

    def _assertion(self, now: int) -> str:
        """A JWT saying 'I am this account and I want these scopes', signed with the key.

        Returned as str, not bytes: httpx form-encodes a bytes value by str()-ing it, so
        bytes would go out as the literal "b'eyJhbGci...'" and Google would refuse it.
        """
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": self.client_email,
            "scope": self.scope,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + int(ASSERTION_LIFETIME.total_seconds()),
        }
        signing_input = b".".join(
            _b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
        )
        signature = self._key.sign(signing_input, self._padding.PKCS1v15(), self._hashes.SHA256())
        return (signing_input + b"." + _b64(signature)).decode("ascii")

    def access_token(self) -> str:
        if self._token is not None and datetime.now(timezone.utc) < self._expires_at - self.EARLY:
            return self._token
        r = self.http.post(TOKEN_URL, data={
            "grant_type": GRANT,
            "assertion": self._assertion(int(time.time())),
        })
        if r.status_code >= 400:
            # Google's error body is a short code: invalid_grant for a clock that's wrong
            # or a deleted account, invalid_scope for a scope the account can't have. It
            # doesn't echo the key.
            raise RuntimeError(
                f"Google refused the service account: {r.status_code} {r.text[:300]}")
        body = r.json()
        self._token = body["access_token"]
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 3600)))
        return self._token
