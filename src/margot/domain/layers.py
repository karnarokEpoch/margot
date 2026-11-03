"""Layer selection and filename resolution: pure functions, no I/O."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

COMPOSE_LAYER_MEDIA_TYPE = "application/vnd.org.margo.component.compose.tar+gzip"
QUADLET_LAYER_MEDIA_TYPE = "application/vnd.org.margo.component.quadlet.tar+gzip"

# Margo application descriptor and resource media types
MARGO_DESCRIPTION_MEDIA_TYPE = "application/vnd.margo.app.description.v1+yaml"
MARGO_ICON_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.icon.v1+{ext}"
MARGO_LICENSE_FILE_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.licenseFile.v1+{ext}"
MARGO_RELEASE_NOTES_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.releaseNotes.v1+{ext}"
MARGO_DESCRIPTION_FILE_MEDIA_TYPE_TEMPLATE = "application/vnd.margo.app.descriptionFile.v1+{ext}"
MARGO_RESOURCE_FALLBACK_MEDIA_TYPE = "application/octet-stream"

# Annotation the Margo spec requires on every layer that references a Margo application resource
MARGO_RESOURCE_ANNOTATION = "org.margo.app.resource"
MARGO_RESOURCE_ANNOTATION_VALUE = "true"

# Extension -> Margo {file format} token. Extensions not listed here pass through unchanged.
_FILE_FORMAT_TOKENS: dict[str, str] = {
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "tif": "tiff",
    "tiff": "tiff",
    "md": "markdown",
    "markdown": "markdown",
}

_OCI_TITLE = "org.opencontainers.image.title"
_OCI_VERSION = "org.opencontainers.image.version"

# Application-level fields in metadata.catalog.application that reference a local resource file
_RESOURCE_REFERENCE_FIELDS: tuple[str, ...] = ("icon", "descriptionFile", "licenseFile", "releaseNotes")
_REMOTE_SCHEMES = frozenset({"http", "https"})


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
    if layer_title and isinstance(layer_title, str):
        if force:
            return layer_title
        safe = sanitize_filename(layer_title)
        if safe is not None:
            return safe
        # Unsafe title — fall through to manifest-level annotations

    if manifest_annotations:
        title = manifest_annotations.get(_OCI_TITLE)
        version = manifest_annotations.get(_OCI_VERSION)
        if title and version and isinstance(title, str) and isinstance(version, str):
            return f"{title}-{version}.tgz"

    return None


def _file_format_token(path_str: str) -> str:
    """Derive the Margo {file format} token for a resource path.

    The extension is lowercased, the dot is stripped, and the result is looked up in a
    small explicit table. Extensions not in the table pass through unchanged. A file with
    no extension uses 'bin'. The mimetypes module is deliberately not used: it depends on
    host mime files and yields values such as 'svg+xml'.

    Table:
        jpg, jpeg      -> jpeg
        tif, tiff      -> tiff
        md, markdown   -> markdown
        anything else  -> the lowercased extension (svg, png, txt, bmp, ...)
        no extension   -> bin

    Args:
        path_str: A file path string.

    Returns:
        The {file format} token for the media type template.

    Examples:
        'icon.svg' -> 'svg'
        'icon.SVG' -> 'svg'
        'photo.JPG' -> 'jpeg'
        'notes.md' -> 'markdown'
        'license.txt' -> 'txt'
        'file' -> 'bin'
    """
    suffix = Path(path_str).suffix
    if not suffix:
        return "bin"
    extension = suffix.lstrip(".").lower()
    return _FILE_FORMAT_TOKENS.get(extension, extension)


@dataclass(frozen=True)
class ResourceFile:
    """A resource file to push as a layer, with its resolved path and media type.

    Attributes:
        path: Absolute Path to the file.
        media_type: OCI layer mediaType string.
        title: OCI annotation title (relative path for display).
    """

    path: Path
    media_type: str
    title: str


def _child_mapping(node: object, key: str) -> dict[str, Any] | None:
    """Return node[key] if node is a dict and that value is also a dict, otherwise None."""
    if not isinstance(node, dict):
        return None
    child = node.get(key)
    return child if isinstance(child, dict) else None


def extract_resource_references(app_yaml_dict: object) -> dict[str, str]:
    """Extract the resource file references from a Margo application description.

    In a Margo application description the references live at
    ``metadata.catalog.application.<field>``. Any missing level, a None value, or a
    non-mapping value at any level yields no references rather than an error. Only
    non-empty string values are returned; other values are ignored. There is no fallback
    to top-level keys.

    Args:
        app_yaml_dict: Parsed app.yaml content. Any value is accepted; a non-mapping value yields {}.

    Returns:
        Mapping of field name (icon, descriptionFile, licenseFile, releaseNotes) to the
        stripped referenced value, for each field that holds a non-empty string.
    """
    application = _child_mapping(_child_mapping(_child_mapping(app_yaml_dict, "metadata"), "catalog"), "application")
    if application is None:
        return {}

    references: dict[str, str] = {}
    for field_name in _RESOURCE_REFERENCE_FIELDS:
        value = application.get(field_name)
        if isinstance(value, str) and value.strip():
            references[field_name] = value.strip()
    return references


def resolve_margo_resource_files(
    app_yaml_dict: dict[str, Any],
    margo_dir: Path,
) -> tuple[list[ResourceFile], list[tuple[str, str]]]:
    """Resolve resource files to push based on app.yaml and the margo build directory.

    Resolves files in this order:
    1. For each reference returned by extract_resource_references() (icon, descriptionFile,
       licenseFile, releaseNotes under metadata.catalog.application):
       - Values with an http or https scheme are remote, not local files. They are skipped
         silently: not pushed and not reported missing.
       - Otherwise the value is resolved relative to margo_dir. If it names an existing file
         inside margo_dir, it is added with a semantically correct media type based on the
         field name and the file's {file format} token. If it is absent, is not a file, or
         resolves outside margo_dir, (field, value) is added to the missing list. The caller
         emits a warning for each entry.
    2. Scan <margo_dir>/resources/ (if it exists), sorted, for files not already matched by
       step 1. Add each such file with the fallback media type (application/octet-stream).

    margo_dir is resolved once up front, so every comparison and every title uses the same
    absolute form regardless of whether it was given as a relative path or through a
    symlink. Every title is the path relative to the resolved margo_dir with '/' separators
    (e.g. 'resources/icon.svg', 'resources/screenshots/a.png'). './' prefixes normalise away.

    The descriptor layer (app.yaml itself) is NOT included in the returned list — it is
    always added as the first required entry by the caller.

    Args:
        app_yaml_dict: Parsed app.yaml dict (typically from safe_load of YAML content).
        margo_dir: Path to the margo build directory (relative or absolute).

    Returns:
        A tuple of (files_to_push, missing). files_to_push is a list of ResourceFile entries
        in push order. missing is a list of (field_name, referenced_value) pairs for local
        references whose files do not exist inside margo_dir.
    """
    margo_dir = margo_dir.resolve()
    resource_files: list[ResourceFile] = []
    missing: list[tuple[str, str]] = []

    # Field name → media type template mapping
    field_to_template = {
        "icon": MARGO_ICON_MEDIA_TYPE_TEMPLATE,
        "descriptionFile": MARGO_DESCRIPTION_FILE_MEDIA_TYPE_TEMPLATE,
        "licenseFile": MARGO_LICENSE_FILE_MEDIA_TYPE_TEMPLATE,
        "releaseNotes": MARGO_RELEASE_NOTES_MEDIA_TYPE_TEMPLATE,
    }

    # Resolved absolute paths already emitted, so the resources/ scan skips them
    processed_paths: set[Path] = set()

    # Step 1: Process metadata.catalog.application references
    references = extract_resource_references(app_yaml_dict)
    for field_name, template in field_to_template.items():
        value = references.get(field_name)
        if value is None or urlparse(value).scheme in _REMOTE_SCHEMES:
            continue

        resolved_path = (margo_dir / value).resolve()
        # A reference that escapes margo_dir is treated as missing
        if not resolved_path.is_relative_to(margo_dir) or not resolved_path.is_file():
            missing.append((field_name, value))
            continue

        media_type = template.format(ext=_file_format_token(value))
        resource_files.append(
            ResourceFile(
                path=resolved_path,
                media_type=media_type,
                title=resolved_path.relative_to(margo_dir).as_posix(),
            )
        )
        processed_paths.add(resolved_path)

    # Step 2: Scan resources/ directory for unreferenced files
    resources_dir = margo_dir / "resources"
    if resources_dir.exists():
        for resource_file in sorted(resources_dir.rglob("*")):
            if not resource_file.is_file() or resource_file.resolve() in processed_paths:
                continue
            resource_files.append(
                ResourceFile(
                    path=resource_file,
                    media_type=MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
                    title=resource_file.relative_to(margo_dir).as_posix(),
                )
            )
            processed_paths.add(resource_file.resolve())

    return resource_files, missing
