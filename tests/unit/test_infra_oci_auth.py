"""Unit tests for infra/oci_auth.py and the OrasClient wiring that installs it.

The fake registry below is a requests transport. It answers the way a htpasswd-protected
zot registry does (401 with a Basic challenge until the Basic header arrives), so the
real oras-py request, retry and auth code paths run without any network access.
"""

from base64 import b64encode
from typing import Any
from urllib.parse import urlsplit

from oras.auth import AuthenticationException
from pytest import mark, raises
from requests import PreparedRequest, Request, Response
from requests.adapters import BaseAdapter, HTTPAdapter
from requests.structures import CaseInsensitiveDict

from margot.infra.oci import OrasClient
from margot.infra.oci_auth import ChallengeAwareAuth, DefaultTimeoutAdapter

REGISTRY = "registry.test"
REPO = "acme/app"
AUTH_SERVER = "auth.example"
BASIC_CREDS = b64encode(b"alice:s3cret").decode()
BASIC_CHALLENGE = 'Basic realm="Authorization Required"'
BEARER_CHALLENGE = f'Bearer realm="https://{AUTH_SERVER}/token",service="{REGISTRY}",scope="repository:{REPO}:push,pull"'
UPLOAD_URL = f"https://{REGISTRY}/v2/{REPO}/blobs/uploads/"
DEFAULT_TIMEOUT = (10, 60)


def _prepared(url: str, method: str = "GET") -> PreparedRequest:
    """Build a prepared request for constructing fake responses."""
    return Request(method, url).prepare()


def _response(request: PreparedRequest, status: int, headers: dict[str, str] | None = None, body: bytes = b"") -> Response:
    """Build a requests.Response the way a transport adapter would return it."""
    response = Response()
    response.status_code = status
    response.headers = CaseInsensitiveDict(headers or {})
    response._content = body
    response.url = request.url or ""
    response.request = request
    response.encoding = "utf-8"
    return response


def _registry_answer(request: PreparedRequest) -> Response:
    """Answer an authorized registry request with the status a push would see."""
    method = request.method or ""
    path = urlsplit(request.url or "").path
    if method == "POST" and path == f"/v2/{REPO}/blobs/uploads/":
        return _response(request, 202, {"Location": f"https://{REGISTRY}/v2/{REPO}/blobs/uploads/session-1"})
    if method == "PUT" and ("/blobs/uploads/" in path or "/manifests/" in path):
        return _response(request, 201)
    if method == "DELETE":
        return _response(request, 204)
    return _response(request, 404)


class FakeRegistry(BaseAdapter):
    """Transport that plays a protected registry. Records every request it receives."""

    def __init__(self, challenge: str | None, accepted_auth: str, *, forbid_accepted: bool = False) -> None:
        super().__init__()
        self.challenge = challenge
        self.accepted_auth = accepted_auth
        self.forbid_accepted = forbid_accepted
        self.requests: list[tuple[str, str, str | None]] = []
        self.unauthorized = 0

    @property
    def hosts(self) -> set[str]:
        """Every host that received a request."""
        return {urlsplit(url).netloc for _, url, _ in self.requests}

    def send(self, request: PreparedRequest, **_kwargs: Any) -> Response:
        """Answer one request as the fake registry (or token endpoint) would."""
        url = request.url or ""
        self.requests.append((request.method or "", url, request.headers.get("Authorization")))
        host = urlsplit(url).netloc
        if host == AUTH_SERVER:
            return _response(request, 200, body=b'{"token": "tok"}')
        if host != REGISTRY:
            return _response(request, 599)
        if request.headers.get("Authorization") != self.accepted_auth:
            self.unauthorized += 1
            headers = {"Www-Authenticate": self.challenge} if self.challenge else {}
            return _response(request, 401, headers)
        if self.forbid_accepted:
            return _response(request, 403)
        return _registry_answer(request)

    def close(self) -> None:
        """Nothing to release."""


def _client(fake: FakeRegistry, *, stored: bool) -> OrasClient:
    """Build an OrasClient whose transport is the fake registry.

    The docker config is replaced with an in-memory one so the test never reads ~/.docker.
    """
    client = OrasClient()
    client.session.mount("https://", fake)
    auths = {REGISTRY: {"auth": BASIC_CREDS}} if stored else {}
    client.auth._auth_config = {"auths": auths, "credsStore": None, "credHelpers": {}}
    client.auth.load_configs(client.get_container(f"{REGISTRY}/{REPO}:1.0.0"))
    return client


