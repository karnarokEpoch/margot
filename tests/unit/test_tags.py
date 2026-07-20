"""Unit tests for domain/tags.py."""

from pytest import mark, raises

from margot.domain.tags import validate_oci_tag, validate_semver


class TestValidateOciTag:
    """Tests for validate_oci_tag()."""

    @mark.parametrize(
        "tag",
        [
            "1.0.0",
            "1.3.0-simple.1",
            "1.3.0_simple",
            "1.3.0_addon-mosquitto",
            "v1.0.0",
            "1.0",
            "latest",
        ],
    )
    def test_validate_oci_tag_accepts(self, tag: str) -> None:
        """Should accept all valid OCI tags without raising."""
        validate_oci_tag(tag)  # should not raise

    @mark.parametrize(
        ("tag", "match_pattern"),
        [
            ("", "OCI tag must not be empty"),
            ("my tag", "OCI tag must contain only"),
            ("tag+build", "OCI tag must contain only"),
            ("x" * 129, "OCI tag must not exceed 128 characters"),
        ],
    )
    def test_validate_oci_tag_rejects(self, tag: str, match_pattern: str) -> None:
        """Should raise ValueError for invalid OCI tags."""
        with raises(ValueError, match=match_pattern):
            validate_oci_tag(tag)

    def test_validate_oci_tag_exactly_128_chars_accepted(self) -> None:
        """Should accept a tag exactly 128 characters long."""
        tag = "a" * 128
        validate_oci_tag(tag)  # should not raise

    def test_validate_oci_tag_exactly_129_chars_rejected(self) -> None:
        """Should reject a tag exactly 129 characters long."""
        tag = "a" * 129
        with raises(ValueError, match="OCI tag must not exceed 128 characters"):
            validate_oci_tag(tag)


class TestValidateSemver:
    """Tests for validate_semver()."""

    @mark.parametrize(
        "tag",
        [
            "1.0.0",
            "1.3.0-simple.1",
            "1.3.0_simple",
            "1.3.0_addon-mosquitto",
        ],
    )
    def test_validate_semver_accepts(self, tag: str) -> None:
        """Should accept all valid SemVer tags (after normalisation) without raising."""
        validate_semver(tag)  # should not raise

    @mark.parametrize(
        ("tag", "match_pattern"),
        [
            ("v1.0.0", "is not valid SemVer"),
            ("1.0", "is not valid SemVer"),
            ("latest", "is not valid SemVer"),
        ],
    )
    def test_validate_semver_rejects(self, tag: str, match_pattern: str) -> None:
        """Should raise ValueError for invalid SemVer tags."""
        with raises(ValueError, match=match_pattern):
            validate_semver(tag)

    def test_validate_semver_normalises_underscore(self) -> None:
        """Should normalise '_' to '+' before validating SemVer."""
        # 1.3.0_simple normalises to 1.3.0+simple, which is valid SemVer
        validate_semver("1.3.0_simple")  # should not raise

    def test_validate_semver_normalises_multi_segment_variant(self) -> None:
        """Should normalise multi-segment variant tags (e.g. 1.3.0_addon-mosquitto)."""
        # 1.3.0_addon-mosquitto normalises to 1.3.0+addon-mosquitto
        validate_semver("1.3.0_addon-mosquitto")  # should not raise
