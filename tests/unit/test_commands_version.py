"""Unit tests for commands/version.py."""

from importlib.metadata import PackageNotFoundError
from pathlib import Path
import tomllib
from unittest.mock import patch

from margot.commands.version import get_version


class TestGetVersion:
    """Tests for get_version()."""

    def test_get_version_queries_margo_tooling_distribution(self) -> None:
        """Should query importlib.metadata.version with 'margo-tooling' distribution name."""
        with patch("margot.commands.version.version") as mock_version:
            mock_version.return_value = "1.2.3"
            result = get_version()

            assert result == "1.2.3"
            mock_version.assert_called_once_with("margo-tooling")

    def test_get_version_returns_unknown_on_package_not_found(self) -> None:
        """Should return 'unknown' when package is not installed."""
        with patch("margot.commands.version.version") as mock_version:
            mock_version.side_effect = PackageNotFoundError("margo-tooling")
            result = get_version()

            assert result == "unknown"

    def test_get_version_matches_pyproject_name(self) -> None:
        """Should query the distribution name matching pyproject.toml [project] name field.

        Per pyproject.toml: name = "margo-tooling"
        This test dynamically verifies the correct name is used.
        """
        # Read pyproject.toml from repo root
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        with pyproject_path.open("rb") as f:
            pyproject = tomllib.load(f)

        expected_name = pyproject["project"]["name"]

        with patch("margot.commands.version.version") as mock_version:
            mock_version.return_value = "0.7.0"
            get_version()

            # Verify version() was called with the correct distribution name
            mock_version.assert_called_once_with(expected_name)

    def test_get_version_real_installation(self) -> None:
        """Should return a version string (or 'unknown') when running against real metadata.

        This test uses the actual importlib.metadata.version without mocking,
        so it verifies the real behavior in the test environment.
        """
        result = get_version()
        # Should return either a version string or 'unknown', not raise
        assert isinstance(result, str)
        assert len(result) > 0
