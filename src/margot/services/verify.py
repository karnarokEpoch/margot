"""Verify service: resolve the Margo application description and validate it.

Descriptor resolution is deliberately separate from :func:`verify` — `margot describe`
needs the identical find → render → load behavior.
"""

from dataclasses import dataclass
from pathlib import Path

from margot import console
from margot.domain.metadata import MargoYaml, build_jinja2_context, load_margo_yaml
from margot.domain.validation import ValidationFinding, VerifyResult, has_errors
from margot.infra.filesystem import write_temp_text
from margot.infra.templating import render_template_file
from margot.schemas import SCHEMA_A_COMMIT, SCHEMA_A_PATH, SCHEMA_A_TARGET_CLASS
from margot.validation.linkml_runner import run_validation

JINJA_DESCRIPTOR = "app.yaml.jinja"
STATIC_DESCRIPTOR = "app.yaml"


@dataclass(frozen=True)
class ResolvedDescriptor:
    """A Margo application description ready to be read.

    Attributes:
        path: File to read — a temporary file when the descriptor was a template.
        source_path: The descriptor as found on disk (template or static file).
        meta: Parsed `margo.yaml`, or None when an explicit static manifest was given
            and no `margo.yaml` was needed.
        rendered: True when `path` is a temporary file **the caller must delete**.
    """

    path: str
    source_path: str
    meta: MargoYaml | None
    rendered: bool


def resolve_descriptor(project_dir: str = ".", manifest_path: str | None = None) -> ResolvedDescriptor:
    """Locate the application description, rendering it when it is a Jinja2 template.

    Never reads the build directory and never requires a prior `build`: the source
    descriptor is resolved directly, and a template is rendered to a temporary file with
    the same context and `StrictUndefined` behavior `build` uses.

    Args:
        project_dir: Directory holding `margo.yaml`.
        manifest_path: Explicit `app.yaml` / `app.yaml.jinja` path, bypassing `margo.yaml`
            resolution.

    Returns:
        The resolved descriptor. When ``rendered`` is True the caller owns the temporary
        file at ``path`` and must delete it.

    Raises:
        ValueError: If `margo.yaml` or the descriptor is missing, if both descriptor
            forms are present, or if a template variable cannot be resolved.
    """
    meta: MargoYaml | None = None
    if manifest_path is not None:
        source = Path(manifest_path)
        if not source.is_file():
            raise ValueError(f"Application description not found: {manifest_path}")
    else:
        meta = load_margo_yaml(str(Path(project_dir) / "margo.yaml"))
        source = _find_descriptor(Path(project_dir) / meta.directory)
    console.info(f"Application description resolved: {source}")

    if source.name.endswith(".jinja"):
        if meta is None:
            meta = load_margo_yaml(str(Path(project_dir) / "margo.yaml"))
        rendered = render_template_file(
            str(source),
            build_jinja2_context(meta, global_repository=meta.repository),
            source_label=JINJA_DESCRIPTOR,
        )
        temp_path = write_temp_text(rendered, suffix=".yaml")
        console.info(f"Rendered {source.name} to a temporary file")
        return ResolvedDescriptor(path=temp_path, source_path=str(source), meta=meta, rendered=True)

    return ResolvedDescriptor(path=str(source), source_path=str(source), meta=meta, rendered=False)


def verify(project_dir: str = ".", manifest_path: str | None = None, schema_path: str | None = None) -> VerifyResult:
    """Validate the application description against the upstream Margo spec schema.

    Args:
        project_dir: Directory holding `margo.yaml`.
        manifest_path: Explicit descriptor path, bypassing `margo.yaml` resolution.
        schema_path: Override for the vendored upstream schema.

    Returns:
        The validation outcome. `passed` is False when any Schema A finding is an ERROR.

    Raises:
        ValueError: If the descriptor cannot be resolved or rendered.
    """
    schema = schema_path or SCHEMA_A_PATH
    descriptor = resolve_descriptor(project_dir, manifest_path)
    try:
        console.info(f"Running Schema A validation against {schema}")
        findings: list[ValidationFinding] = run_validation(descriptor.path, schema, SCHEMA_A_TARGET_CLASS)
    finally:
        if descriptor.rendered:
            Path(descriptor.path).unlink(missing_ok=True)
            console.debug(f"Removed temp file: {descriptor.path}")

    passed = not has_errors(findings)
    console.info(f"Schema A validation complete: {len(findings)} finding(s), passed={passed}")
    return VerifyResult(
        schema_a_results=findings,
        schema_b_results=[],
        schema_a_version=SCHEMA_A_COMMIT,
        passed=passed,
    )


def _find_descriptor(source_dir: Path) -> Path:
    """Return the descriptor inside the margo source directory.

    Raises:
        ValueError: If both descriptor forms are present, or neither is.
    """
    jinja_file = source_dir / JINJA_DESCRIPTOR
    static_file = source_dir / STATIC_DESCRIPTOR
    if jinja_file.exists() and static_file.exists():
        raise ValueError("Both app.yaml.jinja and app.yaml found in margo source directory — use one or the other, not both.")
    if jinja_file.exists():
        return jinja_file
    if static_file.exists():
        return static_file
    raise ValueError("No app.yaml or app.yaml.jinja found in margo source directory.")
