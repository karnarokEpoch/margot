"""Unit tests for infra/templating.py Jinja2 rendering helpers."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from pytest import fixture, raises

from margot.domain.metadata import build_jinja2_context, load_margo_yaml
from margot.infra.templating import render_template_file, render_template_string


@fixture
def mock_console(mocker: Any) -> MagicMock:
    """Mock console.debug for assertion without capturing output."""
    return mocker.patch("margot.infra.templating.console.debug")


@fixture
def margo_project(tmp_path: Path) -> Path:
    """Create a minimal project with a margo.yaml holding a compose component."""
    (tmp_path / "margo.yaml").write_text("""apiVersion: v1
id: testapp
name: testapp
description: Test application
version: 1.0.0
repository: public.ecr.aws/g2n4p2m7/margo
compose:
  directory: compose
  version: 1.0.0
""")
    return tmp_path


class TestRenderTemplateString:
    """Tests for render_template_string."""

    def test_renders_context_values(self, mock_console: MagicMock) -> None:
        """Should substitute context variables into the template."""
        rendered = render_template_string("id: {{ manifest.id }}", {"manifest": {"id": "testapp"}}, source_label="app.yaml.jinja")

        assert rendered == "id: testapp"

    def test_renders_template_without_variables(self, mock_console: MagicMock) -> None:
        """Should return the template unchanged when it has no placeholders."""
        assert render_template_string("kind: ApplicationDescription", {}, source_label="app.yaml.jinja") == (
            "kind: ApplicationDescription"
        )

    def test_unresolved_variable_raises_with_source_label(self, mock_console: MagicMock) -> None:
        """Should raise ValueError naming the source label on an undefined variable."""
        with raises(ValueError, match=r"Unresolved Jinja2 variable in app.yaml.jinja:"):
            render_template_string("id: {{ manifest.missing }}", {"manifest": {}}, source_label="app.yaml.jinja")

    def test_unresolved_variable_in_image_replace_label(self, mock_console: MagicMock) -> None:
        """Should use the caller's label — build reports image.replace failures this way."""
        with raises(ValueError, match=r"Unresolved Jinja2 variable in image.replace:"):
            render_template_string("{{ manifest.nope.deeper }}", {"manifest": {}}, source_label="image.replace")

    def test_renders_margo_yaml_context(self, margo_project: Path, mock_console: MagicMock) -> None:
        """Should render the real build_jinja2_context payload."""
        meta = load_margo_yaml(str(margo_project / "margo.yaml"))
        context = build_jinja2_context(meta, global_repository=meta.repository)

        rendered = render_template_string("{{ manifest.compose.ref }}", context, source_label="app.yaml.jinja")

        assert rendered == "public.ecr.aws/g2n4p2m7/margo:1.0.0"

    def test_emits_debug_log(self, mock_console: MagicMock) -> None:
        """Should log the rendered source at debug level."""
        render_template_string("static", {}, source_label="app.yaml.jinja")

        mock_console.assert_called_once_with("Render template: app.yaml.jinja")


class TestRenderTemplateFile:
    """Tests for render_template_file."""

    def test_renders_file_content(self, tmp_path: Path, mock_console: MagicMock) -> None:
        """Should read the file and render it with the given context.

        Jinja2's default ``keep_trailing_newline=False`` drops the final newline — the
        same behavior `build` has always had, kept byte-for-byte by this extraction.
        """
        template = tmp_path / "app.yaml.jinja"
        template.write_text("name: {{ manifest.name }}\n", encoding="utf-8")

        rendered = render_template_file(str(template), {"manifest": {"name": "testapp"}})

        assert rendered == "name: testapp"

    def test_defaults_source_label_to_file_name(self, tmp_path: Path, mock_console: MagicMock) -> None:
        """Should name the file in the error when no label is given."""
        template = tmp_path / "app.yaml.jinja"
        template.write_text("{{ manifest.missing }}", encoding="utf-8")

        with raises(ValueError, match=r"Unresolved Jinja2 variable in app.yaml.jinja:"):
            render_template_file(str(template), {"manifest": {}})

    def test_explicit_source_label_overrides_file_name(self, tmp_path: Path, mock_console: MagicMock) -> None:
        """Should prefer an explicit source label over the file name."""
        template = tmp_path / "weird-name.tmpl"
        template.write_text("{{ manifest.missing }}", encoding="utf-8")

        with raises(ValueError, match=r"Unresolved Jinja2 variable in app.yaml.jinja:"):
            render_template_file(str(template), {"manifest": {}}, source_label="app.yaml.jinja")

    def test_missing_file_raises_os_error(self, tmp_path: Path, mock_console: MagicMock) -> None:
        """Should propagate the filesystem error for a missing template."""
        with raises(OSError, match="No such file"):
            render_template_file(str(tmp_path / "absent.jinja"), {})
