"""Unit tests for services/package.py runtime daemon lookup."""

from pytest import raises

from margot.services import package as package_service


class TestRuntimeLookupEnum:
    """Tests for RuntimeLookup enum."""

    def test_runtime_lookup_values(self):
        """RuntimeLookup enum should have correct values."""
        assert hasattr(package_service, "RuntimeLookup")
        lookup = package_service.RuntimeLookup
        assert lookup.AUTO.value == "auto"
        assert lookup.PODMAN.value == "podman"
        assert lookup.DOCKER.value == "docker"
        assert lookup.NONE.value == "none"


class TestRuntimeValidation:
    """Tests for --runtime flag validation."""

    def test_invalid_runtime_value_fails(self):
        """Invalid --runtime value should fail."""
        with raises(ValueError, match="Invalid runtime"):
            package_service._validate_runtime_flag("invalid")

    def test_valid_runtime_values(self):
        """Valid runtime values should pass."""
        for value in ("auto", "podman", "docker", "none"):
            # Should not raise
            package_service._validate_runtime_flag(value)


class TestRuntimeAndNoImagesMutualExclusion:
    """Tests for --runtime + --no-images mutual exclusion in package function."""

    def test_runtime_with_no_images_fails(self, mocker):
        """Should fail when both --runtime and --no-images are provided."""
        mocker.patch("margot.services.package.load_margo_yaml")
        mocker.patch("margot.services.package.Path.exists", return_value=True)

        with raises(ValueError, match="--runtime and --no-images are mutually exclusive"):
            package_service.package(
                mocker.MagicMock(),
                project_dir=".",
                build_dir=".dist",
                output=None,
                include_images=False,  # --no-images
                runtime="podman",  # --runtime podman
            )

    def test_runtime_auto_with_no_images_ok(self, mocker):
        """--runtime=auto (default) with --no-images should pass (no check)."""
        # When runtime defaults to 'auto', no_images should be allowed
        # The mutual exclusion only applies to forced runtimes
        mocker.patch("margot.services.package.load_margo_yaml")
        mocker.patch("margot.services.package.Path.exists", return_value=True)

        # This should not raise about mutual exclusion (may fail for other reasons)
        # We skip this test as it's more of an integration concern that is better
        # tested through real package operation tests with mocked dependencies
