"""OCI registry adapter: oras-py wrapper."""

import os
import tempfile
from pathlib import Path
from typing import Any

import oras.defaults
import oras.oci
from oras.client import OrasClient as OrasClientLib

from margot import console


class OrasClient:
    """Wrapper around oras.client.OrasClient for anonymous OCI operations.

    Provides pull() for bulk layer download and download_blob() for individual blob retrieval.
    """

    def __init__(self) -> None:
        """Initialize OrasClient for anonymous registry access."""
        self._client = OrasClientLib()

    def get_manifest(self, uri: str) -> dict[str, Any]:
        """
        Fetch the manifest of an OCI artifact.

        Args:
            uri: Full OCI reference (e.g. public.ecr.aws/g2n4p2m7/margo:1.0.0)

        Returns:
            Manifest dict from the registry.

        Raises:
            Exception: If fetch fails.
        """
        console.debug(f"GET manifest: {uri}")
        return self._client.get_manifest(uri)

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
        result = self._client.pull(target=uri, outdir=outdir)
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
        self._client.download_blob(uri, digest, outfile)
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
        self._client.login(username=username, password=password, hostname=hostname)

    def logout(self, hostname: str) -> None:
        """
        Remove stored credentials for registry.

        Args:
            hostname: Registry hostname.
        """
        console.debug(f"Logout: {hostname}")
        self._client.logout(hostname=hostname)

    def push_margo(
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
            (margo_dir / "resources" / "release-notes.md", "application/vnd.margo.app.releaseNotes.v1+markdown", "resources/release-notes.md"),
            (margo_dir / "resources" / "description.md", "application/vnd.margo.app.descriptionFile.v1+markdown", "resources/description.md"),
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

    def push_compose(
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

    def push_quadlet(
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
        container = self._client.get_container(target)
        self._client.auth.load_configs(container)

        manifest = oras.oci.NewManifest()
        manifest["artifactType"] = artifact_type

        # Build and upload layers
        layers = []
        for file_path, media_type, title in file_entries:
            layer = oras.oci.NewLayer(blob_path=str(file_path), media_type=media_type)
            layer["annotations"] = {oras.defaults.annotation_title: title}
            response = self._client.upload_blob(blob=str(file_path), container=container, layer=layer)
            self._client._check_200_response(response)
            layers.append(layer)

        # Build and upload the empty config blob
        conf, _ = oras.oci.ManifestConfig(path=None, media_type="application/vnd.oci.empty.v1+json")
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write("{}")
        tmp.close()
        try:
            response = self._client.upload_blob(blob=tmp.name, container=container, layer=conf)
            self._client._check_200_response(response)
        finally:
            os.unlink(tmp.name)

        # Assemble manifest
        manifest["config"] = conf
        manifest["layers"] = layers
        manifest["annotations"] = manifest_annotations

        response = self._client.upload_manifest(manifest=manifest, container=container)
        self._client._check_200_response(response)
