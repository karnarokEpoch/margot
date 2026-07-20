"""Unit tests for config.py."""

import os
from pathlib import Path
from typing import Any

from dynaconf import Dynaconf
from pytest import fixture

from margot import config


@fixture
def isolated_config(monkeypatch: Any, tmp_path: Path) -> None:
    """Isolate config tests from real config files and env vars.

    - Monkeypatch HOME to a temp directory (prevents reading ~/.config/margot/config.yaml).
    - Monkeypatch CWD to a temp directory (prevents reading margot.yaml from project root).
    - Clear any MARGOT_* environment variables.
    - Recreate Settings to pick up isolated environment.
    """
    # Redirect HOME to temp dir to isolate from user's real config
    monkeypatch.setenv("HOME", str(tmp_path))

    # Change to temp directory to isolate from project-level margot.yaml
    monkeypatch.chdir(tmp_path)

    # Clear any existing MARGOT_* env vars
    for key in list(os.environ.keys()):
        if key.startswith("MARGOT_"):
            monkeypatch.delenv(key, raising=False)

    # Recreate Settings to pick up isolated environment and reload config files.
    # This ensures Settings starts fresh for each test.
    new_settings = Dynaconf(
        envvar_prefix="MARGOT",
        settings_file=[
            "margot.yaml",
            str(Path.home() / ".config/margot/config.yaml"),
        ],
        environments=False,
        load_dotenv=False,
    )
    monkeypatch.setattr(config, "Settings", new_settings)


class TestGetDefaults:
    """Tests for get() with default values."""

    def test_get_build_dir_default(self, isolated_config: None) -> None:
        """get("build_dir") should return ".dist" by default."""
        assert config.get("build_dir") == ".dist"

    def test_get_run_dir_default(self, isolated_config: None) -> None:
        """get("run_dir") should return ".run" by default."""
        assert config.get("run_dir") == ".run"

    def test_get_registry_default(self, isolated_config: None) -> None:
        """get("registry") should return "" by default."""
        assert config.get("registry") == ""

    def test_get_repository_default(self, isolated_config: None) -> None:
        """get("repository") should return "" by default."""
        assert config.get("repository") == ""

    def test_get_nonexistent_key_returns_none(self, isolated_config: None) -> None:
        """get() for a non-existent key with no default should return None."""
        assert config.get("nonexistent_key") is None

    def test_get_nonexistent_key_returns_provided_default(self, isolated_config: None) -> None:
        """get() for a non-existent key should return the provided default."""
        assert config.get("nonexistent_key", "my_default") == "my_default"


class TestEnvironmentVariables:
    """Tests for MARGOT_* environment variable overrides."""

    def test_margot_build_dir_env_var(self, isolated_config: None, monkeypatch: Any) -> None:
        """MARGOT_BUILD_DIR env var should override default."""
        monkeypatch.setenv("MARGOT_BUILD_DIR", "/tmp/custom_build")  # noqa: S108
        # Reload Settings to pick up the new env var
        new_settings = Dynaconf(
            envvar_prefix="MARGOT",
            settings_file=[
                "margot.yaml",
                str(Path.home() / ".config/margot/config.yaml"),
            ],
            environments=False,
            load_dotenv=False,
        )
        monkeypatch.setattr(config, "Settings", new_settings)
        assert config.get("build_dir") == "/tmp/custom_build"  # noqa: S108

    def test_margot_registry_env_var(self, isolated_config: None, monkeypatch: Any) -> None:
        """MARGOT_REGISTRY env var should override default."""
        monkeypatch.setenv("MARGOT_REGISTRY", "myregistry.com")
        new_settings = Dynaconf(
            envvar_prefix="MARGOT",
            settings_file=[
                "margot.yaml",
                str(Path.home() / ".config/margot/config.yaml"),
            ],
            environments=False,
            load_dotenv=False,
        )
        monkeypatch.setattr(config, "Settings", new_settings)
        assert config.get("registry") == "myregistry.com"

    def test_margot_repository_env_var(self, isolated_config: None, monkeypatch: Any) -> None:
        """MARGOT_REPOSITORY env var should override default."""
        monkeypatch.setenv("MARGOT_REPOSITORY", "myrepo/myapp")
        new_settings = Dynaconf(
            envvar_prefix="MARGOT",
            settings_file=[
                "margot.yaml",
                str(Path.home() / ".config/margot/config.yaml"),
            ],
            environments=False,
            load_dotenv=False,
        )
        monkeypatch.setattr(config, "Settings", new_settings)
        assert config.get("repository") == "myrepo/myapp"

    def test_margot_run_dir_env_var(self, isolated_config: None, monkeypatch: Any) -> None:
        """MARGOT_RUN_DIR env var should override default."""
        monkeypatch.setenv("MARGOT_RUN_DIR", "/tmp/custom_run")  # noqa: S108
        new_settings = Dynaconf(
            envvar_prefix="MARGOT",
            settings_file=[
                "margot.yaml",
                str(Path.home() / ".config/margot/config.yaml"),
            ],
            environments=False,
            load_dotenv=False,
        )
        monkeypatch.setattr(config, "Settings", new_settings)
        assert config.get("run_dir") == "/tmp/custom_run"  # noqa: S108


