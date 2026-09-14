"""Describe service: resolve the Margo application description and load it into a dict.

This service reuses the descriptor resolution logic from verify.py (find, render, load)
and adds the Item 1 load gate: the descriptor must be valid YAML that parses into a
mapping with kind=ApplicationDescription.
"""

from dataclasses import dataclass
from pathlib import Path

from margot import console
from margot.domain.metadata import MargoYaml
from margot.infra.filesystem import load_yaml
from margot.services.verify import resolve_descriptor

JINJA_DESCRIPTOR = "app.yaml.jinja"
STATIC_DESCRIPTOR = "app.yaml"


@dataclass(frozen=True)
class LoadedDescriptor:
    """Loaded descriptor with metadata and resolution info.

    Attributes:
        descriptor: The parsed descriptor dict.
        meta: Parsed `margo.yaml`, or None when an explicit static manifest was given
            and no `margo.yaml` was needed.
        source_path: The descriptor as found on disk (template or static file).
        rendered: True when the descriptor was rendered from a template.
    """

    descriptor: dict
    meta: MargoYaml | None
    source_path: str
    rendered: bool


def load_descriptor(project_dir: str = ".", manifest_path: str | None = None) -> LoadedDescriptor:
    """Load the resolved application description into a dict, enforcing the Item 1 load gate.

    The descriptor is located, rendered if templated, and parsed. It must be valid YAML
    that parses into a mapping with kind=ApplicationDescription. Temporary files are
    cleaned up after parsing.

    Args:
        project_dir: Directory holding margo.yaml.
        manifest_path: Explicit app.yaml / app.yaml.jinja path, bypassing margo.yaml
            resolution.

    Returns:
        A LoadedDescriptor with the parsed descriptor, metadata, source path, and
        rendered flag. The temp file (if any) is already cleaned up.

    Raises:
        ValueError: If the file is missing, both descriptor forms are present, Jinja2
            rendering fails, YAML does not parse, does not parse to a mapping, or
            kind != ApplicationDescription.
    """
    resolved = resolve_descriptor(project_dir, manifest_path)
    try:
        # Load the YAML — this may raise ValueError if invalid
        parsed = load_yaml(resolved.path)
        console.info(f"Application description loaded: {resolved.source_path}")

        # Enforce: must be a mapping
        if not isinstance(parsed, dict):
            raise TypeError("Application description must parse into a mapping (dict), not a sequence or scalar.")

        # Enforce: kind must be ApplicationDescription
        kind = parsed.get("kind")
        if kind != "ApplicationDescription":
            raise ValueError(
                f"Application description kind must be 'ApplicationDescription', got '{kind}'. Run 'margot verify' to debug."
            )

        console.info(
            "Item 1 load gate passed: valid mapping with kind=ApplicationDescription"
        )
        return LoadedDescriptor(
            descriptor=parsed,
            meta=resolved.meta,
            source_path=resolved.source_path,
            rendered=resolved.rendered,
        )

    finally:
        # Clean up temp file if it was rendered
        if resolved.rendered:
            Path(resolved.path).unlink(missing_ok=True)
            console.debug(f"Removed temp file: {resolved.path}")


def load_descriptor_from_path(descriptor_path: str, source_uri: str | None = None) -> LoadedDescriptor:
    """Load an application description from an explicit static file path (e.g., a pulled remote app.yaml).

    Does not perform any Jinja2 rendering or margo.yaml resolution. Enforces the same
    Item 1 load gate (kind=ApplicationDescription). Suitable for loading a descriptor that
    has already been resolved externally (e.g., pulled from a remote artifact).

    Args:
        descriptor_path: Absolute or relative path to the app.yaml file to load.
        source_uri: Optional OCI reference or label for the source (used for display only).
            If provided, replaces source_path in the returned LoadedDescriptor.

    Returns:
        A LoadedDescriptor with parsed descriptor, no metadata (meta=None), source_path
        set to source_uri (if provided) or descriptor_path, rendered=False.

    Raises:
        ValueError: If the file is missing or YAML does not parse.
        TypeError: If YAML does not parse to a mapping.
        ValueError: If kind != ApplicationDescription.
    """
    source_path = Path(descriptor_path)
    if not source_path.is_file():
        raise ValueError(f"Application description not found: {descriptor_path}")

    # Load the YAML
    parsed = load_yaml(str(source_path))
    console.info(f"Application description loaded: {descriptor_path}")

    # Enforce: must be a mapping
    if not isinstance(parsed, dict):
        raise TypeError("Application description must parse into a mapping (dict), not a sequence or scalar.")

    # Enforce: kind must be ApplicationDescription
    kind = parsed.get("kind")
    if kind != "ApplicationDescription":
        raise ValueError(
            f"Application description kind must be 'ApplicationDescription', got '{kind}'. Run 'margot verify' to debug."
        )

    console.info("Item 1 load gate passed: valid mapping with kind=ApplicationDescription")
    return LoadedDescriptor(
        descriptor=parsed,
        meta=None,  # No margo.yaml for externally-resolved descriptors
        source_path=source_uri or str(source_path),  # Use source_uri if provided
        rendered=False,
    )
