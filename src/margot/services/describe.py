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
