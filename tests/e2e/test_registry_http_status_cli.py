"""E2E tests: registry HTTP failures on remote reads exit 4, not 3.

The real OrasClient runs; only the HTTP session is faked, routed by URL, so the
manifest and blob paths behave like a registry that answers with an error status.
"""

from collections.abc import Callable
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any

from pytest import MonkeyPatch, fixture, mark
from requests import Request, Response
from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()

REF = "public.ecr.aws/g2n4p2m7/margo:1.0.0"
MANIFEST_PATH = "/v2/g2n4p2m7/margo/manifests/1.0.0"
BLOB_DIGEST = "sha256:" + "b" * 64
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

Route = Callable[[str], Response]


def _plain(result: Any) -> str:
    """Strip ANSI styling and collapse wrapped lines so assertions see one run of text."""
    text = _ANSI.sub("", result.stdout + (result.stderr or ""))
    return " ".join(text.split())


def _response(status: int, reason: str | None, url: str, body: bytes = b"") -> Response:
    """Build a real requests.Response as the registry would send it."""
    response = Response()
    response.status_code = status
    response.reason = reason
    response.url = url
    # requests exposes no public setter for a response body; oras-py reads it through the normal API.
    response._content = body  # noqa: SLF001
    response.raw = BytesIO(body)  # oras-py uses the response as a context manager, which closes raw
    response.request = Request("GET", url).prepare()
    return response


def _manifest_body() -> bytes:
    """Return a minimal Margo manifest whose descriptor layer uses the blob route."""
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.margo.app.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
        },
        "layers": [
            {
                "mediaType": "application/vnd.margo.app.description.v1+yaml",
                "digest": BLOB_DIGEST,
                "size": 10,
                "annotations": {"org.opencontainers.image.title": "app.yaml"},
            }
        ],
    }
    return json.dumps(manifest).encode()


@fixture
def registry(mocker: Any, monkeypatch: MonkeyPatch, tmp_path: Path) -> Callable[[Route], None]:
    """Route every HTTP request made by requests.Session through the given responder.

    Credentials and the Docker config are isolated under tmp_path so the host's
    login state cannot change the outcome.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    mocker.patch("margot.services.pull.credentials.check_credentials")

    def install(route: Route) -> None:
        def route_request(_method: str, url: str, **_kwargs: Any) -> Response:
            return route(url)

        mocker.patch("requests.Session.request", side_effect=route_request)

    return install


def _manifest_fails(status: int, reason: str) -> Route:
    """Responder: the manifest GET fails with the given status."""

    def route(url: str) -> Response:
        return _response(status, reason, url)

    return route


class TestDescribeRegistryHttpFailures:
    """margot describe <uri> maps registry HTTP failures to exit 4."""

    @mark.parametrize(
        ("status", "reason"),
        [(429, "Too Many Requests"), (503, "Service Unavailable"), (404, "Not Found")],
    )
    def test_describe_registry_http_failure_exits_4(self, registry: Callable[[Route], None], status: int, reason: str) -> None:
        """Should exit 4 and name the status when the registry rejects the manifest GET."""
        registry(_manifest_fails(status, reason))

        result = runner.invoke(app, ["describe", REF])
        plain = _plain(result)

        assert result.exit_code == 4, plain
        assert f"Registry returned {status} {reason}" in plain
        assert "ValueError" not in plain


class TestVerifyRegistryHttpFailures:
    """margot verify <uri> maps registry HTTP failures to exit 4."""

    @mark.parametrize(
        ("status", "reason"),
        [(429, "Too Many Requests"), (503, "Service Unavailable"), (404, "Not Found")],
    )
    def test_verify_registry_http_failure_exits_4(self, registry: Callable[[Route], None], status: int, reason: str) -> None:
        """Should exit 4 and name the status when the registry rejects the manifest GET."""
        registry(_manifest_fails(status, reason))

        result = runner.invoke(app, ["verify", REF])
        plain = _plain(result)

        assert result.exit_code == 4, plain
        assert f"Registry returned {status} {reason}" in plain


class TestPullRegistryHttpFailures:
    """margot pull <uri> maps registry HTTP failures to exit 4 on both manifest and blob GETs."""

    @mark.parametrize(
        ("status", "reason"),
        [(429, "Too Many Requests"), (503, "Service Unavailable"), (404, "Not Found")],
    )
    def test_pull_manifest_http_failure_exits_4(self, registry: Callable[[Route], None], status: int, reason: str) -> None:
        """Should exit 4 and name the status when the manifest GET fails."""
        registry(_manifest_fails(status, reason))

        result = runner.invoke(app, ["pull", REF])
        plain = _plain(result)

        assert result.exit_code == 4, plain
        assert f"Registry returned {status} {reason}" in plain

    def test_pull_blob_rate_limited_exits_4(self, registry: Callable[[Route], None]) -> None:
        """Should exit 4 when the manifest is served but the blob GET is rate limited with 429."""

        def route(url: str) -> Response:
            if MANIFEST_PATH in url:
                return _response(200, "OK", url, _manifest_body())
            return _response(429, "Too Many Requests", url)

        registry(route)

        result = runner.invoke(app, ["pull", REF])

        assert result.exit_code == 4, _plain(result)
