"""OCI registry adapter: oras-py wrapper."""

from datetime import UTC, datetime
from logging import DEBUG, INFO, WARNING, Formatter, Handler, LogRecord, getLogger
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from oras.client import OrasClient as OrasClientLib
from oras.container import Container
from oras.defaults import annotation_title
from oras.oci import ManifestConfig, NewLayer, NewManifest

from margot import console
from margot.infra import credentials


class _OrasLogHandler(Handler):
    """Route oras-py log records to margot's console."""

    def emit(self, record: LogRecord) -> None:
        msg = self.format(record)
        level = record.levelno
        if level >= WARNING:
            console.warning(f"[oras] {msg}")
        elif level >= INFO:
            console.info(f"[oras] {msg}")
        else:  # DEBUG
            console.debug(f"[oras] {msg}")


def _configure_oras_logger() -> None:
    """Attach margot's log handler to the oras logger. Idempotent."""
    oras_logger = getLogger("oras.logger")
    # Remove any existing handlers to avoid duplicate output
    for handler in list(oras_logger.handlers):
        oras_logger.removeHandler(handler)
    handler = _OrasLogHandler()
    handler.setFormatter(Formatter("%(message)s"))
    oras_logger.addHandler(handler)
    oras_logger.propagate = False
    level = DEBUG if console.is_debug() else (INFO if console.is_verbose() else WARNING)
    oras_logger.setLevel(level)


