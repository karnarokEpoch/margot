"""Dynaconf-based settings with layered priority configuration.

Priority (highest to lowest):
1. Explicit overrides via configure() (flag overrides from CLI)
2. MARGOT_* environment variables (e.g. MARGOT_REGISTRY, MARGOT_BUILD_DIR)
3. margot.yaml in current working directory (project-level descriptor)
4. ~/.config/margot/config.yaml (user-level defaults)
5. Built-in defaults (registry="", repository="", build_dir=".dist", run_dir=".run")
"""

from pathlib import Path

from dynaconf import Dynaconf

# Built-in defaults for all config keys
_DEFAULTS: dict[str, str] = {
    "REGISTRY": "",
    "REPOSITORY": "",
    "BUILD_DIR": ".dist",
    "RUN_DIR": ".run",
}

# Initialize dynaconf Settings with layered config files
Settings = Dynaconf(
    envvar_prefix="MARGOT",
    settings_file=[
        "margot.yaml",  # project-level (current working directory)
        str(Path.home() / ".config/margot/config.yaml"),  # user-level defaults
    ],
    environments=False,
    load_dotenv=False,
)


def get_settings() -> Dynaconf:
    """Return the Settings singleton.

    Returns:
        The global Settings object.
    """
    return Settings


def get(key: str, default: str | None = None) -> str | None:
    """Get a config value by key (case-insensitive).

    Applies built-in defaults if key is not found in Settings.

    Args:
        key: Configuration key (e.g. "build_dir", "registry").
        default: Fallback value if key is not found. Defaults to None.

    Returns:
        The config value, or default if not found.
    """
    key_upper = key.upper()
    # Try to get from Settings first, then check built-in defaults, then use provided default
    if Settings.exists(key_upper):
        return Settings.get(key_upper)
    if key_upper in _DEFAULTS:
        return _DEFAULTS[key_upper]
    return default


def configure(**overrides: str) -> None:
    """Apply explicit config overrides (highest priority).

    Used by the CLI command layer to inject flag values before calling services.

    Args:
        **overrides: Key=value pairs to override. Keys are case-insensitive.
                     Example: configure(build_dir="/tmp/build", registry="myregistry.com")
    """
    for key, value in overrides.items():
        Settings.set(key.upper(), value)
