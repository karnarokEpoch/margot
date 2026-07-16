from importlib.metadata import PackageNotFoundError

from typer.testing import CliRunner

from margot.commands.version import get_version
from margot.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("margot ")


def test_get_version_installed(mocker) -> None:
    mocker.patch("margot.commands.version.version", return_value="1.2.3")
    assert get_version() == "1.2.3"


def test_get_version_not_installed(mocker) -> None:
    mocker.patch("margot.commands.version.version", side_effect=PackageNotFoundError)
    assert get_version() == "unknown"
