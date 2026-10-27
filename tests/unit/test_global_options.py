"""Unit tests for global_options callback: --debug and --verbose branches."""

from typing import Any

from margot.commands.global_options import global_options


class TestGlobalOptions:
    """Tests for the global_options callback logic."""

    def test_debug_flag_calls_set_debug(self, mocker: Any) -> None:
        """--debug should call set_debug(True) and NOT set_verbose."""
        mock_set_debug = mocker.patch("margot.commands.global_options.set_debug")
        mock_set_verbose = mocker.patch("margot.commands.global_options.set_verbose")

        global_options(version_flag=False, verbose=False, debug=True)

        mock_set_debug.assert_called_once_with(True)
        mock_set_verbose.assert_not_called()

    def test_verbose_flag_calls_set_verbose(self, mocker: Any) -> None:
        """--verbose should call set_verbose(True) and NOT set_debug."""
        mock_set_debug = mocker.patch("margot.commands.global_options.set_debug")
        mock_set_verbose = mocker.patch("margot.commands.global_options.set_verbose")

        global_options(version_flag=False, verbose=True, debug=False)

        mock_set_verbose.assert_called_once_with(True)
        mock_set_debug.assert_not_called()

    def test_no_flags_calls_neither(self, mocker: Any) -> None:
        """No flags should explicitly reset debug and verbose to False."""
        mock_set_debug = mocker.patch("margot.commands.global_options.set_debug")
        mock_set_verbose = mocker.patch("margot.commands.global_options.set_verbose")

        global_options(version_flag=False, verbose=False, debug=False)

        mock_set_debug.assert_called_once_with(False)
        mock_set_verbose.assert_called_once_with(False)

    def test_debug_takes_precedence_over_verbose(self, mocker: Any) -> None:
        """--debug + --verbose should call set_debug only (elif branch skipped)."""
        mock_set_debug = mocker.patch("margot.commands.global_options.set_debug")
        mock_set_verbose = mocker.patch("margot.commands.global_options.set_verbose")

        global_options(version_flag=False, verbose=True, debug=True)

        mock_set_debug.assert_called_once_with(True)
        mock_set_verbose.assert_not_called()


    def test_no_color_flag_calls_set_no_color(self, mocker: Any) -> None:
        """--no-color should enable color suppression."""
        mock_set_no_color = mocker.patch("margot.commands.global_options.set_no_color")

        global_options(version_flag=False, verbose=False, debug=False, no_color=True)

        mock_set_no_color.assert_called_once_with(True)

    def test_no_color_environment_is_presence_based(self, mocker: Any, monkeypatch: Any) -> None:
        """An empty NO_COLOR value still disables color because presence is the contract."""
        mock_set_no_color = mocker.patch("margot.commands.global_options.set_no_color")
        monkeypatch.setenv("NO_COLOR", "")

        global_options(version_flag=False, verbose=False, debug=False, no_color=False)

        mock_set_no_color.assert_called_once_with(True)
