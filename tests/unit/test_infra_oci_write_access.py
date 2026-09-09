"""Unit tests for infra/oci.py check_write_access method."""

from typing import Any
from unittest.mock import MagicMock, PropertyMock

from pytest import raises

from margot.infra.oci import OciRegistryError, OrasClient


class TestCheckWriteAccess:
    """Tests for OrasClient.check_write_access()."""

    def _setup_client_mocks(self, mocker: Any) -> tuple[OrasClient, MagicMock, MagicMock]:
        """Common setup for client mocking."""
        mocker.patch("margot.infra.oci.OrasClientLib.__init__", return_value=None)

        client = OrasClient()

        # Mock auth as a property
        auth_mock = MagicMock()
        type(client).auth = PropertyMock(return_value=auth_mock)

        # Mock console
        console_mock = mocker.patch("margot.infra.oci.console")

        return client, auth_mock, console_mock

    def test_check_write_access_202_with_location_succeeds(self, mocker: Any) -> None:
        """Should succeed on 202 response with Location header."""
        client, auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        # Mock do_request to return 202 with Location header
        response_mock = MagicMock()
        response_mock.status_code = 202
        response_mock.headers = {"Location": "http://registry/v2/repo/blobs/uploads/abc123"}
        mocker.patch.object(client, "do_request", return_value=response_mock)

        # Mock _get_location to return the location URL
        mocker.patch.object(client, "_get_location", return_value="http://registry/v2/repo/blobs/uploads/abc123")

        # Should not raise
        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

        auth_mock.load_configs.assert_called_once()

    def test_check_write_access_401_raises_permission_error(self, mocker: Any) -> None:
        """Should raise PermissionError on 401 response."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        # Mock do_request to return 401
        response_mock = MagicMock()
        response_mock.status_code = 401
        response_mock.text = "Unauthorized"
        mocker.patch.object(client, "do_request", return_value=response_mock)

        with raises(PermissionError, match=r"public\.ecr\.aws.*g2n4p2m7/margo"):
            client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

    def test_check_write_access_403_raises_permission_error(self, mocker: Any) -> None:
        """Should raise PermissionError on 403 response."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        # Mock do_request to return 403
        response_mock = MagicMock()
        response_mock.status_code = 403
        response_mock.text = "Forbidden"
        mocker.patch.object(client, "do_request", return_value=response_mock)

        with raises(PermissionError, match=r"public\.ecr\.aws.*g2n4p2m7/margo"):
            client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

    def test_check_write_access_500_raises_generic_exception(self, mocker: Any) -> None:
        """Should raise OciRegistryError on unexpected status like 500."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        # Mock do_request to return 500
        response_mock = MagicMock()
        response_mock.status_code = 500
        response_mock.text = "Internal Server Error"
        mocker.patch.object(client, "do_request", return_value=response_mock)

        with raises(OciRegistryError, match="500"):
            client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

    def test_check_write_access_delete_cleanup_failure_does_not_raise(self, mocker: Any) -> None:
        """Should not raise when DELETE cleanup of upload session fails."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        # Mock do_request: returns 202 on POST
        post_response = MagicMock()
        post_response.status_code = 202
        post_response.headers = {"Location": "http://registry/v2/repo/blobs/uploads/abc123"}
        mocker.patch.object(client, "do_request", side_effect=[post_response, RuntimeError("DELETE failed")])

        # Mock _get_location to return the location URL
        mocker.patch.object(client, "_get_location", return_value="http://registry/v2/repo/blobs/uploads/abc123")

        # Should not raise despite DELETE failure
        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

    def test_check_write_access_calls_get_container(self, mocker: Any) -> None:
        """Should call get_container with probe tag."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        get_container = mocker.patch.object(client, "get_container", return_value=container_mock)

        response_mock = MagicMock()
        response_mock.status_code = 202
        response_mock.headers = {"Location": "http://registry/v2/repo/blobs/uploads/abc123"}
        mocker.patch.object(client, "do_request", return_value=response_mock)
        mocker.patch.object(client, "_get_location", return_value="http://registry/v2/repo/blobs/uploads/abc123")

        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

        # Should have called get_container with the probe tag
        get_container.assert_called_with("public.ecr.aws/g2n4p2m7/margo:probe")

    def test_check_write_access_uses_upload_blob_url(self, mocker: Any) -> None:
        """Should use container.upload_blob_url() for POST request."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        container_mock.upload_blob_url.return_value = "v2/g2n4p2m7/margo/blobs/uploads/"
        mocker.patch.object(client, "get_container", return_value=container_mock)

        response_mock = MagicMock()
        response_mock.status_code = 202
        response_mock.headers = {"Location": "http://registry/v2/repo/blobs/uploads/abc123"}
        do_request_mock = mocker.patch.object(client, "do_request", return_value=response_mock)
        mocker.patch.object(client, "_get_location", return_value="http://registry/v2/repo/blobs/uploads/abc123")

        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

        # First do_request call should be to upload_blob_url with POST
        do_request_mock.assert_called()
        first_call = do_request_mock.call_args_list[0]
        assert first_call[0][0] == "v2/g2n4p2m7/margo/blobs/uploads/"
        assert first_call[0][1] == "POST"

    def test_check_write_access_emits_debug_logs(self, mocker: Any) -> None:
        """Should emit debug logs during the probe."""
        client, _auth_mock, console_mock = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        response_mock = MagicMock()
        response_mock.status_code = 202
        response_mock.headers = {"Location": "http://registry/v2/repo/blobs/uploads/abc123"}
        mocker.patch.object(client, "do_request", return_value=response_mock)
        mocker.patch.object(client, "_get_location", return_value="http://registry/v2/repo/blobs/uploads/abc123")

        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

        # Should have called console.debug
        assert console_mock.debug.called

    def test_check_write_access_handles_200_response(self, mocker: Any) -> None:
        """Should succeed on 200 response without cleanup."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        response_mock = MagicMock()
        response_mock.status_code = 200
        mocker.patch.object(client, "do_request", return_value=response_mock)

        # Should not raise (200 is successful, no Location cleanup needed)
        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")

    def test_check_write_access_handles_201_response(self, mocker: Any) -> None:
        """Should succeed on 201 response."""
        client, _auth_mock, _ = self._setup_client_mocks(mocker)

        container_mock = MagicMock()
        mocker.patch.object(client, "get_container", return_value=container_mock)

        response_mock = MagicMock()
        response_mock.status_code = 201
        mocker.patch.object(client, "do_request", return_value=response_mock)

        # Should not raise
        client.check_write_access("public.ecr.aws", "g2n4p2m7/margo")
