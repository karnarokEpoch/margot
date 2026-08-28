"""Unit tests for domain/uri.py."""

from pytest import raises

from margot.domain.uri import extract_hostname, extract_tag, strip_scheme, validate_semver_tag, validate_uri


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

    def test_oci_prefixed_uri_is_valid(self) -> None:
        """Should validate correctly when oci:// scheme is present."""
        validate_uri("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0")

    def test_oci_uppercase_prefixed_uri_is_valid(self) -> None:
        """Should validate correctly when OCI:// (uppercase) scheme is present."""
        validate_uri("OCI://public.ecr.aws/g2n4p2m7/margo:1.0.0")


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

    def test_extracts_tag_with_oci_scheme(self) -> None:
        """Should extract tag correctly even when oci:// scheme is present."""
        assert extract_tag("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0") == "1.0.0"


class TestExtractHostname:
    """Tests for extract_hostname()."""

    def test_extracts_hostname_from_full_uri(self) -> None:
        """Should return everything before the first '/' in a standard URI."""
        assert extract_hostname("public.ecr.aws/g2n4p2m7/margo:1.0.0") == "public.ecr.aws"

    def test_extracts_hostname_with_port(self) -> None:
        """Should return the hostname including a port number."""
        assert extract_hostname("localhost:5000/myapp:1.0.0") == "localhost:5000"

    def test_extracts_simple_hostname(self) -> None:
        """Should return the hostname from a simple registry/repo:tag URI."""
        assert extract_hostname("reg/repo:latest") == "reg"

    def test_empty_string_raises(self) -> None:
        """Should raise ValueError with 'URI must not be empty' for empty string."""
        with raises(ValueError, match="URI must not be empty"):
            extract_hostname("")

    def test_no_slash_separator_raises(self) -> None:
        """Should raise ValueError when URI has no '/' separator."""
        with raises(ValueError, match="URI must contain a hostname"):
            extract_hostname("no-slash:1.0.0")

    def test_leading_slash_raises(self) -> None:
        """Should raise ValueError when URI starts with '/' (empty hostname)."""
        with raises(ValueError, match="URI must contain a hostname"):
            extract_hostname("/repo:1.0.0")

    def test_extracts_hostname_with_oci_scheme(self) -> None:
        """Should extract hostname correctly even when oci:// scheme is present."""
        assert extract_hostname("oci://public.ecr.aws/g2n4p2m7/margo:1.0.0") == "public.ecr.aws"


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


class TestStripScheme:
    """Tests for strip_scheme()."""

    def test_strips_oci_lowercase_scheme(self) -> None:
        """Should strip 'oci://' prefix (lowercase)."""
        assert strip_scheme("oci://public.ecr.aws/org/repo:tag") == "public.ecr.aws/org/repo:tag"

    def test_strips_oci_uppercase_scheme(self) -> None:
        """Should strip 'OCI://' prefix (uppercase)."""
        assert strip_scheme("OCI://public.ecr.aws/org/repo:tag") == "public.ecr.aws/org/repo:tag"

    def test_strips_oci_mixed_case_scheme(self) -> None:
        """Should strip 'Oci://' prefix (mixed case)."""
        assert strip_scheme("Oci://public.ecr.aws/org/repo:tag") == "public.ecr.aws/org/repo:tag"

    def test_no_scheme_unchanged(self) -> None:
        """Should return URI unchanged when no scheme is present."""
        assert strip_scheme("public.ecr.aws/org/repo:tag") == "public.ecr.aws/org/repo:tag"

    def test_different_scheme_unchanged(self) -> None:
        """Should return URI unchanged when a different scheme is present."""
        assert strip_scheme("http://public.ecr.aws/org/repo:tag") == "http://public.ecr.aws/org/repo:tag"

    def test_empty_string_unchanged(self) -> None:
        """Should return empty string unchanged."""
        assert strip_scheme("") == ""

    def test_only_scheme_returns_empty(self) -> None:
        """Should return empty string when only 'oci://' is provided."""
        assert strip_scheme("oci://") == ""