class TestBasicChallenge:
    """Basic challenges are answered with stored credentials, never by treating the realm as a token URL."""

    def test_basic_challenge_with_stored_credentials_retries_with_basic_header(self) -> None:
        """Should retry the request with Authorization: Basic when credentials are stored."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        response = client.do_request(UPLOAD_URL, "POST")

        assert response.status_code == 202
        assert fake.requests[-1][2] == f"Basic {BASIC_CREDS}"

    def test_basic_challenge_never_requests_the_realm(self) -> None:
        """Should contact only the registry host, never the bogus 'Authorization Required' realm."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        client.do_request(UPLOAD_URL, "POST")

        assert fake.hosts == {REGISTRY}

    def test_basic_challenge_without_credentials_fails_fast_without_retry_sleeps(self, mocker: Any) -> None:
        """Should raise AuthenticationException at once, with a login hint, and never sleep between retries."""
        sleep = mocker.patch("oras.decorator.time.sleep")
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=False)

        with raises(AuthenticationException, match=rf"margot auth login {REGISTRY}"):
            client.do_request(UPLOAD_URL, "POST")

        sleep.assert_not_called()
        assert fake.hosts == {REGISTRY}
        assert len(fake.requests) == 1

    def test_get_manifest_on_basic_registry_without_credentials_raises_authentication_error(self, mocker: Any) -> None:
        """Should fail a read (pull path) on a Basic registry with AuthenticationException, not a hang."""
        mocker.patch("oras.decorator.time.sleep")
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=False)

        with raises(AuthenticationException):
            client.get_manifest(f"{REGISTRY}/{REPO}:1.0.0")

    @mark.parametrize("scheme", ["Basic", "basic", "BASIC"])
    def test_scheme_match_is_case_insensitive(self, scheme: str) -> None:
        """Should treat the challenge scheme as Basic regardless of letter case."""
        fake = FakeRegistry(f'{scheme} realm="Authorization Required"', accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        response = client.do_request(UPLOAD_URL, "POST")

        assert response.status_code == 202
        assert fake.hosts == {REGISTRY}

    def test_after_basic_challenge_next_request_carries_basic_up_front(self) -> None:
        """Should send Basic on later requests without another 401 round trip."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        client.do_request(UPLOAD_URL, "POST")
        client.do_request(UPLOAD_URL, "POST")

        assert fake.unauthorized == 1
        assert fake.requests[-1][2] == f"Basic {BASIC_CREDS}"

    def test_403_after_basic_raises_authentication_error_without_looping(self) -> None:
        """Should stop after one retry when the registry rejects the Basic credentials with 403."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}", forbid_accepted=True)
        client = _client(fake, stored=True)

        with raises(AuthenticationException, match=rf"margot auth login {REGISTRY}"):
            client.do_request(UPLOAD_URL, "POST")

        assert len(fake.requests) == 2

    def test_rejected_credentials_return_401_then_later_request_raises_authentication_error(self) -> None:
        """Should return the 401 once after the retry, then fail fast on the next request that sends Basic up front."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth="Basic bm9wZTpub3Bl")
        client = _client(fake, stored=True)

        assert client.do_request(UPLOAD_URL, "POST").status_code == 401

        with raises(AuthenticationException, match="rejected the stored credentials"):
            client.do_request(UPLOAD_URL, "POST")

    def test_unauthorized_read_response_raises_authentication_error(self) -> None:
        """Should map a 401 that survives authentication to AuthenticationException (exit 4), not ValueError."""
        client = OrasClient()
        request = _prepared(f"https://{REGISTRY}/v2/{REPO}/manifests/1.0.0")

        with raises(AuthenticationException, match=rf"margot auth login {REGISTRY}"):
            client._check_200_response(_response(request, 401))

    def test_logout_clears_basic_mode(self) -> None:
        """Should stop sending Basic up front after the auth backend is logged out."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)
        client.do_request(UPLOAD_URL, "POST")

        client.auth._logout()

        assert client.auth.get_auth_header() == {}
        assert client.auth.token is None


