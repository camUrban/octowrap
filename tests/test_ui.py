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

    def test_divider_width_defaults_to_88(self, capsys, monkeypatch):
        """With no explicit width, the dividers default to the standard wrap target of
        88 characters, matching the default --line-length."""
        monkeypatch.setattr(
            "octowrap.rewrap._USE_COLOR", False
        )  # plain '─', no color codes
        show_block_diff(["# a"], ["# b"], 0)
        out = capsys.readouterr().out
        divider_lines = [ln for ln in out.splitlines() if ln and ln[0] == "─"]
        assert len(divider_lines) == 2
        assert all(len(ln) == 88 for ln in divider_lines)

    def test_divider_width_tracks_explicit_width(self, capsys, monkeypatch):
        """*divider_width* sets the rule width so the visual frame matches the active
        ``max_line_length`` instead of a hard-coded 60."""
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        show_block_diff(["# a"], ["# b"], 0, divider_width=120)
        out = capsys.readouterr().out
        divider_lines = [ln for ln in out.splitlines() if ln and ln[0] == "─"]
        assert len(divider_lines) == 2
        assert all(len(ln) == 120 for ln in divider_lines)

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
        """On Unix, _getch uses termios/tty + os.read to read one character."""
        import os
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"k")
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
        import os
        import select
        import termios
        import tty

        reads = iter([b"\x1b", b"[A"])
        ready = iter([([0], [], []), ([], [], [])])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: next(reads))
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
        import os
        import select
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"\x1b")
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
        import os
        import select
        import termios
        import tty

        timeouts = []

        def fake_select(rlist, wlist, xlist, timeout):
            timeouts.append(timeout)
            return ([], [], [])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"\x1b")
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
        import os
        import termios
        import tty

        flush_calls = []

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"a")
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
    def test_unix_read_oserror_returns_empty(self, monkeypatch):
        """An OSError on read (e.g. interrupted syscall) is treated as a non-action key
        rather than crashing the interactive loop."""
        import os
        import termios
        import tty

        def fake_read(fd, n):
            raise OSError("interrupted")

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", fake_read)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_invalid_utf8_byte_does_not_crash(self, monkeypatch):
        """A non-UTF8 byte (e.g. 0xff) is decoded with errors='replace' rather than
        crashing the interactive loop.

        The resulting character is harmless: it never
        matches any action key, so prompt_user re-prompts.
        """
        import os
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"\xff")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        result = _getch()
        # The replacement character (or anything else) is fine as long as it's not a
        # recognized action key; assert it would not trigger any of {a,A,e,f,s,u,q}.
        assert result.lower() not in {"a", "e", "f", "s", "u", "q"}
        assert result != "A"

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
    def test_unix_oserror_during_escape_drain_tolerated(self, monkeypatch):
        """An OSError raised while draining the tail of an escape sequence breaks the
        drain loop cleanly rather than propagating, and _getch still returns ''."""
        import os
        import select
        import termios
        import tty

        reads = iter([b"\x1b", OSError("interrupted")])

        def fake_read(fd, n):
            value = next(reads)
            if isinstance(value, OSError):
                raise value
            return value

        ready = iter([([0], [], []), ([], [], [])])

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", fake_read)
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        monkeypatch.setattr(select, "select", lambda *a, **k: next(ready))

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_eof_on_first_read_returns_empty(self, monkeypatch):
        """``os.read`` returns ``b''`` at EOF (e.g. closed stdin); _getch reports '' so
        the prompt loop can re-prompt or exit gracefully rather than crashing."""
        import os
        import termios
        import tty

        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: b"")
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_eof_during_escape_drain_breaks_loop(self, monkeypatch):
        """If ``os.read`` returns ``b''`` while draining an escape tail, the drain loop
        must break instead of spinning forever on a closed pipe."""
        import os
        import select
        import termios
        import tty

        reads = iter([b"\x1b", b""])
        monkeypatch.setattr("sys.stdin.fileno", lambda: 0)
        monkeypatch.setattr(os, "read", lambda fd, n: next(reads))
        monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
        monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
        monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
        monkeypatch.setattr(termios, "TCSADRAIN", 1)
        monkeypatch.setattr(termios, "TCIFLUSH", 0)
        monkeypatch.setattr(tty, "setcbreak", lambda fd: None)
        # select reports ready forever; only the b"" return value can break the loop.
        monkeypatch.setattr(select, "select", lambda *a, **k: ([0], [], []))

        assert _getch() == ""

    @pytest.mark.skipif(sys.platform == "win32", reason="Unix only path")
    def test_unix_up_arrow_real_pipe_drains_tail(self, monkeypatch):
        """Regression for v0.6.0: pressing up arrow (\\x1b[A) leaked '[' and 'A' into
        subsequent reads because Python's TextIOWrapper pre-fetched all 3 bytes from the
        kernel pipe into its own buffer on the first ``sys.stdin.read(1)``, and the
        select-based drain (which only sees the OS fd) couldn't reach them.  Result: the
        next prompt would echo '[' (ignored) and then 'A' (misread as accept-all).

        This test wires _getch up to a real pipe pre-loaded with all 3 bytes — the exact
        condition that triggered the bug — and checks that _getch consumes the whole
        sequence and leaves the pipe empty.
        """
        import os
        import termios
        import tty

        r_fd, w_fd = os.pipe()
        try:
            os.write(w_fd, b"\x1b[A")

            monkeypatch.setattr("sys.stdin.fileno", lambda: r_fd)
            monkeypatch.setattr(termios, "tcgetattr", lambda fd: [])
            monkeypatch.setattr(termios, "tcsetattr", lambda fd, when, old: None)
            # tcflush only works on real terminals; stub it out.  os.read + select
            # already guarantee the kernel pipe is empty on success, so this stub isn't
            # masking the assertion below.
            monkeypatch.setattr(termios, "tcflush", lambda fd, when: None)
            monkeypatch.setattr(tty, "setcbreak", lambda fd: None)

            assert _getch() == "", "up arrow must collapse to '' (no leftover key)"

            # The pipe must be empty: any leftover byte would resurface as a bogus
            # keypress in the next prompt iteration — exactly the original bug.
            import select as _sel

            ready, _, _ = _sel.select([r_fd], [], [], 0)
            if ready:
                leftover = os.read(r_fd, 16)
                pytest.fail(
                    f"up arrow leaked tail bytes into the input stream: {leftover!r}"
                )
        finally:
            os.close(r_fd)
            os.close(w_fd)


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
