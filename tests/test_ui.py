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
        assert out.startswith("\n") or "Lines 1-1:" in out
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

    _getch uses msvcrt on Windows and termios/tty on Unix (imported locally inside the
    function).  The skipif markers ensure each platform native test only runs where the
    real modules exist; the dual-branch tests in TestGetchEscapeSequences cover the non-
    native side via MagicMock for the cases where it can faithfully model the API.
    """

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only path")
    def test_windows_msvcrt(self, monkeypatch):
        """On Windows, _getch delegates to msvcrt.getwch."""
        import msvcrt

        monkeypatch.setattr(msvcrt, "getwch", lambda: "k")
        monkeypatch.setattr(msvcrt, "kbhit", lambda: False)
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
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == "k"


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

    def test_prompt_colors_are_all_valid(self, monkeypatch):
        """Every colorize() call in prompt_user must use a known color name."""
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        monkeypatch.setattr(mod, "_getch", lambda: "a")
        captured = []
        original_colorize = colorize

        def spy(text, this_color):
            captured.append(this_color)
            return original_colorize(text, this_color)

        monkeypatch.setattr(mod, "colorize", spy)
        prompt_user()

        colors = {"red", "green", "yellow", "blue", "cyan", "magenta", "bold", "reset"}
        for color in captured:
            assert color in colors, f"prompt_user uses unknown color {color!r}"

    def test_undo_accepted_when_can_undo(self, monkeypatch):
        """Pressing 'u' returns 'u' when can_undo=True."""
        monkeypatch.setattr(mod, "_getch", lambda: "u")
        assert prompt_user(can_undo=True) == "u"

    def test_undo_rejected_when_cannot_undo(self, monkeypatch):
        """Pressing 'u' when can_undo=False is silently ignored — the prompt loops."""
        responses = iter(["u", "u", "a"])
        monkeypatch.setattr(mod, "_getch", lambda: next(responses))
        assert prompt_user(can_undo=False) == "a"

    def test_undo_label_shown_when_can_undo(self, monkeypatch, capsys):
        """The [u]ndo label appears in the rendered prompt only when can_undo=True."""
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        monkeypatch.setattr(mod, "_getch", lambda: "a")
        prompt_user(can_undo=True)
        out = capsys.readouterr().out
        assert "[u]ndo" in out

    def test_undo_label_hidden_when_cannot_undo(self, monkeypatch, capsys):
        """The [u]ndo label is omitted when can_undo=False."""
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        monkeypatch.setattr(mod, "_getch", lambda: "a")
        prompt_user(can_undo=False)
        out = capsys.readouterr().out
        assert "[u]ndo" not in out


class TestGetchEscapeSequences:
    """_getch() must consume escape sequences and other multi-byte input as a single
    logical event, so the trailing bytes never reach the action dispatcher.

    These tests exercise _getch's byte-level handling rather than monkeypatching _getch
    itself.
    """

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_escape_sequence_returns_empty(self, monkeypatch):
        """\\x1b[A (up arrow) is consumed in full and reported as ''."""
        import select
        import termios
        import tty

        reads = iter(["\x1b", "[", "A"])
        ready = iter([([0], [], []), ([0], [], []), ([], [], [])])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", lambda n: next(reads))
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(select, "select", lambda *a, **k: next(ready))

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_bare_escape_returns_empty(self, monkeypatch):
        """A lone ESC press with no tail bytes returns '' rather than \\x1b."""
        import select
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", lambda n: "\x1b")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(select, "select", lambda *a, **k: ([], [], []))

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_escape_drain_uses_nonzero_timeout(self, monkeypatch):
        """The select() that drains the ESC tail must use a nonzero timeout so a slow
        remote terminal where the tail bytes arrive a few milliseconds late still has
        its sequence drained instead of leaking into the next read."""
        import select
        import termios
        import tty

        timeouts = []

        def fake_select(rlist, wlist, xlist, timeout):
            timeouts.append(timeout)
            return ([], [], [])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", lambda n: "\x1b")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(select, "select", fake_select)

        _getch()

        assert any(t and t > 0 for t in timeouts), (
            "select() must be called with a nonzero timeout for ESC drain; "
            f"got {timeouts!r}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_normal_char_drains_input_buffer(self, monkeypatch):
        """After a single-byte read, _getch flushes any further buffered input so that a
        paste's trailing bytes don't bleed into the next prompt."""
        import termios
        import tty

        flush_calls = []

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", lambda n: "a")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(
            termios, "tcflush", lambda fd, when: flush_calls.append((fd, when))
        )
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 99)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == "a"
        assert flush_calls, "tcflush was not called to drain pending input"
        assert any(when == 99 for _, when in flush_calls), (
            f"tcflush should be called with TCIFLUSH; got {flush_calls!r}"
        )

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_unicode_decode_error_returns_empty(self, monkeypatch):
        """A UnicodeDecodeError on read is treated as a non-action key rather than
        crashing the interactive loop."""
        import termios
        import tty

        def fake_read(n):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", fake_read)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == ""

    def test_windows_special_key_xe0_prefix(self, monkeypatch):
        """Windows reports special keys (arrows, F-keys) as a \\xe0 prefix followed by a
        scancode.

        _getch consumes both and returns ''.
        """
        if sys.platform == "win32":
            import msvcrt

            calls = iter(["\xe0", "H"])
            monkeypatch.setattr(msvcrt, "getwch", lambda: next(calls))
            monkeypatch.setattr(msvcrt, "kbhit", lambda: False)
            assert _getch() == ""
        else:
            monkeypatch.setattr(sys, "platform", "win32")
            fake_msvcrt = MagicMock()
            calls = iter(["\xe0", "H"])
            fake_msvcrt.getwch.side_effect = lambda: next(calls)
            fake_msvcrt.kbhit.return_value = False
            monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
            assert _getch() == ""

    def test_windows_special_key_x00_prefix(self, monkeypatch):
        """Some Windows keys use \\x00 instead of \\xe0 as the prefix."""
        if sys.platform == "win32":
            import msvcrt

            calls = iter(["\x00", ";"])
            monkeypatch.setattr(msvcrt, "getwch", lambda: next(calls))
            monkeypatch.setattr(msvcrt, "kbhit", lambda: False)
            assert _getch() == ""
        else:
            monkeypatch.setattr(sys, "platform", "win32")
            fake_msvcrt = MagicMock()
            calls = iter(["\x00", ";"])
            fake_msvcrt.getwch.side_effect = lambda: next(calls)
            fake_msvcrt.kbhit.return_value = False
            monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
            assert _getch() == ""

    def test_windows_drains_queued_keys_including_special_prefix(self, monkeypatch):
        """The post-read drain on Windows must consume queued keys (a paste tail) and
        correctly handle a special-key prefix encountered mid-drain by also discarding
        its scancode."""
        # Initial getwch returns a normal "k". kbhit then signals one queued group: an
        # \xe0 prefix followed by its scancode "H". After that group, kbhit returns
        # False.
        getwch_calls = iter(["k", "\xe0", "H"])
        kbhit_calls = iter([True, False])

        if sys.platform == "win32":
            import msvcrt

            monkeypatch.setattr(msvcrt, "getwch", lambda: next(getwch_calls))
            monkeypatch.setattr(msvcrt, "kbhit", lambda: next(kbhit_calls))
            assert _getch() == "k"
        else:
            monkeypatch.setattr(sys, "platform", "win32")
            fake_msvcrt = MagicMock()
            fake_msvcrt.getwch.side_effect = lambda: next(getwch_calls)
            fake_msvcrt.kbhit.side_effect = lambda: next(kbhit_calls)
            monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
            assert _getch() == "k"

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_unicode_decode_error_during_escape_drain_tolerated(self, monkeypatch):
        """A UnicodeDecodeError raised while draining the tail of an escape sequence is
        swallowed; the drain loop continues until select reports nothing pending and
        _getch still returns ''."""
        import select
        import termios
        import tty

        reads = iter(
            [
                "\x1b",
                UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
            ]
        )

        def fake_read(n):
            value = next(reads)
            if isinstance(value, UnicodeDecodeError):
                raise value
            return value

        ready = iter([([0], [], []), ([], [], [])])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr("sys.stdin.read", fake_read)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(select, "select", lambda *a, **k: next(ready))

        assert _getch() == ""


class TestPromptUserNoRawByteEcho:
    """prompt_user must validate before echoing, so control bytes returned by _getch
    never reach the terminal."""

    def test_invalid_control_byte_not_echoed(self, monkeypatch):
        """When _getch returns an unrecognized byte (e.g. \\x1b), it must NOT be written
        to stdout.

        Color is disabled so the prompt itself is plain ASCII; any \\x1b in the captured
        output therefore came from echoing the raw input.
        """
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        responses = iter(["\x1b", "a"])
        monkeypatch.setattr(mod, "_getch", lambda: next(responses))
        printed = []
        monkeypatch.setattr("sys.stdout.write", lambda s: printed.append(s) or len(s))
        monkeypatch.setattr("sys.stdout.flush", lambda: None)

        assert prompt_user() == "a"
        joined = "".join(printed)
        assert "\x1b" not in joined, (
            f"prompt_user must not echo raw control bytes to stdout; got {joined!r}"
        )

    def test_unrecognized_letter_not_echoed(self, monkeypatch):
        """A non-action letter like 'z' triggers a re-prompt; the 'z' must not appear
        anywhere in stdout."""
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        responses = iter(["z", "a"])
        monkeypatch.setattr(mod, "_getch", lambda: next(responses))
        printed = []
        monkeypatch.setattr("sys.stdout.write", lambda s: printed.append(s) or len(s))
        monkeypatch.setattr("sys.stdout.flush", lambda: None)

        assert prompt_user() == "a"
        joined = "".join(printed)
        assert "z" not in joined, (
            f"rejected input 'z' should not be echoed; got {joined!r}"
        )


class TestInteractiveRequiresTTY:
    """--interactive should refuse cleanly when stdin is not a TTY, instead
    of crashing inside _getch on the first prompt."""

    @pytest.mark.skipif(sys.platform == "win32", reason="termios is Unix-only")
    def test_main_rejects_interactive_without_tty(self, monkeypatch, tmp_path, capsys):
        from octowrap import rewrap as rw

        f = tmp_path / "x.py"
        f.write_text(
            "# this is a very long comment that absolutely needs to be rewrapped"
            " because it is way over the line length limit and would normally"
            " trigger a prompt in interactive mode\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sys, "argv", ["octowrap", "--interactive", str(f)])

        with pytest.raises(SystemExit) as exc_info:
            rw.main()

        captured = capsys.readouterr()
        assert exc_info.value.code != 0
        combined = (captured.err + captured.out).lower()
        assert "interactive" in combined and "tty" in combined, (
            "expected an --interactive/TTY error message; got "
            f"stderr={captured.err!r} stdout={captured.out!r}"
        )
