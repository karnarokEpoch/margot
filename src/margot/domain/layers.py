"""Layer selection and filename resolution: pure functions, no I/O."""

from typing import Any

COMPOSE_LAYER_MEDIA_TYPE = "application/vnd.org.margo.component.compose.tar+gzip"
QUADLET_LAYER_MEDIA_TYPE = "application/vnd.org.margo.component.quadlet.tar+gzip"

_OCI_TITLE = "org.opencontainers.image.title"
_OCI_VERSION = "org.opencontainers.image.version"


def select_payload_layer(
    layers: list[dict[str, Any]],
    media_type: str,
) -> dict[str, Any] | None:
    """Return the first layer whose mediaType matches `media_type`, or None.

    Args:
        layers: List of OCI manifest layer descriptors.
        media_type: The mediaType string to match against.

    Returns:
        The first matching layer dict, or None if no layer matches.
    """
    for layer in layers:
        if layer.get("mediaType") == media_type:
            return layer
    return None


def sanitize_filename(name: str) -> str | None:
    """
    Sanitize a candidate filename from an untrusted OCI annotation.

    Returns the stripped name if safe, or None if the name is rejected.

    Rejected if:
    - Contains a '/' or '\\' (path traversal)
    - Contains a null byte
    - Is exactly '.' or '..'
    - Is empty after stripping whitespace

    Args:
        name: Candidate filename string from an OCI annotation.

    Returns:
        Stripped filename string if safe, None otherwise.
    """
    stripped = name.strip()
    if not stripped:
        return None
    if "/" in stripped or "\\" in stripped:
        return None
    if "\x00" in stripped:
        return None
    if stripped in (".", ".."):
        return None
    return stripped


def resolve_filename(
    layer: dict[str, Any],
    manifest_annotations: dict[str, Any] | None,
    *,
    force: bool = False,
) -> str | None:
    """Resolve a filename for a layer using annotation-based naming rules.

    Resolution order:
    1. Use the layer's own 'org.opencontainers.image.title' annotation if present.
       When force=False, the title is sanitized; an unsafe title falls through to step 2.
       When force=True, the raw title is returned without sanitization.
    2. Else construct '<title>-<version>.tgz' from manifest-level annotations
       ('org.opencontainers.image.title' + 'org.opencontainers.image.version').
       This fallback is always sanitized regardless of force.
    3. Return None if no naming info is available.

    Args:
        layer: OCI layer descriptor dict (may contain 'annotations').
        manifest_annotations: Manifest-level annotations dict, or None.
        force: If True, skip sanitization on the layer title annotation.

    Returns:
        Resolved filename string, or None if no name can be determined.
    """
    layer_annotations = layer.get("annotations") or {}
    layer_title = layer_annotations.get(_OCI_TITLE)
    if layer_title:
        if force:
            return layer_title
        safe = sanitize_filename(layer_title)
        if safe is not None:
            return safe
        # Unsafe title — fall through to manifest-level annotations

    if manifest_annotations:
        title = manifest_annotations.get(_OCI_TITLE)
        version = manifest_annotations.get(_OCI_VERSION)
        if title and version:
            return f"{title}-{version}.tgz"

    return None
