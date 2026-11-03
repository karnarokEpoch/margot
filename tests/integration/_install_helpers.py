"""Builders shared by the install integration tests: tar archives, descriptors and built projects."""

import io
from pathlib import Path
import re
import tarfile
from typing import Any

from margot.infra.systemd import GeneratorRun

MOSQUITTO_QUADLET_REVISION = "1.0.2+mosquitto-quadlet"
MOSQUITTO_QUADLET_TAG = "1.0.2_mosquitto-quadlet"
MOSQUITTO_MARGO_VERSION = "1.0.3+mosquitto-margo-manifest"
MOSQUITTO_MARGO_TAG = "1.0.3_mosquitto-margo-manifest"
REPOSITORY = "public.ecr.aws/g2n4p2m7/belden-margo"

MOSQUITTO_CONTAINER = b"[Container]\nImage=docker.io/library/eclipse-mosquitto:2\nPublishPort=1883:1883\n"
MOSQUITTO_CONF = b"listener 1883\nallow_anonymous true\n"


def write_tar(path: Path, members: dict[str, bytes]) -> Path:
    """Write a gzip tar with the given regular-file members (name -> content)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def unquote_environment(line: str) -> str:
    """Return the value of an ``Environment="NAME=value"`` line as systemd reads it.

    The independent reader used to check margot's encoding: it removes the surrounding quotes, turns
    ``\\\\`` and ``\\"`` back into a backslash and a quote, and ``%%`` back into ``%``.

    Raises:
        ValueError: If the line is not a quoted Environment assignment.
    """
    match = re.fullmatch(r'Environment="[^=]*=(.*)"', line)
    if match is None:
        raise ValueError(f"not a quoted Environment assignment: {line!r}")
    return re.sub(r"\\(.)|%%", lambda found: found.group(1) or "%", match.group(1))


def quadlet_payload(root: str | None = "mosquitto-1.0.2_mosquitto-quadlet") -> dict[str, bytes]:
    """The quadlet payload as margot builds it: an optional top-level directory and two files."""
    prefix = f"{root}/" if root else ""
    return {
        f"{prefix}mosquitto.container": MOSQUITTO_CONTAINER,
        f"{prefix}conf/mosquitto.conf": MOSQUITTO_CONF,
    }


def app_description(  # noqa: PLR0913 - keyword-only test builder
    *,
    profile_type: str = "quadlet",
    profile_id: str = "quadlet-v1",
    component: str = "mosquitto-quadlet",
    repository: str = f"oci://{REPOSITORY}",
    revision: str = MOSQUITTO_QUADLET_REVISION,
    extra_profiles: str = "",
    parameters: str = "",
    app_id: str = "com-belden-mosquitto",
) -> str:
    """A minimal built application description with one profile of the given type."""
    return f"""apiVersion: margo.org/v1alpha1
kind: ApplicationDescription
id: {app_id}
metadata:
  name: Eclipse Mosquitto
  version: {MOSQUITTO_MARGO_VERSION}
deploymentProfiles:
  - id: {profile_id}
    type: {profile_type}
    components:
      - name: {component}
        properties:
          repository: {repository}
          revision: {revision}
{extra_profiles}{parameters}"""


MARGO_YAML = f"""apiVersion: v1
id: com-belden-mosquitto
name: mosquitto
version: {MOSQUITTO_MARGO_VERSION}
description: Lightweight MQTT broker
repository: {REPOSITORY}
quadlet:
  version: {MOSQUITTO_QUADLET_REVISION}
"""


def build_project(
    root: Path, *, descriptor: str | None = None, archive_members: dict[str, bytes] | None = None
) -> tuple[Path, Path]:
    """Create a project with margo.yaml and a built `.dist` tree. Returns (project_dir, build_dir)."""
    project = root / "project"
    project.mkdir(parents=True)
    (project / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
    build = project / ".dist"
    margo_dir = build / MOSQUITTO_MARGO_TAG / "margo"
    margo_dir.mkdir(parents=True)
    (margo_dir / "app.yaml").write_text(descriptor or app_description(), encoding="utf-8")
    write_tar(
        build / MOSQUITTO_QUADLET_TAG / f"mosquitto-{MOSQUITTO_QUADLET_TAG}.tgz",
        archive_members if archive_members is not None else quadlet_payload(),
    )
    return project, build


def build_static_folder(root: Path, *, descriptor: str | None = None, members: dict[str, bytes] | None = None) -> Path:
    """Create a `pull --recursive`-shaped folder: app.yaml plus <component>/<one archive>. Returns the folder."""
    folder = root / "pulled"
    folder.mkdir(parents=True)
    (folder / "app.yaml").write_text(descriptor or app_description(), encoding="utf-8")
    component_dir = folder / "mosquitto-quadlet"
    write_tar(component_dir / "bundle.tgz", members if members is not None else quadlet_payload())
    return folder


def answer_by_run(staged: GeneratorRun, host: GeneratorRun | BaseException) -> Any:
    """A stand-in for ``systemd.check_units`` that answers the two kinds of run differently.

    A call with a unit directory is the staged-tree dry run (guard 2) and gets ``staged``. A call with
    ``None`` is the host run that uses the real search path (guard 3) and gets ``host``, or raises it when
    ``host`` is an exception.
    """

    def check(unit_dir: Path | None, _binary: str, _environ: Any) -> GeneratorRun:
        if unit_dir is not None:
            return staged
        if isinstance(host, BaseException):
            raise host
        return host

    return check
