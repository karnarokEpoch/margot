"""Unit tests for platform filtering in package service."""

from pytest import fixture, raises

from margot.services import package as package_service


class TestValidatePlatform:
    """Tests for _validate_platform()."""

    def test_valid_os_arch(self) -> None:
        """Should accept valid os/arch format."""
        package_service._validate_platform("linux/amd64")
        package_service._validate_platform("linux/arm64")
        package_service._validate_platform("linux/arm/v7")
        package_service._validate_platform("windows/amd64")

    def test_valid_os_arch_variant(self) -> None:
        """Should accept os/arch/variant format."""
        package_service._validate_platform("linux/arm/v7")
        package_service._validate_platform("linux/arm/v6")

    def test_invalid_format_no_slash(self) -> None:
        """Should reject platform with no slashes."""
        with raises(ValueError, match=r"Invalid platform.*must be in os/arch"):
            package_service._validate_platform("linux-amd64")

    def test_invalid_format_single_slash(self) -> None:
        """Should reject platform with single slash but no values."""
        with raises(ValueError, match=r"Invalid platform.*must be in os/arch"):
            package_service._validate_platform("/")

    def test_invalid_format_missing_os(self) -> None:
        """Should reject platform with missing os."""
        with raises(ValueError, match=r"Invalid platform.*must be in os/arch"):
            package_service._validate_platform("/amd64")

    def test_invalid_format_missing_arch(self) -> None:
        """Should reject platform with missing arch."""
        with raises(ValueError, match=r"Invalid platform.*must be in os/arch"):
            package_service._validate_platform("linux/")

    def test_invalid_format_too_many_slashes(self) -> None:
        """Should reject platform with too many slashes."""
        with raises(ValueError, match=r"Invalid platform.*must be in os/arch"):
            package_service._validate_platform("linux/amd64/extra/parts")


class TestNormalizePlatform:
    """Tests for _normalize_platform()."""

    def test_normalize_os_arch(self) -> None:
        """Should normalize os/arch format."""
        result = package_service._normalize_platform("linux/amd64")
        assert result == "linux/amd64"

    def test_normalize_os_arch_variant(self) -> None:
        """Should normalize os/arch/variant format."""
        result = package_service._normalize_platform("linux/arm/v7")
        assert result == "linux/arm/v7"

    def test_normalize_case_sensitive(self) -> None:
        """Should keep case as-is (platform is case-sensitive)."""
        result = package_service._normalize_platform("Linux/amd64")
        assert result == "Linux/amd64"


