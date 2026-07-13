from importlib.metadata import PackageNotFoundError

from typer.testing import CliRunner

from margot.main import app, get_version

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.startswith("margot ")


def test_hello() -> None:
    result = runner.invoke(app, ["hello"])
    assert result.exit_code == 0
    assert "margot" in result.output


def test_get_version_installed(mocker) -> None:
    mocker.patch("margot.main.version", return_value="1.2.3")
    assert get_version() == "1.2.3"


def test_get_version_not_installed(mocker) -> None:
    mocker.patch("margot.main.version", side_effect=PackageNotFoundError)
    assert get_version() == "unknown"
