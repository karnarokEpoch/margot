"""E2E tests for describe and verify without margo.yaml (Sprint 12 fallback search)."""

import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture
from typer.testing import CliRunner

from margot.domain.layers import (
    MARGO_DESCRIPTION_MEDIA_TYPE,
    MARGO_RESOURCE_ANNOTATION,
    MARGO_RESOURCE_ANNOTATION_VALUE,
    MARGO_RESOURCE_FALLBACK_MEDIA_TYPE,
)
from margot.main import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

NOT_RENDERABLE_MESSAGE = "Jinja2 templates require margo.yaml context"
URI = "public.ecr.aws/g2n4p2m7/margo:1.0.0"

MARGO_YAML = """apiVersion: v1
id: hello-world
name: Hello World
description: A sample application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: compose
  version: 1.0.0
"""

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

TEMPLATED_APP_YAML = """apiVersion: v1
kind: ApplicationDescription
id: {{ manifest.id }}
metadata:
  name: {{ manifest.name }}
  description: {{ manifest.description }}
  version: {{ manifest.version }}
  catalog:
    application:
      icon: https://example.com/icon.png
    organization:
      - name: Example Corp
deploymentProfiles:
  - type: compose
    id: default
    components:
      - name: {{ manifest.compose.component }}
        properties:
          repository: oci://example.com/compose/hello-world
          revision: 1.0.0
"""


def _named(name: str) -> str:
    """Return the valid descriptor with a different metadata.name, to tell copies apart in output."""
    return VALID_APP_YAML.replace("  name: Hello World\n", f"  name: {name}\n")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text for plain-string assertions."""
    return _ANSI_RE.sub("", text)


def _output(result: Any) -> str:
    """Combine stdout and stderr into plain, ANSI-free text."""
    return _strip_ansi(result.stdout + (result.stderr or ""))


@fixture
def bare_cwd(tmp_path: Path, monkeypatch: Any) -> Path:
    """Run from an empty directory with no margo.yaml; the project is the cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@fixture
def elsewhere(tmp_path: Path, monkeypatch: Any) -> Path:
    """Run from an unrelated directory so --project-dir is the only way to reach the project."""
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path / "project"


