"""Jinja2 rendering helpers shared by build, verify and describe.

Every template margot renders uses ``StrictUndefined``: an unresolved variable is a
build/verify failure, never a silently empty string.
"""

from pathlib import Path

from jinja2 import Environment, StrictUndefined, UndefinedError

from margot import console


def render_template_string(template: str, context: dict, *, source_label: str) -> str:
    """Render a Jinja2 template string with StrictUndefined.

    Args:
        template: Template source.
        context: Plain-data rendering context.
        source_label: Label used in the error message (e.g. ``"app.yaml.jinja"``).

    Returns:
        The rendered text.

    Raises:
        ValueError: If a template variable cannot be resolved.
    """
    console.debug(f"Render template: {source_label}")
    try:
        environment = Environment(undefined=StrictUndefined)  # noqa: S701
        return environment.from_string(template).render(context)
    except UndefinedError as e:
        raise ValueError(f"Unresolved Jinja2 variable in {source_label}: {e}") from e


def render_template_file(path: str, context: dict, *, source_label: str | None = None) -> str:
    """Render a Jinja2 template file with StrictUndefined.

    Args:
        path: Path to the template file.
        context: Plain-data rendering context.
        source_label: Label used in the error message. Defaults to the file name.

    Returns:
        The rendered text.

    Raises:
        ValueError: If a template variable cannot be resolved.
    """
    file_path = Path(path)
    label = source_label or file_path.name
    return render_template_string(file_path.read_text(encoding="utf-8"), context, source_label=label)
