from typer.testing import CliRunner

from margot.main import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "margot 0.1.0" in result.output


def test_hello() -> None:
    result = runner.invoke(app, ["hello"])
    assert result.exit_code == 0
    assert "margot" in result.output
