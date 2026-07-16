"""URI validation helpers: pure functions, no I/O."""

import re

_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)

# Old artifact-type suffix patterns are rejected even though they are technically
# valid SemVer, because artifact type must be encoded in artifactType, not the tag.
_ARTIFACT_SUFFIX_RE = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+-(margo-manifest|compose|quadlet)$"
)


def validate_uri(uri: str) -> None:
    """Raise ValueError if uri is empty or missing a tag separator with a non-empty tag.

    Args:
        uri: OCI reference string to validate.

    Raises:
        ValueError: If uri is empty.
        ValueError: If uri has no ':' separator or the tag after ':' is empty.
    """
    if not uri:
        raise ValueError("URI must not be empty")
    tag_sep = uri.rfind(":")
    if tag_sep == -1 or not uri[tag_sep + 1 :]:
        raise ValueError("URI must contain a tag separated by ':' (e.g. registry/repo:tag)")


def extract_tag(uri: str) -> str:
    """
    Extract the tag portion from an OCI URI.

    Assumes the URI has already been validated by validate_uri().
    Returns everything after the last ':'.

    Args:
        uri: A validated OCI reference string.

    Returns:
        The tag string (e.g. '1.0.0', 'latest', '1.3.0-simple.1').
    """
    return uri[uri.rfind(":") + 1 :]


def validate_semver_tag(tag: str) -> bool:
    """
    Return True if tag is a valid SemVer string, False otherwise.

    Uses the canonical semver.org regex (2.0.0). Accepts pre-release
    and build metadata (e.g. '1.3.0-simple.1', '1.3.0+build.42').

    Old artifact-type suffix patterns (e.g. '1.0.0-margo-manifest',
    '1.0.0-compose', '1.0.0-quadlet') are explicitly rejected even though
    they are technically valid SemVer. Artifact type must be encoded in
    the OCI artifactType field, not in the tag.

    Args:
        tag: The tag string to validate.

    Returns:
        True if valid SemVer, False otherwise.
    """
    if not _SEMVER_RE.match(tag):
        return False
    if _ARTIFACT_SUFFIX_RE.match(tag):
        return False
    return True
