"""The one piece both Google adapters need: turning a refresh token into access tokens.

Shared by adapters/google_calendar.py and adapters/google_sheets.py. Trading a refresh
token for an access token is a form POST, so there's no JWT to sign and no crypto library
to install; a self-hoster installs nothing beyond requirements.txt.

The scopes a token can be used for are the ones it was consented with, not something sent
at refresh time, so each adapter documents the scope it needs and one token can cover
both (see README, "Connecting Google").
"""
from datetime import datetime, timedelta, timezone

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleToken:
    """Turns the long-lived refresh token into short-lived access tokens, and keeps one
    until it's nearly up. Shared by every request an adapter makes."""

    # Refresh a minute early, so a token can't expire between the check and the call.
    EARLY = timedelta(seconds=60)

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 http: httpx.Client | None = None) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.http = http or httpx.Client(timeout=10)
        self._token: str | None = None
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)

    def access_token(self) -> str:
        if self._token is not None and datetime.now(timezone.utc) < self._expires_at - self.EARLY:
            return self._token
        r = self.http.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        })
        if r.status_code >= 400:
            # Google's error body is a short code like "invalid_grant" (a revoked or
            # expired refresh token). It doesn't echo the secrets we just sent.
            raise RuntimeError(f"Google refused the refresh token: {r.status_code} {r.text[:300]}")
        body = r.json()
        self._token = body["access_token"]
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(body.get("expires_in", 3600)))
        return self._token