class TestFilterManifestsByPlatforms:
    """Tests for _filter_manifests_by_platforms()."""

    @fixture
    def multi_arch_index(self) -> dict:
        """Fixture: a multi-arch image index with multiple platforms."""
        return {
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "schemaVersion": 2,
            "manifests": [
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:amd64digest",
                    "size": 1000,
                    "platform": {"os": "linux", "architecture": "amd64"},
                },
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:arm64digest",
                    "size": 2000,
                    "platform": {"os": "linux", "architecture": "arm64"},
                },
                {
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "digest": "sha256:armv7digest",
                    "size": 1500,
                    "platform": {"os": "linux", "architecture": "arm", "variant": "v7"},
                },
            ],
        }

    @fixture
    def single_arch_manifest(self) -> dict:
        """Fixture: a single-arch manifest (not an index)."""
        return {
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
            "config": {"digest": "sha256:configdigest", "size": 500},
            "layers": [],
        }

    def test_no_platforms_returns_all(self, multi_arch_index: dict) -> None:
        """Should return all manifests when platforms list is empty."""
        result = package_service._filter_manifests_by_platforms(multi_arch_index, [])
        assert len(result["manifests"]) == 3

    def test_single_platform_filter(self, multi_arch_index: dict) -> None:
        """Should filter to single requested platform."""
        result = package_service._filter_manifests_by_platforms(
            multi_arch_index,
            ["linux/amd64"],
        )
        assert len(result["manifests"]) == 1
        assert result["manifests"][0]["platform"]["architecture"] == "amd64"

    def test_multiple_platform_filter(self, multi_arch_index: dict) -> None:
        """Should filter to multiple requested platforms."""
        result = package_service._filter_manifests_by_platforms(
            multi_arch_index,
            ["linux/amd64", "linux/arm64"],
        )
        assert len(result["manifests"]) == 2
        archs = {m["platform"]["architecture"] for m in result["manifests"]}
        assert archs == {"amd64", "arm64"}

    def test_platform_with_variant_filter(self, multi_arch_index: dict) -> None:
        """Should filter platforms with variant."""
        result = package_service._filter_manifests_by_platforms(
            multi_arch_index,
            ["linux/arm/v7"],
        )
        assert len(result["manifests"]) == 1
        assert result["manifests"][0]["platform"]["architecture"] == "arm"
        assert result["manifests"][0]["platform"]["variant"] == "v7"

    def test_requested_platform_absent_raises(self, multi_arch_index: dict) -> None:
        """Should raise clear error if requested platform not in index."""
        with raises(ValueError, match=r"Requested platform.*not found") as exc_info:
            package_service._filter_manifests_by_platforms(
                multi_arch_index,
                ["linux/ppc64le"],
            )
        error_msg = str(exc_info.value)
        assert "linux/ppc64le" in error_msg
        assert "linux/amd64" in error_msg
        assert "linux/arm64" in error_msg
        assert "linux/arm/v7" in error_msg

    def test_single_arch_manifest_with_non_matching_platform_raises(
        self,
        single_arch_manifest: dict,
    ) -> None:
        """Should raise error for single-arch manifest with non-matching --platform."""
        with raises(ValueError, match=r"Single-platform.*does not support.*--platform"):
            package_service._filter_manifests_by_platforms(
                single_arch_manifest,
                ["linux/arm64"],
            )

    def test_single_arch_manifest_no_platform_filter_returns_unchanged(
        self,
        single_arch_manifest: dict,
    ) -> None:
        """Should return single-arch manifest unchanged when no platform filter."""
        result = package_service._filter_manifests_by_platforms(
            single_arch_manifest,
            [],
        )
        assert result == single_arch_manifest

    def test_index_platform_missing_optional_variant_matches_os_arch(
        self,
        multi_arch_index: dict,
    ) -> None:
        """Should match manifest without variant when requesting os/arch/variant."""
        # Remove variant from arm64 manifest to make it os/arch only
        multi_arch_index["manifests"][1]["platform"].pop("variant", None)

        result = package_service._filter_manifests_by_platforms(
            multi_arch_index,
            ["linux/arm64"],
        )
        assert len(result["manifests"]) == 1
        assert result["manifests"][0]["platform"]["architecture"] == "arm64"
        assert "variant" not in result["manifests"][0]["platform"]


class TestPlatformAndNoImagesMutualExclusion:
    """Tests for platform + no-images mutual exclusion validation."""

    def test_platform_with_no_images_should_raise(self) -> None:
        """Should raise clear error when --platform and --no-images both set."""
        with raises(ValueError, match=r"--platform.*--no-images.*mutually"):
            package_service._validate_platform_no_images_exclusion(
                platforms=["linux/amd64"],
                no_images=True,
            )

    def test_platform_without_no_images_allowed(self) -> None:
        """Should allow --platform when --no-images is False."""
        package_service._validate_platform_no_images_exclusion(
            platforms=["linux/amd64"],
            no_images=False,
        )

    def test_no_images_without_platform_allowed(self) -> None:
        """Should allow --no-images when platforms is empty."""
        package_service._validate_platform_no_images_exclusion(
            platforms=[],
            no_images=True,
        )

    def test_no_images_no_platform_allowed(self) -> None:
        """Should allow when both are default."""
        package_service._validate_platform_no_images_exclusion(
            platforms=[],
            no_images=False,
        )
