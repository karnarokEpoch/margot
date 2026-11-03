"""Unit tests for OrasClient handling of non-2xx registry responses."""

from io import BytesIO
from pathlib import Path
from re import escape
from typing import Any

from pytest import fixture, mark, raises
from requests import Request, Response
from requests.exceptions import RequestException

from margot.infra.oci import OciRegistryError, OrasClient

REGISTRY_HOST = "public.ecr.aws"
MANIFEST_URL = f"https://{REGISTRY_HOST}/v2/g2n4p2m7/margo/manifests/1.0.0"
MANIFEST_REF = f"{REGISTRY_HOST}/g2n4p2m7/margo:1.0.0"
BLOB_DIGEST = "sha256:" + "a" * 64
AUTH_HEADER_VALUE = "Bearer s3cr3t-token"


def _response(status: int, reason: str | None, url: str = MANIFEST_URL, body: bytes = b"") -> Response:
    """Build a real requests.Response for a registry reply to a GET request."""
    response = Response()
    response.status_code = status
    response.reason = reason
    response.url = url
    response._content = body
    response.raw = BytesIO(body)  # oras-py uses the response as a context manager, which closes raw
    response.request = Request("GET", url, headers={"Authorization": AUTH_HEADER_VALUE}).prepare()
    return response


@fixture
def client(mocker: Any) -> OrasClient:
    """Real OrasClient (anonymous) with the auth backend neutralised."""
    instance = OrasClient()
    mocker.patch.object(instance, "auth")
    return instance


class TestCheckResponseNonSuccess:
    """Non-2xx registry replies must raise OciRegistryError, not a bare ValueError."""

    @mark.parametrize(
        ("status", "reason"),
        [
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (404, "Not Found"),
            (429, "Too Many Requests"),
            (500, "Internal Server Error"),
            (503, "Service Unavailable"),
        ],
    )
    def test_non_2xx_raises_registry_error_with_status_and_url(self, client: OrasClient, status: int, reason: str) -> None:
        """Should raise OciRegistryError naming the status, reason, method and URL."""
        response = _response(status, reason)

        with raises(OciRegistryError, match=escape(f"Registry returned {status} {reason} for GET {MANIFEST_URL}")):
            client._check_200_response(response)

    @mark.parametrize("status", [200, 201, 202])
    def test_success_statuses_do_not_raise(self, client: OrasClient, status: int) -> None:
        """Should accept 200, 201 and 202 without raising."""
        client._check_200_response(_response(status, "OK"))

    def test_message_without_reason_still_names_status(self, client: OrasClient) -> None:
        """Should report the status code when the response carries no reason phrase."""
        with raises(OciRegistryError, match=escape(f"Registry returned 429 for GET {MANIFEST_URL}")):
            client._check_200_response(_response(429, None))

    def test_message_omits_headers_and_query_string(self, client: OrasClient) -> None:
        """Should never leak Authorization values or URL query parameters into the message."""
        url = f"{MANIFEST_URL}?_state=upload-token&access_token=leaked"
        with raises(OciRegistryError) as exc_info:
            client._check_200_response(_response(503, "Service Unavailable", url=url))

        message = str(exc_info.value)
        assert "s3cr3t-token" not in message
        assert "Authorization" not in message
        assert "leaked" not in message
        assert "_state" not in message
        assert f"Registry returned 503 Service Unavailable for GET {MANIFEST_URL}" == message

    def test_message_omits_userinfo_in_url(self, client: OrasClient) -> None:
        """Should drop user:password credentials embedded in the URL authority."""
        url = f"https://robot:hunter2@{REGISTRY_HOST}/v2/g2n4p2m7/margo/manifests/1.0.0"
        with raises(OciRegistryError) as exc_info:
            client._check_200_response(_response(429, "Too Many Requests", url=url))

        message = str(exc_info.value)
        assert "hunter2" not in message
        assert "robot" not in message
        assert f"{REGISTRY_HOST}/v2/g2n4p2m7/margo/manifests/1.0.0" in message


class TestManifestFetchNonSuccess:
    """Manifest GETs through the real oras-py path must surface registry HTTP failures as OciRegistryError."""

    @mark.parametrize(("status", "reason"), [(429, "Too Many Requests"), (503, "Service Unavailable"), (404, "Not Found")])
    def test_get_manifest_non_2xx_raises_registry_error(self, client: OrasClient, mocker: Any, status: int, reason: str) -> None:
        """Should raise OciRegistryError when the registry answers the manifest GET with a non-2xx status."""
        mocker.patch.object(client.session, "request", return_value=_response(status, reason))

        with raises(OciRegistryError, match=escape(f"Registry returned {status} {reason}")):
            client.get_manifest(MANIFEST_REF)

    def test_pull_manifest_non_2xx_raises_registry_error(self, client: OrasClient, mocker: Any, tmp_path: Path) -> None:
        """Should raise OciRegistryError when oras-py's own pull() dispatches its manifest GET back into the override."""
        mocker.patch.object(client.session, "request", return_value=_response(429, "Too Many Requests"))

        with raises(OciRegistryError, match="429 Too Many Requests"):
            client.pull(MANIFEST_REF, str(tmp_path))


class TestBlobFetchNonSuccess:
    """Blob GETs already raise requests.HTTPError from oras-py; that must stay a RequestException (exit 4)."""

    def test_download_blob_429_raises_request_exception(self, client: OrasClient, mocker: Any, tmp_path: Path) -> None:
        """Should raise a RequestException subclass when a blob GET returns 429."""
        mocker.patch.object(
            client.session,
            "request",
            return_value=_response(
                429, "Too Many Requests", url=f"https://{REGISTRY_HOST}/v2/g2n4p2m7/margo/blobs/{BLOB_DIGEST}"
            ),
        )

        with raises(RequestException):
            client.download_blob(MANIFEST_REF, BLOB_DIGEST, str(tmp_path / "blob"))


class TestPushUploadNonSuccess:
    """Upload failures on push paths use the same registry error type."""

    def test_push_compose_upload_429_raises_registry_error(self, client: OrasClient, mocker: Any, tmp_path: Path) -> None:
        """Should raise OciRegistryError when a layer upload is rate limited."""
        archive = tmp_path / "app.tgz"
        archive.write_bytes(b"fake archive")
        mocker.patch.object(client, "upload_blob", return_value=_response(429, "Too Many Requests"))

        with raises(OciRegistryError, match="429 Too Many Requests"):
            client.push_compose(str(archive), "1.0.0", REGISTRY_HOST, "g2n4p2m7/margo", "app", "desc")

    def test_push_manifest_503_raises_registry_error(self, client: OrasClient, mocker: Any, tmp_path: Path) -> None:
        """Should raise OciRegistryError when the manifest PUT fails with 503."""
        archive = tmp_path / "app.tgz"
        archive.write_bytes(b"fake archive")
        upload_ok = _response(201, "Created", url=f"https://{REGISTRY_HOST}/v2/g2n4p2m7/margo/blobs/uploads/x")
        mocker.patch.object(client, "upload_blob", return_value=upload_ok)
        mocker.patch.object(client, "upload_manifest", return_value=_response(503, "Service Unavailable"))

        with raises(OciRegistryError, match="503 Service Unavailable"):
            client.push_compose(str(archive), "1.0.0", REGISTRY_HOST, "g2n4p2m7/margo", "app", "desc")