class TestBearerChallenge:
    """Bearer challenges keep using oras-py's token flow."""

    def test_bearer_challenge_still_uses_token_flow(self) -> None:
        """Should request a token from the realm and retry with the Bearer header."""
        fake = FakeRegistry(BEARER_CHALLENGE, accepted_auth="Bearer tok")
        client = _client(fake, stored=True)

        response = client.do_request(UPLOAD_URL, "POST")

        assert response.status_code == 202
        assert AUTH_SERVER in fake.hosts
        assert fake.requests[-1][2] == "Bearer tok"

    def test_bearer_challenge_after_basic_switches_back_to_token_flow(self) -> None:
        """Should leave Basic mode when a later challenge is Bearer, instead of sending Basic to it."""
        fake = FakeRegistry(BEARER_CHALLENGE, accepted_auth="Bearer tok")
        client = _client(fake, stored=True)
        client.auth._basic_mode = True

        response = client.do_request(UPLOAD_URL, "POST")

        assert response.status_code == 202
        assert fake.requests[-1][2] == "Bearer tok"


class TestRegistryIntegration:
    """Push operations against a Basic-protected registry, using the real oras-py request path."""

    def test_push_margo_to_basic_registry_succeeds_with_one_unauthorized_round_trip(self, tmp_path: Any) -> None:
        """Should push a margo artifact, pay one 401 round trip, and never request the realm."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)
        margo_dir = tmp_path / "1.0.0" / "margo"
        margo_dir.mkdir(parents=True)
        (margo_dir / "app.yaml").write_text("name: demo\n", encoding="utf-8")

        client.push_margo(
            build_dir=str(tmp_path),
            version="1.0.0",
            registry=REGISTRY,
            repository=REPO,
            name="demo",
            description="demo app",
        )

        assert fake.unauthorized == 1
        assert fake.hosts == {REGISTRY}

    def test_check_write_access_probe_uses_https_url(self) -> None:
        """Should POST the write-access probe to an absolute https URL (no MissingSchema retry loop)."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        client.check_write_access(REGISTRY, REPO)

        assert fake.requests[0][:2] == ("POST", UPLOAD_URL)

    def test_check_write_access_on_basic_registry_succeeds_without_realm_request(self) -> None:
        """Should pass the write-access probe on a Basic registry with stored credentials."""
        fake = FakeRegistry(BASIC_CHALLENGE, accepted_auth=f"Basic {BASIC_CREDS}")
        client = _client(fake, stored=True)

        client.check_write_access(REGISTRY, REPO)

        assert fake.hosts == {REGISTRY}


class TestDefaultTimeout:
    """Every request made through the client session gets a default (connect, read) timeout."""

    def test_request_without_explicit_timeout_gets_default_timeout(self, mocker: Any) -> None:
        """Should pass timeout=(10, 60) to the adapter when the caller gives none."""
        send = mocker.patch.object(HTTPAdapter, "send", return_value=_response(_prepared("https://x.test/"), 200))
        client = OrasClient()

        client.session.get(f"https://{REGISTRY}/v2/")

        assert send.call_args.kwargs["timeout"] == DEFAULT_TIMEOUT

    def test_explicit_timeout_is_not_overridden(self, mocker: Any) -> None:
        """Should pass through a caller-supplied timeout unchanged."""
        send = mocker.patch.object(HTTPAdapter, "send", return_value=_response(_prepared("https://x.test/"), 200))
        client = OrasClient()

        client.session.get(f"https://{REGISTRY}/v2/", timeout=5)

        assert send.call_args.kwargs["timeout"] == 5

    def test_verify_argument_still_reaches_the_adapter(self, mocker: Any) -> None:
        """Should keep forwarding verify= so custom CA bundles keep working."""
        send = mocker.patch.object(HTTPAdapter, "send", return_value=_response(_prepared("https://x.test/"), 200))
        client = OrasClient()

        client.session.get(f"https://{REGISTRY}/v2/", verify="/etc/ssl/ca.pem")

        assert send.call_args.kwargs["verify"] == "/etc/ssl/ca.pem"

    def test_client_session_mounts_default_timeout_adapter_for_http_and_https(self) -> None:
        """Should mount the timeout adapter on both schemes."""
        client = OrasClient()

        assert isinstance(client.session.get_adapter(f"https://{REGISTRY}/"), DefaultTimeoutAdapter)
        assert isinstance(client.session.get_adapter(f"http://{REGISTRY}/"), DefaultTimeoutAdapter)

    def test_auth_backend_shares_the_client_session_and_tls_settings(self) -> None:
        """Should keep session, prefix and TLS verification identical to the stock oras-py backend."""
        client = OrasClient()

        assert isinstance(client.auth, ChallengeAwareAuth)
        assert client.auth.session is client.session
        assert client.auth.prefix == "https"
        assert client.auth._tls_verify is True
