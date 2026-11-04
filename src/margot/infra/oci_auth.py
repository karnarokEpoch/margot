"""Scheme-aware oras-py auth backend and default HTTP timeouts for OrasClient.

oras-py's TokenAuth assumes every 401 challenge is Bearer. For a Basic challenge (RFC 7617)
it parses the realm as a token URL and sends an un-timeouted request to it, so a registry
with htpasswd auth (for example zot) hangs. This module answers Basic challenges with the
stored credentials, and leaves every other scheme to oras-py's token flow.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from oras.auth import AuthenticationException
from oras.auth.token import TokenAuth
from requests import PreparedRequest, Response, Session
from requests.adapters import HTTPAdapter

from margot import console

_CONNECT_TIMEOUT_S = 10
_READ_TIMEOUT_S = 60
DEFAULT_TIMEOUT = (_CONNECT_TIMEOUT_S, _READ_TIMEOUT_S)

_BASIC_SCHEME = "basic"
# Stored in TokenAuth.token while Basic is in use. oras-py's Registry.do_request attaches
# get_auth_header() only when token is not None, so a non-None marker makes every later request
# carry the Basic header up front. The marker itself is never sent: get_auth_header() ignores it.
_BASIC_MODE_MARKER = "basic"


class DefaultTimeoutAdapter(HTTPAdapter):
    """HTTPAdapter that applies DEFAULT_TIMEOUT when the caller passes no timeout."""

    def send(  # noqa: PLR0913
        self,
        request: PreparedRequest,
        stream: bool = False,
        timeout: float | tuple[float, float] | None = None,
        verify: bool | str = True,
        cert: str | tuple[str, str] | None = None,
        proxies: Mapping[str, str] | None = None,
    ) -> Response:
        """Send the request, substituting DEFAULT_TIMEOUT for an unset timeout."""
        if timeout is None:
            timeout = DEFAULT_TIMEOUT
        return super().send(request, stream=stream, timeout=timeout, verify=verify, cert=cert, proxies=proxies)


def mount_default_timeouts(session: Session) -> None:
    """Mount DefaultTimeoutAdapter on both URL schemes of a requests session."""
    adapter = DefaultTimeoutAdapter()
    session.mount("https://", adapter)
    session.mount("http://", adapter)


class ChallengeAwareAuth(TokenAuth):
    """oras-py token backend that answers Basic challenges with stored Basic credentials.

    The override signatures match TokenAuth exactly (Liskov): oras-py calls these methods
    from inside its own request loop, so narrowing them would break the base class.
    """

    def __init__(self) -> None:
        super().__init__()
        self._basic_mode = False

    def authenticate_request(self, original: Response, headers: dict, refresh: bool = False) -> tuple[dict, bool]:
        """Answer a 401/403 challenge according to its scheme.

        Basic challenges (and bare 401/403 responses while Basic is already in use) are answered
        here. Any other scheme is delegated to TokenAuth, which runs the Bearer token flow.
        """
        headers = headers or {}
        scheme = _challenge_scheme(original)
        if scheme == _BASIC_SCHEME or (self._basic_mode and scheme == ""):
            return self._answer_basic_challenge(original, headers, refresh=refresh)
        if self._basic_mode:
            # The registry now asks for another scheme, so Basic no longer applies.
            self._leave_basic_mode()
        return super().authenticate_request(original, headers, refresh=refresh)

    def get_auth_header(self) -> dict[str, str]:
        """Return the Basic header while in Basic mode, otherwise the TokenAuth header."""
        if self._basic_mode:
            return {"Authorization": f"Basic {getattr(self, '_basic_auth', '')}"}
        return super().get_auth_header()

    def _logout(self) -> None:
        """Forget Basic mode together with the token state."""
        self._basic_mode = False
        super()._logout()

    def _answer_basic_challenge(self, original: Response, headers: dict, *, refresh: bool) -> tuple[dict, bool]:
        """Send stored Basic credentials, or fail fast when they are missing or rejected."""
        host = _host_of(original)
        basic = getattr(self, "_basic_auth", None)
        if not basic:
            console.debug(f"{host} sent a Basic challenge and no credentials are stored.")
            raise AuthenticationException(f"Registry {host} requires authentication. Run `margot auth login {host}`.")
        if self._basic_mode or refresh:
            # Basic was already sent for this request, so the registry rejected the credentials.
            console.debug(f"{host} rejected the Basic credentials.")
            raise AuthenticationException(
                f"Registry {host} rejected the stored credentials. Run `margot auth login {host}` to replace them."
            )
        console.debug(f"{host} sent a Basic challenge; answering with stored credentials.")
        self._basic_mode = True
        self.token = _BASIC_MODE_MARKER
        headers["Authorization"] = f"Basic {basic}"
        return headers, True

    def _leave_basic_mode(self) -> None:
        """Return to the token flow."""
        self._basic_mode = False
        self.token = None


def challenge_aware_from(backend: TokenAuth) -> ChallengeAwareAuth:
    """Build a ChallengeAwareAuth that shares the session and TLS settings of an oras-py backend."""
    auth = ChallengeAwareAuth()
    auth.session = backend.session
    auth.prefix = backend.prefix
    auth._tls_verify = backend._tls_verify  # noqa: SLF001
    return auth


def access_denied(response: Response) -> AuthenticationException:
    """Build the exit-4 error for a 401/403 that survived authentication."""
    host = _host_of(response)
    return AuthenticationException(
        f"Registry {host} denied the request (HTTP {response.status_code}). Run `margot auth login {host}` to check "
        "the stored credentials."
    )


def _challenge_scheme(response: Response) -> str:
    """Return the lowercased auth scheme of the first challenge, or '' when there is none."""
    parts = response.headers.get("Www-Authenticate", "").split(maxsplit=1)
    return parts[0].lower() if parts else ""


def _host_of(response: Response) -> str:
    """Return the registry host (with port, if any) that produced a response."""
    return urlsplit(response.url or "").netloc or "registry"
