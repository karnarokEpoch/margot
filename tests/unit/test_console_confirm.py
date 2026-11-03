"""Unit tests for console.confirm and console.is_interactive."""

from io import StringIO
from typing import Any

from pytest import mark

from margot import console


class _Tty(StringIO):
    """A StringIO that claims to be a terminal."""

    def isatty(self) -> bool:
        return True


class TestConfirm:
    """Reads one line from stdin; only an affirmative answer proceeds."""

    @mark.parametrize("answer", ["y\n", "Y\n", "yes\n", "YES\n", "  yes  \n"])
    def test_affirmative_answers_are_accepted(self, monkeypatch: Any, answer: str) -> None:
        """Should return True for y / yes in any case, ignoring surrounding spaces."""
        monkeypatch.setattr("sys.stdin", StringIO(answer))

        assert console.confirm("Install?") is True

    @mark.parametrize("answer", ["n\n", "no\n", "\n", "maybe\n", ""])
    def test_everything_else_is_no(self, monkeypatch: Any, answer: str) -> None:
        """Should return False for any other answer, including an empty line and EOF."""
        monkeypatch.setattr("sys.stdin", StringIO(answer))

        assert console.confirm("Install?") is False

    def test_question_is_written_to_stderr(self, monkeypatch: Any, capsys: Any) -> None:
        """Should print the question to stderr, never to stdout."""
        monkeypatch.setattr("sys.stdin", StringIO("n\n"))

        console.confirm("Install 1 component(s) on this host? [y/N]")

        captured = capsys.readouterr()
        assert "Install 1 component(s) on this host? [y/N]" in captured.err
        assert captured.out == ""


class TestIsInteractive:
    """TTY check used before asking for confirmation."""

    def test_pipe_is_not_interactive(self, monkeypatch: Any) -> None:
        """Should return False when stdin is not a terminal."""
        monkeypatch.setattr("sys.stdin", StringIO(""))

        assert console.is_interactive() is False

    def test_terminal_is_interactive(self, monkeypatch: Any) -> None:
        """Should return True when stdin is a terminal."""
        monkeypatch.setattr("sys.stdin", _Tty(""))

        assert console.is_interactive() is True
