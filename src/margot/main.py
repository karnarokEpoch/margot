from rich import print as rprint
import typer

app = typer.Typer(name="margot", help="Margo application package developer CLI.", no_args_is_help=True)


@app.command()
def hello() -> None:
    """Say hello (smoke test)."""
    rprint("[bold green]margot[/bold green] is working!")


@app.callback(invoke_without_command=True)
def _version(
    version: bool = typer.Option(False, "--version", "-v", help="Print version and exit.", is_eager=True),
) -> None:
    if version:
        typer.echo("margot 0.1.0")
        raise typer.Exit


if __name__ == "__main__":
    app()