class OrasClient(OrasClientLib):
    """OCI client extending oras.client.OrasClient for anonymous OCI operations.

    Provides pull() for bulk layer download and download_blob() for individual blob retrieval.
    """

    def __init__(self, hostname: str | None = None) -> None:
        """Initialize OrasClient for registry access.

        Args:
            hostname: Registry hostname (e.g. 'public.ecr.aws'). When provided,
                stored credentials for that host are loaded automatically so
                subsequent operations use them. When omitted, the client is
                anonymous-only (no credential loading).
        """
        super().__init__()
        if hostname is not None:
            self.auth.load_configs(self.get_container(hostname))
        _configure_oras_logger()

    def get_manifest(
        self,
        container: str | Container,
        allowed_media_type: list | None = None,
        validation_schema: dict | None = None,
    ) -> dict[str, Any]:
        """Fetch the manifest of an OCI artifact.

        This method overrides the base class signature to support both legacy usage
        patterns from margot's own call sites (which pass a URI string) and internal
        oras-py polymorphic calls (which pass a Container object with extra parameters).

        Liskov Substitution Principle: The override's signature is a superset-compatible
        match of the base class's, accepting both a plain URI string and a Container
        object with optional parameters. Internal oras-py calls (e.g., from Registry.pull())
        dispatch through self.get_manifest(container, allowed_media_type) polymorphically,
        passing a Container object and optional allowed_media_type; this method must
        accept both forms without re-wrapping or dropping arguments.

        Args:
            container: Full OCI reference as a string (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
                or an oras.container.Container instance (when called by oras-py internals).
            allowed_media_type: Optional list of allowed manifest media types.
                Passed through to the base class unchanged.
            validation_schema: Optional validation schema dict. Passed through to the base
                class unchanged.

        Returns:
            Manifest dict from the registry.

        Raises:
            Exception: If fetch fails.
        """
        # If container is a plain string (margot's own external call sites), convert to Container.
        # If it's already a Container (oras-py's internal polymorphic dispatch), use as-is.
        if isinstance(container, str):
            console.debug(f"GET manifest: {container}")
            container = self.get_container(container)
        else:
            console.debug(f"GET manifest: {container}")

        return super().get_manifest(container, allowed_media_type, validation_schema)

    def pull(self, uri: str, outdir: str) -> list[str]:
        """
        Pull OCI artifact layers to outdir.

        Deprecated:
            Production code should use download_blob() directly via the layer loop
            in services/pull.py. This method is retained for legacy test compatibility
            and for non-compose/quadlet artifact types.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)
            outdir: Directory to write layer blobs to.

        Returns:
            List of paths to written files.

        Raises:
            Exception: If pull fails.
        """
        console.debug(f"Pull layers: {uri} → {outdir}")
        result = super().pull(target=uri, outdir=outdir)
        if isinstance(result, list):
            return result
        return []

    def download_blob(self, uri: str, digest: str, outfile: str) -> str:
        """
        Download a single blob by digest to outfile.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0).
                Used to resolve the registry/repository container.
            digest: The blob digest (e.g. 'sha256:abc...').
            outfile: Destination file path (created by oras-py).

        Returns:
            The outfile path.

        Raises:
            Exception: If download fails.
        """
        console.debug(f"Download blob: {digest} → {outfile}")
        super().download_blob(uri, digest, outfile)
        return outfile

    def login(self, hostname: str, username: str, password: str) -> None:
        """
        Authenticate with an OCI registry.

        Args:
            hostname: Registry hostname (e.g. 'public.ecr.aws').
            username: Username (e.g. 'AWS' for ECR).
            password: Password or token.
        """
        console.debug(f"Login: {hostname} as {username}")
        super().login(username=username, password=password, hostname=hostname)

    def logout(self, hostname: str) -> None:
        """
        Remove stored credentials for registry.

        oras-py's logout() only clears its in-memory auth state — it never
        persists the removal to ~/.docker/config.json (see
        oras.auth.base.AuthBackend.logout()). We call it for correctness within
        this process, then explicitly strip the on-disk entry ourselves so a
        subsequent `margot auth login` doesn't see stale credentials.

        Args:
            hostname: Registry hostname.
        """
        console.debug(f"Logout: {hostname}")
        super().logout(hostname=hostname)
        credentials.remove_docker_config_entry(hostname)

    def push_margo(  # noqa: PLR0913
        self,
        build_dir: str,
        version: str,
        registry: str,
        repository: str,
        name: str,
        description: str,
    ) -> None:
        """
        Push a margo artifact to OCI registry.

        Reads files from: <build_dir>/<version>/margo/
        Only includes files that actually exist in the build_dir (skip missing optional ones).

        Args:
            build_dir: Root build output directory.
            version: SemVer version tag.
            registry: OCI registry hostname.
            repository: Repository path within registry.
            name: Application name (for annotation).
            description: Application description (for annotation).
        """
        target = f"{registry}/{repository}:{version}"
        console.debug(f"Push margo: {target}")

        margo_dir = Path(build_dir) / version / "margo"

        # Build file list: (path, media_type, annotation_title)
        file_entries: list[tuple[Path, str, str]] = [
            (margo_dir / "app.yaml", "application/vnd.margo.app.description.v1+yaml", "app.yaml"),
        ]
        optional = [
            (margo_dir / "resources" / "icon.png", "application/vnd.margo.app.icon.v1+png", "resources/icon.png"),
            (margo_dir / "resources" / "license.txt", "application/vnd.margo.app.license.v1+plain", "resources/license.txt"),
            (
                margo_dir / "resources" / "release-notes.md",
                "application/vnd.margo.app.releaseNotes.v1+markdown",
                "resources/release-notes.md",
            ),
            (
                margo_dir / "resources" / "description.md",
                "application/vnd.margo.app.descriptionFile.v1+markdown",
                "resources/description.md",
            ),
        ]
        for path, mt, title in optional:
            if path.exists():
                file_entries.append((path, mt, title))

        self._push_artifact(
            target=target,
            artifact_type="application/vnd.margo.app.v1+json",
            file_entries=file_entries,
            manifest_annotations={
                "org.opencontainers.image.title": name,
                "org.opencontainers.image.description": description,
            },
        )

    def push_compose(  # noqa: PLR0913
        self,
        archive_path: str,
        version: str,
        registry: str,
        repository: str,
        name: str,
        description: str,
    ) -> None:
        """
        Push a compose artifact to OCI registry.

        Args:
            archive_path: Path to the .tgz archive.
            version: SemVer version tag.
            registry: OCI registry hostname.
            repository: Repository path within registry.
            name: Application name (for annotation).
            description: Application description (for annotation).
        """
        target = f"{registry}/{repository}:{version}"
        console.debug(f"Push compose: {target}")
        self._push_artifact(
            target=target,
            artifact_type="application/vnd.org.margo.component.compose+json",
            file_entries=[
                (Path(archive_path), "application/vnd.org.margo.component.compose.tar+gzip", Path(archive_path).name),
            ],
            manifest_annotations={
                "org.margo.component.type": "compose",
                "org.margo.component.version": version,
                "org.opencontainers.image.title": name,
                "org.opencontainers.image.description": description,
            },
        )

    def push_quadlet(  # noqa: PLR0913
        self,
        archive_path: str,
        version: str,
        registry: str,
        repository: str,
        name: str,
        description: str,
    ) -> None:
        """
        Push a quadlet artifact to OCI registry.

        Args:
            archive_path: Path to the .tgz archive.
            version: SemVer version tag.
            registry: OCI registry hostname.
            repository: Repository path within registry.
            name: Application name (for annotation).
            description: Application description (for annotation).
        """
        target = f"{registry}/{repository}:{version}"
        console.debug(f"Push quadlet: {target}")
        self._push_artifact(
            target=target,
            artifact_type="application/vnd.org.margo.component.quadlet+json",
            file_entries=[
                (Path(archive_path), "application/vnd.org.margo.component.quadlet.tar+gzip", Path(archive_path).name),
            ],
            manifest_annotations={
                "org.margo.component.type": "quadlet",
                "org.margo.component.version": version,
                "org.opencontainers.image.title": name,
                "org.opencontainers.image.description": description,
            },
        )

    def _push_artifact(
        self,
        target: str,
        artifact_type: str,
        file_entries: list[tuple[Path, str, str]],
        manifest_annotations: dict[str, str],
    ) -> None:
        """Low-level OCI artifact push with artifactType support.

        Args:
            target: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0).
            artifact_type: The artifactType to set in the manifest.
            file_entries: List of (path, media_type, annotation_title) tuples for layers.
            manifest_annotations: Annotations to set on the manifest.
        """
        container = self.get_container(target)
        self.auth.load_configs(container)

        manifest = NewManifest()
        manifest = {
            "schemaVersion": manifest["schemaVersion"],
            "mediaType": manifest["mediaType"],
            "artifactType": artifact_type,
            "config": manifest["config"],
            "layers": manifest["layers"],
            "annotations": manifest["annotations"],
        }

        # Build and upload layers
        layers = []
        for file_path, media_type, title in file_entries:
            layer = NewLayer(blob_path=str(file_path), media_type=media_type)
            layer["annotations"] = {annotation_title: title}
            console.debug(f"  layer: {title} [{media_type}] ({layer['size']} bytes, {layer['digest']})")
            response = self.upload_blob(blob=str(file_path), container=container, layer=layer)
            self._check_200_response(response)
            layers.append(layer)

        # Build and upload the empty config blob
        conf, _ = ManifestConfig(path=None, media_type="application/vnd.oci.empty.v1+json")
        console.debug(f"  config: {conf['mediaType']} ({conf['size']} bytes, {conf['digest']})")
        with NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            tmp.write("{}")
            tmp_path = Path(tmp.name)
        try:
            response = self.upload_blob(blob=str(tmp_path), container=container, layer=conf)
            self._check_200_response(response)
        finally:
            tmp_path.unlink()

        # Assemble manifest
        manifest["config"] = conf
        manifest["layers"] = layers
        created = datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest["annotations"] = {
            "org.opencontainers.image.created": created,
            **manifest_annotations,
        }
        console.debug(f"  annotations: {list(manifest['annotations'].keys())}")
        console.debug(f"  uploading manifest → {target}")

        console.debug(f"  manifest uploaded ({response.status_code})")
        response = self.upload_manifest(manifest=manifest, container=container)
        self._check_200_response(response)
