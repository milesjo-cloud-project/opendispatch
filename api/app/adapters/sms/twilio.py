"""Sends texts through Twilio's REST API. Plain HTTP, no Twilio SDK needed."""

import httpx


class TwilioSms:
    API = "https://api.twilio.com/2010-04-01"

    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 http: httpx.Client | None = None) -> None:
        self.account_sid = account_sid
        self.from_number = from_number
        self.http = http or httpx.Client(timeout=10)
        self._auth = (account_sid, auth_token)

    def send(self, to: str, body: str) -> None:
        r = self.http.post(
            f"{self.API}/Accounts/{self.account_sid}/Messages.json",
            data={"To": to, "From": self.from_number, "Body": body},
            auth=self._auth,
        )
        if r.status_code >= 400:
            # Twilio's error body names the problem (bad number, unverified, ...); no secrets in it.
            raise RuntimeError(f"Twilio refused the message: {r.status_code} {r.text[:300]}")