class TestConfigureOverrides:
    """Tests for configure() explicit overrides (highest priority)."""

    def test_configure_build_dir(self, isolated_config: None) -> None:
        """configure(build_dir=...) should set the override."""
        config.configure(build_dir="/tmp/build")  # noqa: S108
        assert config.get("build_dir") == "/tmp/build"  # noqa: S108

    def test_configure_registry(self, isolated_config: None) -> None:
        """configure(registry=...) should set the override."""
        config.configure(registry="myregistry.io")
        assert config.get("registry") == "myregistry.io"

    def test_configure_multiple_keys(self, isolated_config: None) -> None:
        """configure() should handle multiple keys at once."""
        config.configure(build_dir="/custom/build", repository="myrepo/app", run_dir="/custom/run")
        assert config.get("build_dir") == "/custom/build"
        assert config.get("repository") == "myrepo/app"
        assert config.get("run_dir") == "/custom/run"

    def test_configure_overrides_env_var(self, isolated_config: None, monkeypatch: Any) -> None:
        """configure() should have higher priority than env var."""
        monkeypatch.setenv("MARGOT_BUILD_DIR", "/env/build")
        new_settings = Dynaconf(
            envvar_prefix="MARGOT",
            settings_file=[
                "margot.yaml",
                str(Path.home() / ".config/margot/config.yaml"),
            ],
            environments=False,
            load_dotenv=False,
        )
        monkeypatch.setattr(config, "Settings", new_settings)
        config.configure(build_dir="/override/build")
        assert config.get("build_dir") == "/override/build"


class TestCaseInsensitivity:
    """Tests for case-insensitive key handling."""

    def test_get_lowercase_key(self, isolated_config: None) -> None:
        """get() should accept lowercase keys."""
        assert config.get("build_dir") == ".dist"

    def test_get_uppercase_key(self, isolated_config: None) -> None:
        """get() should accept uppercase keys."""
        assert config.get("BUILD_DIR") == ".dist"

    def test_configure_lowercase_key(self, isolated_config: None) -> None:
        """configure() should accept lowercase keys."""
        config.configure(build_dir="/tmp/build")  # noqa: S108
        assert config.get("BUILD_DIR") == "/tmp/build"  # noqa: S108

    def test_configure_uppercase_key(self, isolated_config: None) -> None:
        """configure() should accept uppercase keys."""
        config.configure(BUILD_DIR="/tmp/build")  # noqa: S108
        assert config.get("build_dir") == "/tmp/build"  # noqa: S108


class TestGetSettings:
    """Tests for get_settings()."""

    def test_get_settings_returns_singleton(self, isolated_config: None) -> None:
        """get_settings() should return the Settings singleton."""
        settings = config.get_settings()
        assert settings is config.Settings