class TestRootAppYamlWithoutMargoYaml:
    """A bare app.yaml at the project root resolves with no margo.yaml."""

    def test_verify_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should pass verify when run from a directory holding only app.yaml."""
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should describe the application when run from a directory holding only app.yaml."""
        (bare_cwd / "app.yaml").write_text(_named("Root App"), encoding="utf-8")

        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 0
        assert "Root App" in _output(result)

    def test_verify_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should pass verify when --project-dir points at a directory holding only app.yaml."""
        elsewhere.mkdir()
        (elsewhere / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should describe the application when --project-dir points at a directory holding only app.yaml."""
        elsewhere.mkdir()
        (elsewhere / "app.yaml").write_text(_named("Root App"), encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "Root App" in _output(result)


class TestMargoSubdirAppYamlWithoutMargoYaml:
    """The margo/app.yaml layout resolves with no margo.yaml, and the root copy wins when both exist."""

    def test_verify_exits_0_from_the_project_directory(self, bare_cwd: Path) -> None:
        """Should pass verify on margo/app.yaml when no margo.yaml and no root app.yaml exist."""
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_describe_exits_0_with_project_dir(self, elsewhere: Path) -> None:
        """Should describe margo/app.yaml when --project-dir points at the project."""
        (elsewhere / "margo").mkdir(parents=True)
        (elsewhere / "margo" / "app.yaml").write_text(_named("Subdir App"), encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        assert "Subdir App" in _output(result)

    def test_root_app_yaml_wins_over_margo_subdir_for_verify(self, bare_cwd: Path) -> None:
        """Should verify the valid root app.yaml and ignore a broken margo/app.yaml beside it."""
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 0
        assert "PASS" in _output(result)

    def test_root_app_yaml_wins_over_margo_subdir_for_describe(self, bare_cwd: Path) -> None:
        """Should describe the root app.yaml and not the margo/app.yaml copy."""
        (bare_cwd / "app.yaml").write_text(_named("Root App"), encoding="utf-8")
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(_named("Subdir App"), encoding="utf-8")

        result = runner.invoke(app, ["describe"])
        plain = _output(result)

        assert result.exit_code == 0
        assert "Root App" in plain
        assert "Subdir App" not in plain


class TestJinjaWithoutMargoYamlExits3:
    """A template cannot render without margo.yaml, so the fallback reports an actionable error."""

    def test_verify_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 with the render-context hint when verify finds app.yaml.jinja and no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 with the render-context hint when describe finds app.yaml.jinja and no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_jinja_in_margo_subdir_without_margo_yaml_exits_3(self, elsewhere: Path) -> None:
        """Should exit 3 when the only template sits in margo/ and --project-dir points at the project."""
        (elsewhere / "margo").mkdir(parents=True)
        (elsewhere / "margo" / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe", "--project-dir", str(elsewhere)])

        assert result.exit_code == 3
        assert NOT_RENDERABLE_MESSAGE in _output(result)

    def test_describe_without_any_descriptor_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 and name both static paths searched when no descriptor exists."""
        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 3
        assert "Searched: app.yaml, margo/app.yaml" in _output(result)


class TestFallbackJson:
    """--json on the fallback path: a document on success, the error envelope on failure."""

    def test_verify_json_on_root_app_yaml_is_valid_json(self, bare_cwd: Path) -> None:
        """Should print a passing verify document on stdout and nothing on stderr."""
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--json"])

        assert result.exit_code == 0
        assert json.loads(result.stdout)["passed"] is True
        assert result.stderr == ""

    def test_describe_json_on_margo_subdir_is_valid_json(self, elsewhere: Path) -> None:
        """Should print the describe document as valid JSON for margo/app.yaml."""
        (elsewhere / "margo").mkdir(parents=True)
        (elsewhere / "margo" / "app.yaml").write_text(_named("Subdir App"), encoding="utf-8")

        result = runner.invoke(app, ["describe", "--json", "--project-dir", str(elsewhere)])

        assert result.exit_code == 0
        json.loads(result.stdout)
        assert "Subdir App" in result.stdout

    def test_verify_json_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should emit the stderr error envelope with code 3 for a template with no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify", "--json"])

        assert result.exit_code == 3
        assert result.stdout == ""
        envelope = json.loads(result.stderr)
        assert envelope["error"] is True
        assert envelope["code"] == 3
        assert NOT_RENDERABLE_MESSAGE in envelope["message"]

    def test_describe_json_jinja_without_margo_yaml_exits_3(self, bare_cwd: Path) -> None:
        """Should emit the stderr error envelope with code 3 when describe meets a template with no margo.yaml."""
        (bare_cwd / "app.yaml.jinja").write_text(TEMPLATED_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe", "--json"])

        assert result.exit_code == 3
        assert result.stdout == ""
        envelope = json.loads(result.stderr)
        assert envelope["error"] is True
        assert envelope["code"] == 3
        assert NOT_RENDERABLE_MESSAGE in envelope["message"]


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


class TestPullThenInspectCLI:
    """The full journey: pull a margo artifact, then describe and verify it where it landed."""

    def test_pull_then_describe_and_verify_exit_0_without_margo_yaml(self, mocker: Any, bare_cwd: Path) -> None:
        """Should exit 0 at every step and leave no margo.yaml behind."""
        client = MagicMock()
        client.get_manifest.return_value = _margo_manifest()
        client.pull.side_effect = _fake_oras_pull
        mocker.patch("margot.services.pull.credentials.check_credentials")
        mocker.patch("margot.services.pull.OrasClient", return_value=client)
        project = bare_cwd / "pulled"

        pulled = runner.invoke(app, ["pull", URI, "--output", str(project)])
        described = runner.invoke(app, ["describe", "--project-dir", str(project)])
        verified = runner.invoke(app, ["verify", "--project-dir", str(project)])

        assert pulled.exit_code == 0
        assert (project / "app.yaml").is_file()
        assert (project / "resources" / "icon.png").is_file()
        assert described.exit_code == 0
        assert "Hello World" in _output(described)
        assert verified.exit_code == 0
        assert "PASS" in _output(verified)
        assert not (project / "margo.yaml").exists()
        assert not (bare_cwd / "margo.yaml").exists()


class TestMargoYamlPresentIsUnchanged:
    """With margo.yaml present, resolution stays on the margo.yaml path and never falls back."""

    def test_margo_yaml_directory_is_honoured_over_margo_subdir(self, bare_cwd: Path) -> None:
        """Should resolve margo.yaml's configured directory and never read the margo/ default."""
        (bare_cwd / "margo.yaml").write_text("directory: source\n" + MARGO_YAML, encoding="utf-8")
        (bare_cwd / "source").mkdir()
        (bare_cwd / "source" / "app.yaml").write_text(_named("Configured App"), encoding="utf-8")
        (bare_cwd / "margo").mkdir()
        (bare_cwd / "margo" / "app.yaml").write_text(VALID_APP_YAML.replace("  version: 1.0.0\n", ""), encoding="utf-8")

        verified = runner.invoke(app, ["verify"])
        described = runner.invoke(app, ["describe"])

        assert verified.exit_code == 0
        assert described.exit_code == 0
        assert "Configured App" in _output(described)

    def test_verify_margo_yaml_present_never_falls_back_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 instead of using a root app.yaml when margo.yaml names a missing source directory."""
        (bare_cwd / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["verify"])

        assert result.exit_code == 3
        assert "No app.yaml or app.yaml.jinja found in margo source directory." in _output(result)

    def test_describe_margo_yaml_present_never_falls_back_exits_3(self, bare_cwd: Path) -> None:
        """Should exit 3 instead of using a root app.yaml when margo.yaml names a missing source directory."""
        (bare_cwd / "margo.yaml").write_text(MARGO_YAML, encoding="utf-8")
        (bare_cwd / "app.yaml").write_text(VALID_APP_YAML, encoding="utf-8")

        result = runner.invoke(app, ["describe"])

        assert result.exit_code == 3
        assert "No app.yaml or app.yaml.jinja found in margo source directory." in _output(result)
