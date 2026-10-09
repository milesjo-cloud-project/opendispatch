"""Authenticating to Google as a service account, against a stubbed HTTP transport.

No network and no real account: the test makes its own key pair, so the assertion the
adapter signs can be verified here with the matching public key.

Skipped when `cryptography` isn't installed, because it's optional at runtime
(requirements-sheets.txt) -- only the Sheets copy of the waitlist needs it. CI installs
it, so these do run on every change.
"""
import base64
import json
import time

import httpx
import pytest

cryptography = pytest.importorskip("cryptography", reason="see requirements-sheets.txt")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402

from app.adapters.google_service_account import TOKEN_URL, ServiceAccountToken  # noqa: E402

SCOPE = "https://www.googleapis.com/auth/spreadsheets"
EMAIL = "opendispatch-waitlist@opendispatch.iam.gserviceaccount.com"


@pytest.fixture(scope="module")
def keys():
    """One key pair for the whole module; generating RSA keys isn't free."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, private.public_key()


def unpad(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


class Google:
    """Records what the adapter sent and answers with whatever the test asks for."""

    def __init__(self, token: httpx.Response | None = None) -> None:
        self.token = token or httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.token

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    @property
    def sent(self) -> dict:
        import urllib.parse
        return dict(urllib.parse.parse_qsl(self.requests[-1].content.decode()))


def account(keys, google: Google) -> ServiceAccountToken:
    pem, _ = keys
    return ServiceAccountToken(EMAIL, pem, SCOPE, http=google.client())


# --- the assertion

def test_the_assertion_says_who_we_are_and_what_we_want(keys):
    google = Google()
    account(keys, google).access_token()

    body = google.sent
    assert str(google.requests[-1].url) == TOKEN_URL
    assert body["grant_type"] == "urn:ietf:params:oauth:grant-type:jwt-bearer"

    header_b64, claims_b64, _ = body["assertion"].split(".")
    assert json.loads(unpad(header_b64)) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(unpad(claims_b64))
    assert claims["iss"] == EMAIL
    assert claims["scope"] == SCOPE
    assert claims["aud"] == TOKEN_URL  # signing for the wrong audience is a replay risk
    assert claims["exp"] - claims["iat"] == 3600  # Google refuses longer than an hour
    assert abs(claims["iat"] - int(time.time())) < 30


def test_the_assertion_is_really_signed_by_the_private_key(keys):
    """The whole point: Google accepts it because only the key holder could have made it."""
    _, public = keys
    google = Google()
    account(keys, google).access_token()

    header_b64, claims_b64, signature_b64 = google.sent["assertion"].split(".")
    public.verify(
        unpad(signature_b64),
        f"{header_b64}.{claims_b64}".encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )  # raises InvalidSignature if it isn't


def test_a_tampered_assertion_would_not_verify(keys):
    """Guards the test above against passing for the wrong reason."""
    from cryptography.exceptions import InvalidSignature

    _, public = keys
    google = Google()
    account(keys, google).access_token()
    header_b64, claims_b64, signature_b64 = google.sent["assertion"].split(".")
    with pytest.raises(InvalidSignature):
        public.verify(unpad(signature_b64), f"{header_b64}.{claims_b64}x".encode(),
                      padding.PKCS1v15(), hashes.SHA256())


# --- the access token

def test_the_access_token_is_fetched_once_and_reused(keys):
    google = Google()
    token = account(keys, google)
    assert token.access_token() == "at-1"
    assert token.access_token() == "at-1"
    assert len(google.requests) == 1


def test_a_token_about_to_expire_is_replaced(keys):
    google = Google(httpx.Response(200, json={"access_token": "at-1", "expires_in": 30}))
    token = account(keys, google)
    token.access_token()
    token.access_token()
    assert len(google.requests) == 2  # 30s left is inside the EARLY window


def test_a_refused_assertion_raises_with_googles_reason(keys):
    """A wrong clock or a deleted account; the outbox retries and keeps the reason."""
    google = Google(httpx.Response(400, text='{"error": "invalid_grant"}'))
    with pytest.raises(RuntimeError, match="invalid_grant"):
        account(keys, google).access_token()


def test_the_key_is_never_echoed_in_the_error(keys):
    google = Google(httpx.Response(401, text='{"error": "unauthorized_client"}'))
    with pytest.raises(RuntimeError) as caught:
        account(keys, google).access_token()
    assert "PRIVATE KEY" not in str(caught.value)


# --- reading Google's JSON key file

def test_a_key_file_is_all_it_takes(keys):
    pem, _ = keys
    google = Google()
    blob = json.dumps({"type": "service_account", "client_email": EMAIL, "private_key": pem})
    token = ServiceAccountToken.from_json(blob, SCOPE, http=google.client())
    assert token.access_token() == "at-1"
    assert token.client_email == EMAIL


def test_a_key_file_that_is_not_json_says_so():
    with pytest.raises(RuntimeError, match="isn't valid JSON"):
        ServiceAccountToken.from_json("not json at all", SCOPE)


@pytest.mark.parametrize("drop", ["client_email", "private_key"])
def test_a_key_file_missing_a_field_names_the_field(keys, drop):
    pem, _ = keys
    info = {"type": "service_account", "client_email": EMAIL, "private_key": pem}
    del info[drop]
    with pytest.raises(RuntimeError, match=drop):
        ServiceAccountToken.from_json(json.dumps(info), SCOPE)


def test_a_mangled_key_fails_at_startup_not_at_the_first_write():
    """So a bad key is a loud error when the process starts, not a stuck outbox row."""
    info = {"client_email": EMAIL, "private_key": "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----\n"}
    # cryptography's own parse error, not one we reshape: the point is that it's raised
    # here, while the app is starting, rather than swallowed until the first write.
    with pytest.raises(ValueError):
        ServiceAccountToken.from_json(json.dumps(info), SCOPE)
