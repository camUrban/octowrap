import sys
from unittest.mock import MagicMock

import pytest

import octowrap.rewrap as mod

# Accessing _getch directly is needed to test the platform specific implementation.
# noinspection PyProtectedMember
from octowrap.rewrap import (
    _getch,
    colorize,
    prompt_user,
    show_block_diff,
)


class TestColorize:
    def test_known_color(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("hello", "red")
        assert result == "\033[91mhello\033[0m"

    def test_bold(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("title", "bold")
        assert result == "\033[1mtitle\033[0m"

    def test_unknown_color_still_resets(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("text", "nonexistent")
        assert result == "text\033[0m"

    def test_empty_string(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("", "green")
        assert result == "\033[92m\033[0m"

    def test_disabled_returns_plain_text(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        assert colorize("hello", "red") == "hello"
        assert colorize("title", "bold") == "title"
        assert colorize("", "green") == ""


class TestShowBlockDiff:
    def test_no_changes_returns_false(self, capsys):
        lines = ["# hello world"]
        assert show_block_diff(lines, lines, 0) is False
        assert capsys.readouterr().out == ""

    def test_changes_returns_true(self, capsys):
        original = ["# hello", "# world"]
        new = ["# hello world"]
        assert show_block_diff(original, new, 0) is True

    def test_output_contains_original_and_new(self, capsys):
        original = ["# old line"]
        new = ["# new line"]
        show_block_diff(original, new, 5)
        out = capsys.readouterr().out
        assert "- # old line" in out
        assert "+ # new line" in out

    def test_output_contains_line_numbers(self, capsys):
        original = ["# a"]
        new = ["# b"]
        show_block_diff(original, new, 9)
        out = capsys.readouterr().out
        # start_line is 0 indexed, display is 1 indexed
        assert "Lines 10-10:" in out

    def test_output_contains_filepath(self, capsys):
        original = ["# a"]
        new = ["# b"]
        show_block_diff(original, new, 0, filepath="src/example.py")
        out = capsys.readouterr().out
        assert "src/example.py" in out
        assert "Lines 1-1:" in out

    def test_no_filepath_omits_prefix(self, capsys):
        original = ["# a"]
        new = ["# b"]
        show_block_diff(original, new, 0)
        out = capsys.readouterr().out
        assert out.lstrip().startswith("\n") or "Lines 1-1:" in out
        # Should not have a path prefix before "Lines"
        for line in out.splitlines():
            if "Lines" in line:
                stripped = line.lstrip()
                # Remove ANSI codes for comparison
                import re

                clean = re.sub(r"\033\[[0-9;]*m", "", stripped)
                assert clean.startswith("Lines")


class TestGetch:
    """Tests for _getch(), the platform specific single keypress reader.

    _getch uses msvcrt on Windows and termios/tty on Unix (imported
    conditionally at module level).  The skipif markers ensure each
    platform native test only runs where the real modules exist.
    test_non_native_platform covers the opposite branch by monkeypatching
    sys.platform and faking the missing modules.
    """

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only path")
    def test_windows_msvcrt(self, monkeypatch):
        """On Windows, _getch delegates to msvcrt.getwch."""
        import msvcrt

        monkeypatch.setattr(msvcrt, "getwch", lambda: "k")
        assert _getch() == "k"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_termios(self, monkeypatch):
        """On Unix, _getch uses termios/tty to read one character."""
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", lambda n: "k")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == "k"

    def test_non_native_platform(self, monkeypatch):
        """Covers the branch for the platform we are NOT running on.

        Since the conditional top level imports only define the native
        platform's modules, we inject fake modules for the other platform
        directly onto the rewrap module.
        """
        if sys.platform == "win32":
            # We're on Windows, so fake the Unix path.
            monkeypatch.setattr(sys, "platform", "linux")
            fake_termios = MagicMock()
            fake_termios.tcgetattr.return_value = []
            # termios/tty don't exist on the module on Windows, so inject them.
            monkeypatch.setattr(mod, "termios", fake_termios, raising=False)
            monkeypatch.setattr(mod, "tty", MagicMock(), raising=False)
            monkeypatch.setattr(
                "sys.stdin",
                MagicMock(
                    fileno=MagicMock(return_value=0), read=MagicMock(return_value="z")
                ),
            )
            assert _getch() == "z"
        else:
            # We're on Unix, so fake the Windows path.
            monkeypatch.setattr(sys, "platform", "win32")
            fake_msvcrt = MagicMock()
            fake_msvcrt.getwch.return_value = "z"
            # msvcrt doesn't exist on the module on Unix, so inject it.
            monkeypatch.setattr(mod, "msvcrt", fake_msvcrt, raising=False)
            assert _getch() == "z"


class TestPromptUser:
    def test_accept(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "a")
        assert prompt_user() == "a"

    def test_skip(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "s")
        assert prompt_user() == "s"

    def test_quit(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "q")
        assert prompt_user() == "q"

    def test_accept_all(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "A")
        assert prompt_user() == "A"

    def test_lowercase_a_is_single_accept(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "a")
        assert prompt_user() == "a"

    def test_invalid_then_valid(self, monkeypatch):
        responses = iter(["x", "z", "a"])
        monkeypatch.setattr(mod, "_getch", lambda: next(responses))
        assert prompt_user() == "a"

    def test_eof_returns_quit(self, monkeypatch):
        def raise_eof():
            raise EOFError

        monkeypatch.setattr(mod, "_getch", raise_eof)
        assert prompt_user() == "q"

    def test_keyboard_interrupt_returns_quit(self, monkeypatch):
        def raise_interrupt():
            raise KeyboardInterrupt

        monkeypatch.setattr(mod, "_getch", raise_interrupt)
        assert prompt_user() == "q"

    def test_exclude(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "e")
        assert prompt_user() == "e"

    def test_exclude_uppercase(self, monkeypatch):
        monkeypatch.setattr(mod, "_getch", lambda: "E")
        assert prompt_user() == "e"
