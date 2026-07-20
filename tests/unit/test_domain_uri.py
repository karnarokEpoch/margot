"""Unit tests for domain/uri.py."""

from pytest import raises

from margot.domain.uri import extract_tag, validate_semver_tag, validate_uri


class TestValidateUri:
    """Tests for validate_uri()."""

    def test_empty_string_raises(self) -> None:
        """Should raise ValueError with 'URI must not be empty' for empty string."""
        with raises(ValueError, match="URI must not be empty"):
            validate_uri("")

    def test_no_tag_separator_raises(self) -> None:
        """Should raise ValueError when URI has no colon."""
        with raises(ValueError, match="URI must contain a tag"):
            validate_uri("no-tag")

    def test_empty_tag_after_colon_raises(self) -> None:
        """Should raise ValueError when tag after colon is empty."""
        with raises(ValueError, match="URI must contain a tag"):
            validate_uri("reg/repo:")

    def test_valid_full_uri_does_not_raise(self) -> None:
        """Should not raise for a well-formed OCI URI."""
        validate_uri("public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_valid_simple_uri_does_not_raise(self) -> None:
        """Should not raise for a simple registry/repo:tag URI."""
        validate_uri("reg/repo:latest")


class TestExtractTag:
    """Tests for extract_tag()."""

    def test_extracts_semver_tag(self) -> None:
        """Should return the semver tag from a full OCI URI."""
        assert extract_tag("public.ecr.aws/g2n4p2m7/margo:1.0.0") == "1.0.0"

    def test_extracts_latest_tag(self) -> None:
        """Should return 'latest' from a simple registry/repo:latest URI."""
        assert extract_tag("reg/repo:latest") == "latest"

    def test_extracts_prerelease_tag(self) -> None:
        """Should return the pre-release tag including hyphen and dot separators."""
        assert extract_tag("reg/repo:1.3.0-simple.1") == "1.3.0-simple.1"


class TestValidateSemverTag:
    """Tests for validate_semver_tag()."""

    def test_basic_semver_is_valid(self) -> None:
        """Should accept a basic X.Y.Z semver string."""
        assert validate_semver_tag("1.0.0") is True

    def test_prerelease_is_valid(self) -> None:
        """Should accept a pre-release semver string with dot-separated identifiers."""
        assert validate_semver_tag("1.3.0-simple.1") is True

    def test_build_metadata_is_valid(self) -> None:
        """Should accept a semver string with build metadata."""
        assert validate_semver_tag("1.3.0+build.42") is True

    def test_prerelease_and_build_metadata_is_valid(self) -> None:
        """Should accept a semver string with both pre-release and build metadata."""
        assert validate_semver_tag("1.3.0-alpha.1+build.42") is True

    def test_latest_is_invalid(self) -> None:
        """Should reject 'latest' as not a semver string."""
        assert validate_semver_tag("latest") is False

    def test_legacy_margo_manifest_suffix_is_valid(self) -> None:
        """Should accept legacy margo-manifest suffix — it is valid SemVer pre-release."""
        assert validate_semver_tag("1.0.0-margo-manifest") is True

    def test_legacy_compose_suffix_is_valid(self) -> None:
        """Should accept legacy compose suffix — it is valid SemVer pre-release."""
        assert validate_semver_tag("1.0.0-compose") is True

    def test_legacy_quadlet_suffix_is_valid(self) -> None:
        """Should accept legacy quadlet suffix — it is valid SemVer pre-release."""
        assert validate_semver_tag("1.0.0-quadlet") is True

    def test_empty_string_is_invalid(self) -> None:
        """Should reject empty string."""
        assert validate_semver_tag("") is False

    def test_missing_patch_is_invalid(self) -> None:
        """Should reject '1.0' (missing patch component)."""
        assert validate_semver_tag("1.0") is False

    def test_v_prefix_is_invalid(self) -> None:
        """Should reject 'v1.0.0' (v-prefix is not canonical SemVer)."""
        assert validate_semver_tag("v1.0.0") is False
