"""Integration tests: pull a margo artifact, then describe and verify it in place (Sprint 12).

The registry is faked at the oras client boundary. `pull_artifact` and its margo handler
run for real, and the fake `client.pull` writes the layers the way oras would.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from margot.domain.layers import (
    MARGO_DESCRIPTION_MEDIA_TYPE,
    MARGO_RESOURCE_ANNOTATION,
    MARGO_RESOURCE_ANNOTATION_VALUE,
    MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
)
from margot.services import describe as describe_service
from margot.services import pull as pull_service
from margot.services import verify as verify_service

URI = "public.ecr.aws/g2n4p2m7/margo:1.0.0"

VALID_APP_YAML = """apiVersion: v1
kind: ApplicationDescription
id: hello-world
metadata:
  name: Hello World
  description: A sample application
  version: 1.0.0
  catalog:
    application:
      icon: https://example.com/icon.png
    organization:
      - name: Example Corp
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: hello-world-compose
        properties:
          repository: oci://example.com/compose/hello-world
          revision: 1.0.0
"""


def _margo_manifest() -> dict[str, Any]:
    """Return a margo artifact manifest with a descriptor layer and one resource layer."""
    return {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "artifactType": "application/vnd.margo.app.v1+json",
        "config": {
            "mediaType": "application/vnd.oci.empty.v1+json",
            "digest": "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
            "size": 2,
        },
        "layers": [
            {
                "mediaType": MARGO_DESCRIPTION_MEDIA_TYPE,
                "digest": "sha256:" + "1" * 64,
                "annotations": {"org.opencontainers.image.title": "app.yaml"},
            },
            {
                "mediaType": MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
                "digest": "sha256:" + "2" * 64,
                "annotations": {
                    "org.opencontainers.image.title": "resources/icon.png",
                    MARGO_RESOURCE_ANNOTATION: MARGO_RESOURCE_ANNOTATION_VALUE,
                },
            },
        ],
    }


def _fake_oras_pull(uri: str, outdir: str) -> list[str]:
    """Write the artifact layers into outdir as oras would, and return their paths."""
    del uri
    root = Path(outdir)
    (root / "resources").mkdir(parents=True, exist_ok=True)
    app_yaml = root / "app.yaml"
    app_yaml.write_text(VALID_APP_YAML, encoding="utf-8")
    icon = root / "resources" / "icon.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return [str(app_yaml), str(icon)]


class TestPullThenInspect:
    """A pulled margo artifact can be described and verified where it landed."""

    def test_pulled_artifact_is_described_and_verified_without_margo_yaml(self, mocker: Any, tmp_path: Path) -> None:
        """Should pull app.yaml and resources, write no margo.yaml, and let describe and verify run in place."""
        outdir = tmp_path / "pulled"
        client = MagicMock()
        client.get_manifest.return_value = _margo_manifest()
        client.pull.side_effect = _fake_oras_pull
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.OrasClient", return_value=client)

        pulled = pull_service.pull_artifact(URI, outdir=str(outdir))

        assert pulled == [str(outdir / "app.yaml"), str(outdir / "resources" / "icon.png")]
        assert (outdir / "app.yaml").is_file()
        assert (outdir / "resources" / "icon.png").is_file()
        assert not (outdir / "margo.yaml").exists()

        loaded = describe_service.load_descriptor(str(outdir))
        assert loaded.meta is None
        assert loaded.rendered is False
        assert loaded.descriptor["metadata"]["name"] == "Hello World"

        result = verify_service.verify(project_dir=str(outdir))
        assert result.passed is True
        assert result.schema_a_results == []
        assert result.schema_b_results == []
