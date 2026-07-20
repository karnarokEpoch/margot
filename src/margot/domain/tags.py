"""OCI tag and SemVer validation: pure functions, no I/O."""

from re import fullmatch

from semver import Version

# OCI Distribution Spec: max tag length is 128 characters
_MAX_OCI_TAG_LENGTH = 128


def validate_oci_tag(tag: str) -> None:
    """Raise ValueError if tag is empty, contains invalid OCI characters, or exceeds 128 chars.

    Valid OCI tag characters per OCI Distribution Spec: [a-zA-Z0-9_.-]
    Maximum length: 128 characters.

    Args:
        tag: OCI tag string to validate.

    Raises:
        ValueError: If tag is empty.
        ValueError: If tag contains characters outside [a-zA-Z0-9_.-].
        ValueError: If tag exceeds 128 characters.
    """
    if not tag:
        raise ValueError("OCI tag must not be empty")

    if len(tag) > _MAX_OCI_TAG_LENGTH:
        raise ValueError("OCI tag must not exceed 128 characters")

    # Match valid OCI characters: [a-zA-Z0-9_.-]
    if not fullmatch(r"[a-zA-Z0-9_.\-]+", tag):
        raise ValueError("OCI tag must contain only alphanumeric characters, underscores, dots, or dashes")


def validate_semver(tag: str) -> None:
    """Raise ValueError if tag is not valid SemVer after normalisation.

    Normalises '_' to '+' before parsing (Margo OCI spec: '_' encodes '+' in tags).
    Uses python-semver for validation (semver.org 2.0.0 spec).

    Args:
        tag: Tag string to validate (may contain '_' for variant/build metadata).

    Raises:
        ValueError: If the normalised tag is not valid SemVer.

    Note:
        Does NOT validate OCI characters or length — caller must use validate_oci_tag first.
    """
    normalised = tag.replace("_", "+")
    if not Version.is_valid(normalised):
        raise ValueError(f"'{tag}' is not valid SemVer")
