"""Unit tests for domain/uri.py."""

from pytest import raises

from margot.domain.uri import validate_uri


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
