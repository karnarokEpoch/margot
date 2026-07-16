"""URI validation helpers: pure functions, no I/O."""


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
