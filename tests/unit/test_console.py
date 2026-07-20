"""Unit tests for margot.console module."""

from io import StringIO

from pytest import fixture, raises
from rich.console import Console
from typer import Exit

import margot.console as _console


@fixture()
def capture_console():
    """Replace _stdout and _stderr module references with StringIO-backed consoles for assertion."""
    out = StringIO()
    err = StringIO()
    # Replace the getter functions to return StringIO-backed consoles
    original_get_stdout = _console._get_stdout
    original_get_stderr = _console._get_stderr
    
    def mock_get_stdout():
        return Console(file=out)
    
    def mock_get_stderr():
        return Console(file=err)
    
    _console._get_stdout = mock_get_stdout
    _console._get_stderr = mock_get_stderr
    
    yield out, err
    
    _console._get_stdout = original_get_stdout
    _console._get_stderr = original_get_stderr


@fixture(autouse=False)
def reset_console():
    """Reset verbose and debug flags to default state."""
    _console.set_verbose(False)
    _console.set_debug(False)
    yield
    _console.set_verbose(False)
    _console.set_debug(False)


class TestVerboseControl:
    """Tests for set_verbose and is_verbose."""

    def test_set_verbose_true_enables_verbose(self, reset_console):
        """set_verbose(True) should make is_verbose() return True."""
        _console.set_verbose(True)
        assert _console.is_verbose() is True

    def test_set_verbose_false_disables_verbose(self, reset_console):
        """set_verbose(False) should make is_verbose() return False."""
        _console.set_verbose(True)
        _console.set_verbose(False)
        assert _console.is_verbose() is False

    def test_verbose_defaults_to_false(self):
        """is_verbose() should return False by default."""
        # Note: This test runs last or with fresh module state
        assert _console.is_verbose() is False


class TestDebugControl:
    """Tests for set_debug and is_debug."""

    def test_set_debug_true_enables_debug(self, reset_console):
        """set_debug(True) should make is_debug() return True."""
        _console.set_debug(True)
        assert _console.is_debug() is True

    def test_set_debug_true_also_enables_verbose(self, reset_console):
        """set_debug(True) should also set _verbose to True."""
        _console.set_debug(True)
        assert _console.is_verbose() is True
        assert _console.is_debug() is True

    def test_set_debug_false_disables_debug_only(self, reset_console):
        """set_debug(False) should set _debug to False but NOT reset _verbose."""
        _console.set_debug(True)
        assert _console.is_verbose() is True
        _console.set_debug(False)
        assert _console.is_debug() is False
        assert _console.is_verbose() is True  # Still verbose after disabling debug

    def test_set_debug_false_does_not_reset_independent_verbose(self, reset_console):
        """set_debug(False) should not reset _verbose if it was set independently."""
        _console.set_verbose(True)
        _console.set_debug(True)
        assert _console.is_verbose() is True
        assert _console.is_debug() is True
        _console.set_debug(False)
        assert _console.is_debug() is False
        assert _console.is_verbose() is True  # Independent verbose setting persists

    def test_debug_defaults_to_false(self):
        """is_debug() should return False by default."""
        assert _console.is_debug() is False


class TestSuccess:
    """Tests for success() output."""

    def test_success_writes_to_stdout(self, capture_console, reset_console):
        """success() should write to stdout, not stderr."""
        out, err = capture_console
        _console.success("Test success")
        out_text = out.getvalue()
        err_text = err.getvalue()

        assert "Test success" in out_text
        assert err_text == ""

    def test_success_always_shown(self, capture_console, reset_console):
        """success() should be shown regardless of verbose/debug flags."""
        out, err = capture_console
        _console.success("Success with no flags")
        assert "Success with no flags" in out.getvalue()

        out.seek(0)
        out.truncate(0)
        _console.set_verbose(True)
        _console.success("Success with verbose")
        assert "Success with verbose" in out.getvalue()


class TestWarning:
    """Tests for warning() output."""

    def test_warning_writes_to_stderr(self, capture_console, reset_console):
        """warning() should write to stderr, not stdout."""
        out, err = capture_console
        _console.warning("Test warning")
        out_text = out.getvalue()
        err_text = err.getvalue()

        assert out_text == ""
        assert "Test warning" in err_text

    def test_warning_includes_prefix(self, capture_console, reset_console):
        """warning() output should include 'Warning:' prefix."""
        out, err = capture_console
        _console.warning("Test warning")
        err_text = err.getvalue()

        assert "Warning:" in err_text
        assert "Test warning" in err_text

    def test_warning_always_shown(self, capture_console, reset_console):
        """warning() should be shown regardless of verbose/debug flags."""
        out, err = capture_console
        _console.warning("Warning with no flags")
        assert "Warning:" in err.getvalue()


class TestInfo:
    """Tests for info() output."""

    def test_info_not_shown_without_verbose(self, capture_console, reset_console):
        """info() should produce no output when verbose=False."""
        out, err = capture_console
        _console.info("Test info")
        err_text = err.getvalue()

        assert err_text == ""

    def test_info_shown_with_verbose(self, capture_console, reset_console):
        """info() should write to stderr when verbose=True."""
        out, err = capture_console
        _console.set_verbose(True)
        _console.info("Test info")
        err_text = err.getvalue()
        out_text = out.getvalue()

        assert out_text == ""
        assert "Test info" in err_text

    def test_info_shown_with_debug(self, capture_console, reset_console):
        """info() should write to stderr when debug=True (debug implies verbose)."""
        out, err = capture_console
        _console.set_debug(True)
        _console.info("Test info")
        err_text = err.getvalue()
        out_text = out.getvalue()

        assert out_text == ""
        assert "Test info" in err_text


class TestDebug:
    """Tests for debug() output."""

    def test_debug_not_shown_without_debug(self, capture_console, reset_console):
        """debug() should produce no output when debug=False."""
        out, err = capture_console
        _console.debug("Test debug")
        err_text = err.getvalue()

        assert err_text == ""

    def test_debug_not_shown_with_verbose_only(self, capture_console, reset_console):
        """debug() should produce no output when verbose=True but debug=False."""
        out, err = capture_console
        _console.set_verbose(True)
        _console.debug("Test debug")
        err_text = err.getvalue()

        assert err_text == ""

    def test_debug_shown_with_debug(self, capture_console, reset_console):
        """debug() should write to stderr when debug=True."""
        out, err = capture_console
        _console.set_debug(True)
        _console.debug("Test debug")
        err_text = err.getvalue()
        out_text = out.getvalue()

        assert out_text == ""
        assert "Test debug" in err_text
        assert "debug:" in err_text

    def test_debug_shown_with_debug_prefix(self, capture_console, reset_console):
        """debug() output should include 'debug:' prefix."""
        out, err = capture_console
        _console.set_debug(True)
        _console.debug("Test debug message")
        err_text = err.getvalue()

        assert "debug:" in err_text
        assert "Test debug message" in err_text


class TestFatal:
    """Tests for fatal() output and exit."""

    def test_fatal_writes_to_stderr(self, capture_console, reset_console):
        """fatal() should write to stderr, not stdout."""
        out, err = capture_console
        with raises(Exit) as exc_info:
            _console.fatal("Test error")
        out_text = out.getvalue()
        err_text = err.getvalue()

        assert out_text == ""
        assert "Test error" in err_text
        assert exc_info.value.exit_code == 1

    def test_fatal_includes_error_prefix(self, capture_console, reset_console):
        """fatal() output should include 'Error:' prefix."""
        out, err = capture_console
        with raises(Exit):
            _console.fatal("Test error")
        err_text = err.getvalue()

        assert "Error:" in err_text
        assert "Test error" in err_text

    def test_fatal_raises_exit_with_code_1(self, reset_console):
        """fatal() should raise Exit(1)."""
        with raises(Exit) as exc_info:
            _console.fatal("Fatal error")
        assert exc_info.value.exit_code == 1

    def test_fatal_is_ignored_outside_try(self, reset_console):
        """fatal() raises Exit, so execution stops."""
        raised = False
        try:
            _console.fatal("This stops execution")
        except Exit:
            raised = True
        assert raised is True


class TestInteraction:
    """Tests for interactions between console functions."""

    def test_verbose_then_debug_then_disable_debug(self, reset_console):
        """Sequence: verbose on, debug on, debug off."""
        _console.set_verbose(True)
        assert _console.is_verbose() is True
        assert _console.is_debug() is False

        _console.set_debug(True)
        assert _console.is_verbose() is True
        assert _console.is_debug() is True

        _console.set_debug(False)
        assert _console.is_verbose() is True
        assert _console.is_debug() is False

    def test_debug_then_disable_debug_then_disable_verbose(self, reset_console):
        """Sequence: debug on, debug off, verbose off."""
        _console.set_debug(True)
        assert _console.is_verbose() is True
        assert _console.is_debug() is True

        _console.set_debug(False)
        assert _console.is_verbose() is True
        assert _console.is_debug() is False

        _console.set_verbose(False)
        assert _console.is_verbose() is False
        assert _console.is_debug() is False

    def test_all_output_functions_independent(self, capture_console, reset_console):
        """All output functions (success, warning, info, debug) should work independently."""
        out, err = capture_console
        _console.set_verbose(True)
        _console.set_debug(True)

        _console.success("Success")
        _console.warning("Warning")
        _console.info("Info")
        _console.debug("Debug")

        out_text = out.getvalue()
        err_text = err.getvalue()

        assert "Success" in out_text
        assert "Warning" in err_text
        assert "Info" in err_text
        assert "Debug" in err_text
