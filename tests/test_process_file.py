import os
import re
from pathlib import Path

import pytest

# noinspection PyProtectedMember
from octowrap.rewrap import (
    Decision,
    _block_prompt_units,
    _init_session_state,
    _relative_path,
    count_changed_blocks,
    process_content,
    process_file,
)


def _raise_os_error(*_args, **_kwargs):
    raise OSError("fake replace failure")


# fmt: off
WRAPPABLE_CONTENT = (
    b"# This is a comment that was wrapped\n"
    b"# at a short width previously.\n"
    b"x = 1\n"
)
# fmt: on


class TestProcessContent:
    """Tests for the process_content() pure transformation function."""

    def test_basic_rewrap(self):
        """Wrappable content returns changed=True with joined comment."""
        content = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in result
        )

    def test_unchanged(self):
        """Clean code returns changed=False with identical content."""
        content = "x = 1\ny = 2\n"
        changed, result, _ = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_empty_string(self):
        """Empty string returns (False, '')."""
        changed, result, _ = process_content("", max_line_length=88)
        assert not changed
        assert result == ""


class TestProcessFile:
    def test_basic_rewrap(self, tmp_path):
        """Comments in a file get rewrapped to the target width."""
        f = tmp_path / "example.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        changed, content = process_file(f, max_line_length=88)
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in content
        )

    def test_unchanged_file_returns_false(self, tmp_path):
        """A file with no rewrappable changes should return changed=False."""
        f = tmp_path / "clean.py"
        f.write_bytes(b"x = 1\ny = 2\n")
        changed, content = process_file(f, max_line_length=88)
        assert not changed

    def test_dry_run_does_not_write(self, tmp_path):
        """dry_run=True should not modify the file on disk."""
        original = (
            b"# This is a comment that was wrapped\n# at a short width previously.\n"
        )
        f = tmp_path / "readonly.py"
        f.write_bytes(original)
        changed, _ = process_file(f, max_line_length=88, dry_run=True)
        assert changed
        assert f.read_bytes() == original

    def test_preserves_lf_endings(self, tmp_path):
        """Unix style \\n line endings should be preserved."""
        f = tmp_path / "unix.py"
        f.write_bytes(b"# Short comment.\nx = 1\n")
        _, content = process_file(f, max_line_length=88)
        assert "\r\n" not in content
        assert content.endswith("\n")

    def test_preserves_cr_endings(self, tmp_path):
        """Old Mac style \\r line endings should be preserved."""
        f = tmp_path / "mac.py"
        f.write_bytes(b"# Short comment.\rx = 1\r")
        _, content = process_file(f, max_line_length=88)
        assert "\r\n" not in content
        assert "\r" in content
        assert content.endswith("\r")

    def test_preserves_crlf_endings(self, tmp_path):
        """Windows style \\r\\n line endings should be preserved."""
        f = tmp_path / "win.py"
        f.write_bytes(b"# Short comment.\r\nx = 1\r\n")
        _, content = process_file(f, max_line_length=88)
        assert "\r\n" in content

    def test_file_actually_written(self, tmp_path):
        """Without dry_run, the file should be updated on disk."""
        f = tmp_path / "writable.py"
        f.write_bytes(b"# This was wrapped at a very\n# short width before.\n")
        changed, content = process_file(f, max_line_length=88)
        assert changed
        assert f.read_bytes().decode() == content

    def test_atomic_write_cleans_up_on_failure(self, tmp_path, monkeypatch):
        """If os.replace fails, the temp file is removed and the original is intact."""
        f = tmp_path / "t.py"
        original = b"# This was wrapped at a very\n# short width before.\n"
        f.write_bytes(original)

        monkeypatch.setattr("os.replace", _raise_os_error)
        with pytest.raises(OSError):
            process_file(f, max_line_length=88)

        # Original file should be untouched
        assert f.read_bytes() == original
        # No temp files left behind
        assert list(tmp_path.glob("*.tmp")) == []

    def test_atomic_write_cleanup_failure_does_not_mask_error(
        self, tmp_path, monkeypatch
    ):
        """If both os.replace and os.unlink fail, the original error propagates."""
        f = tmp_path / "t.py"
        f.write_bytes(b"# This was wrapped at a very\n# short width before.\n")

        monkeypatch.setattr("os.replace", _raise_os_error)
        monkeypatch.setattr("os.unlink", _raise_os_error)
        with pytest.raises(OSError, match="fake replace failure"):
            process_file(f, max_line_length=88)

        assert (
            f.read_bytes() == b"# This was wrapped at a very\n# short width before.\n"
        )

    def test_atomic_write_preserves_permissions(self, tmp_path):
        """Atomic write should preserve the original file's permission bits."""
        f = tmp_path / "perms.py"
        f.write_bytes(b"# This was wrapped at a very\n# short width before.\n")
        import stat

        original_mode = stat.S_IMODE(f.stat().st_mode)
        changed, _ = process_file(f, max_line_length=88)
        assert changed
        new_mode = stat.S_IMODE(f.stat().st_mode)
        assert new_mode == original_mode


class TestProcessFileInteractive:
    """Tests for the interactive path of process_file."""

    def test_accept_applies_changes(self, tmp_path, monkeypatch):
        """When the user accepts, the rewrapped content is used."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "wrapped at a short width previously." in content

    def test_skip_keeps_original(self, tmp_path, monkeypatch):
        """When the user skips, the original block is preserved."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "s")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert not changed

    def test_quit_keeps_remaining_blocks(self, tmp_path, monkeypatch):
        """After quit, all subsequent blocks keep their original form."""
        f = tmp_path / "t.py"
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "q")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        # Both blocks should be unchanged since user quit on the first
        assert not changed

    def test_quit_suppresses_diff_for_remaining_blocks(
        self, tmp_path, monkeypatch, capsys
    ):
        """After quit, no diffs are shown for subsequent blocks."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "q")
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        process_file(f, max_line_length=88, interactive=True)
        out = capsys.readouterr().out
        # Only the first block's diff should appear, not the second
        assert "First block" in out
        assert "Second block" not in out

    def test_accept_all_applies_remaining(self, tmp_path, monkeypatch):
        """Accept-all applies rewrapped content to all subsequent blocks."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "A")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped at a short width." in content

    def test_accept_all_skips_prompting(self, tmp_path, monkeypatch):
        """After accept-all, prompt_user is not called for subsequent blocks."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        call_count = 0

        def counting_prompt(*_, **__):
            nonlocal call_count
            call_count += 1
            return "A"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", counting_prompt)
        process_file(f, max_line_length=88, interactive=True)
        assert call_count == 1

    def test_no_diff_shown_when_block_unchanged(self, tmp_path, monkeypatch):
        """When a block has no changes, prompt_user should not be called."""
        f = tmp_path / "t.py"
        f.write_bytes(b"# Short.\nx = 1\n")
        called = False

        def should_not_be_called(*_, **__):
            nonlocal called
            called = True
            return "a"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", should_not_be_called)
        process_file(f, max_line_length=88, interactive=True)
        assert not called

    def test_exclude_wraps_block_with_pragmas(self, tmp_path, monkeypatch):
        """Excluding a block wraps it with octowrap: off/on pragmas."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "e")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# octowrap: off" in content
        assert "# octowrap: on" in content

    def test_exclude_adds_exactly_two_lines(self, tmp_path, monkeypatch):
        """Excluding a block adds exactly two lines (the off/on pragmas)."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        original_line_count = WRAPPABLE_CONTENT.count(b"\n")
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "e")
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert content.count("\n") == original_line_count + 2

    def test_exclude_preserves_indent(self, tmp_path, monkeypatch):
        """Pragmas match the indentation of the excluded block."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"def foo():\n"
            b"    # This is a comment that was wrapped\n"
            b"    # at a short width previously.\n"
        )
        # fmt: on
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "e")
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "    # octowrap: off" in content
        assert "    # octowrap: on" in content

    def test_excluded_block_ignored_on_rerun(self, tmp_path, monkeypatch):
        """Re-running on an excluded file produces no changes (idempotent)."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "e")
        process_file(f, max_line_length=88, interactive=True)
        # Second run: no interactive prompt needed, nothing should change
        changed, _ = process_file(f, max_line_length=88)
        assert not changed

    def test_exclude_then_accept(self, tmp_path, monkeypatch):
        """Exclude on first block and accept on second works correctly."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        responses = iter(["e", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        # First block should be wrapped with pragmas, original text preserved
        assert "# octowrap: off" in content
        assert "# First block that was wrapped\n" in content
        assert "# octowrap: on" in content
        # Second block should be rewrapped
        assert "# Second block that was also wrapped at a short width." in content

    def test_flag_adds_fixme_above_block(self, tmp_path, monkeypatch):
        """Flagging a block inserts a FIXME comment and preserves original text."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# FIXME: Manually fix the below comment" in content
        # Original block text preserved below the flag
        assert "# This is a comment that was wrapped\n" in content
        assert "# at a short width previously.\n" in content

    def test_flag_preserves_indent(self, tmp_path, monkeypatch):
        """The FIXME line matches the indentation of the flagged block."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"def foo():\n"
            b"    # This is a comment that was wrapped\n"
            b"    # at a short width previously.\n"
        )
        # fmt: on
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "    # FIXME: Manually fix the below comment" in content

    def test_flag_wraps_at_line_length(self, tmp_path, monkeypatch):
        """A short line length forces the FIXME comment to wrap."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        _, content = process_file(f, max_line_length=40, interactive=True)
        fixme_lines = [
            ln for ln in content.splitlines() if "FIXME" in ln or ln.startswith("#  ")
        ]
        assert len(fixme_lines) > 1
        # Continuation lines use one-space indent
        for line in fixme_lines[1:]:
            if line.startswith("#  "):
                assert line.startswith("#  ")

    @pytest.mark.parametrize("width", [22, 25, 30, 40, 60, 88])
    def test_flag_text_never_overflows(self, tmp_path, monkeypatch, width):
        """The FIXME marker octowrap inserts must itself respect max_line_length.

        Sampled across the range where the flag action can actually fire (widths below
        the rewrap text_width floor of 20 do not trigger a prompt at all).
        """
        f = tmp_path / "t.py"
        # A block long enough to guarantee a prompt at every sampled width.
        f.write_bytes(
            b"# This is a comment that was wrapped at a short width previously "
            b"and keeps going on well past any sane line length limit.\n"
            b"# Second line of the same paragraph to force a wrap operation.\n"
        )
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        _, content = process_file(f, max_line_length=width, interactive=True)
        flag_lines = [
            ln
            for ln in content.splitlines()
            if ln.startswith("# FIXME: ") or ln.startswith("#  ")
        ]
        assert flag_lines, f"expected a FIXME block at width={width}"
        for line in flag_lines:
            assert len(line) <= width, (
                f"flag line overflows width={width}: {len(line)} chars: {line!r}"
            )

    def test_flag_then_accept(self, tmp_path, monkeypatch):
        """Flag on first block and accept on second works correctly."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        responses = iter(["f", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        # First block should have FIXME above it, original text preserved
        assert "# FIXME: Manually fix the below comment" in content
        assert "# First block that was wrapped\n" in content
        # Second block should be rewrapped
        assert "# Second block that was also wrapped at a short width." in content

    def test_flag_wraps_block_with_pragmas(self, tmp_path, monkeypatch):
        """Flagging wraps the FIXME marker + original block in octowrap off/on
        pragmas."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        _, content = process_file(f, max_line_length=88, interactive=True)
        lines = content.splitlines()
        off_idx = lines.index("# octowrap: off")
        on_idx = lines.index("# octowrap: on")
        between = lines[off_idx + 1 : on_idx]
        # The pragma region contains the FIXME marker AND the unchanged original.
        assert between[0].startswith("# FIXME: Manually fix the below comment")
        assert "# This is a comment that was wrapped" in between
        assert "# at a short width previously." in between

    def test_flagged_block_not_rewrapped_on_rerun(self, tmp_path, monkeypatch):
        """Re-running on a flagged file leaves the pragma-protected region untouched."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "f")
        process_file(f, max_line_length=88, interactive=True)
        first_pass = f.read_bytes()
        # Second run in batch mode — nothing should change because the pragmas disable
        # rewrapping inside the flagged region.
        changed, content = process_file(f, max_line_length=88)
        assert not changed
        assert f.read_bytes() == first_pass
        # Original wrapped form is preserved; no joined rewrap line appeared.
        assert (
            "# This is a comment that was wrapped at a short width previously."
            not in content
        )


class TestBlockPromptUnits:
    """Tests for _block_prompt_units() paragraph-level splitting."""

    @staticmethod
    def _block(lines: list[str], indent: str = "") -> dict:
        return {
            "type": "comment_block",
            "lines": lines,
            "indent": indent,
            "start_idx": 0,
        }

    def test_single_prose_block_is_one_unit(self):
        """A plain prose block returns exactly one prompt unit."""
        block = self._block(
            [
                "# This is a comment that was wrapped",
                "# at a short width previously.",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert len(units) == 1

    def test_prose_plus_todo_split_into_two_units(self):
        """A block containing prose followed by a TODO yields two prompt units."""
        block = self._block(
            [
                "# Initialize variables that hold data which characterizes this panel.",
                "# These values will be overwritten during the collapse geometry step.",
                "# TODO: Compact the vortex arrays to only contain trailing edge panels.",
                "#  The current arrays waste ~93% of the expanded kernel computation.",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert len(units) == 2
        # First unit is the prose paragraph.
        assert all("TODO:" not in ln for ln in units[0]["rewrapped"])
        # Second unit carries the TODO marker.
        assert any("TODO:" in ln for ln in units[1]["rewrapped"])

    def test_tool_directive_is_its_own_no_op_unit(self):
        """A tool directive sits in its own unit where original == rewrapped."""
        block = self._block(
            [
                "# This module is inherently coupled to class internals, so accessing a",
                "# private attribute directly is acceptable here.",
                "# noinspection PyProtectedMember",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        # Prose unit + directive unit.
        assert len(units) == 2
        directive_unit = units[-1]
        assert directive_unit["original"] == directive_unit["rewrapped"]
        assert directive_unit["original"] == ["# noinspection PyProtectedMember"]

    def test_consecutive_list_items_grouped(self):
        """Adjacent list items merge into a single prompt unit."""
        block = self._block(
            [
                "# - alpha item one that keeps going a while to force rewrapping",
                "# - beta item two also long enough to need the wrap treatment",
                "# - gamma item three here is the last one in the group",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert len(units) == 1
        assert units[0]["raw_start"] == 0
        assert len(units[0]["original"]) == 3

    def test_list_split_by_blank_line(self):
        """A blank line between list items splits them into separate units."""
        block = self._block(
            [
                "# - alpha",
                "# - beta",
                "#",
                "# - gamma",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        # Two list groups plus the blank line in between.
        assert len(units) == 3
        assert [u["raw_start"] for u in units] == [0, 2, 3]

    def test_raw_start_is_block_relative(self):
        """``raw_start`` is an offset into ``block['lines']``, not an absolute line."""
        block = self._block(
            [
                "# First paragraph of prose that is long enough to wrap in a block.",
                "#",
                "# TODO: Second paragraph is a todo marker.",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert [u["raw_start"] for u in units] == [0, 1, 2]

    def test_adjacent_todo_markers_are_separate_units(self):
        """Adjacent TODO-style markers (no blank line) each get their own unit.

        Unlike list items, todo-type paragraphs are NOT grouped — each marker is a
        distinct task and users may want to accept/skip them independently.
        """
        block = self._block(
            [
                "# TODO: first task that is long enough to trigger a rewrap at 88 chars.",
                "# FIXME: second task that also exceeds the line length limit.",
                "# TODO: third task rounding out the adjacent todo cluster.",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert len(units) == 3
        assert [u["raw_start"] for u in units] == [0, 1, 2]
        assert all(len(u["original"]) == 1 for u in units)

    def test_adjacent_todo_with_continuations_stay_separate(self):
        """TODO continuation lines fold into their own todo, but adjacent TODOs stay in
        distinct units."""
        block = self._block(
            [
                "# TODO: first task with a long description needing more room",
                "#  that spans onto a continuation line beneath it.",
                "# TODO: second task that also needs its own prompt unit.",
            ]
        )
        units = _block_prompt_units(block, max_line_length=88)
        assert len(units) == 2
        # First unit absorbs its continuation line.
        assert len(units[0]["original"]) == 2
        assert len(units[1]["original"]) == 1


class TestInteractivePerParagraph:
    """Tests for per-paragraph interactive prompting."""

    @staticmethod
    def _mixed_block_content() -> bytes:
        # fmt: off
        return (
            b"# Initialize variables that hold data which characterizes this panel.\n"
            b"# These values will be overwritten during the collapse geometry step.\n"
            b"# TODO: Compact the vortex arrays to only contain trailing edge panels.\n"
            b"#  The current arrays waste ~93% of the expanded kernel computation.\n"
        )
        # fmt: on

    def test_diff_divider_width_matches_wrap_target_plus_prefix(
        self, tmp_path, monkeypatch, capsys
    ):
        """The diff dividers in interactive mode are *max_line_length + 2* wide so they
        extend past the two-character ``- `` / ``+ `` prefix and visually frame the wrap
        target."""
        f = tmp_path / "t.py"
        f.write_bytes(self._mixed_block_content())
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")

        process_file(f, max_line_length=120, interactive=True)

        out = capsys.readouterr().out
        divider_lines = [ln for ln in out.splitlines() if ln and ln[0] == "─"]
        assert divider_lines, "expected at least one divider in interactive output"
        # 120 (wrap target) + 2 ("- "/"+ " prefix) = 122.
        assert all(len(ln) == 122 for ln in divider_lines), (
            f"divider widths should be 122; got "
            f"{sorted({len(ln) for ln in divider_lines})}"
        )

    def test_prose_and_todo_prompted_separately(self, tmp_path, monkeypatch):
        """A block with prose + TODO triggers exactly two prompts."""
        f = tmp_path / "t.py"
        f.write_bytes(self._mixed_block_content())
        call_count = 0

        def counting_prompt(*_, **__) -> str:
            nonlocal call_count
            call_count += 1
            return "a"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", counting_prompt)
        changed, _ = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert call_count == 2

    def test_tool_directive_does_not_prompt(self, tmp_path, monkeypatch):
        """A no-op tool directive alongside wrappable prose does not add a prompt."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# This module is inherently coupled to class internals, so accessing a\n"
            b"# private attribute directly is acceptable here.\n"
            b"# noinspection PyProtectedMember\n"
        )
        # fmt: on
        call_count = 0

        def counting_prompt(*_, **__) -> str:
            nonlocal call_count
            call_count += 1
            return "a"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", counting_prompt)
        process_file(f, max_line_length=88, interactive=True)
        assert call_count == 1

    def test_skip_one_paragraph_accept_next(self, tmp_path, monkeypatch):
        """Skipping the prose paragraph keeps it while the TODO still rewraps."""
        f = tmp_path / "t.py"
        f.write_bytes(self._mixed_block_content())
        responses = iter(["s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        _, content = process_file(f, max_line_length=88, interactive=True)
        # The prose paragraph stays split across two lines (skipped).
        assert (
            "# Initialize variables that hold data which characterizes this panel.\n"
            in content
        )
        # The TODO paragraph is now rewrapped onto one content line plus a continuation
        # prefix.
        assert (
            "# TODO: Compact the vortex arrays to only contain trailing edge panels"
            in content
        )

    def test_exclude_wraps_only_the_paragraph(self, tmp_path, monkeypatch):
        """Excluding the TODO wraps only that paragraph in octowrap off/on pragmas."""
        f = tmp_path / "t.py"
        f.write_bytes(self._mixed_block_content())
        responses = iter(["a", "e"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        _, content = process_file(f, max_line_length=88, interactive=True)
        lines = content.splitlines()
        off_idx = lines.index("# octowrap: off")
        on_idx = lines.index("# octowrap: on")
        # The pragmas bracket just the TODO paragraph (2 original lines).
        between = lines[off_idx + 1 : on_idx]
        assert between == [
            "# TODO: Compact the vortex arrays to only contain trailing edge panels.",
            "#  The current arrays waste ~93% of the expanded kernel computation.",
        ]

    def test_count_changed_blocks_counts_paragraphs(self):
        """count_changed_blocks reports paragraph-level prompt counts."""
        content = (
            "# Initialize variables that hold data which characterizes this panel.\n"
            "# These values will be overwritten during the collapse geometry step.\n"
            "# TODO: Compact the vortex arrays to only contain trailing edge panels.\n"
            "#  The current arrays waste ~93% of the expanded kernel computation.\n"
        )
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 2


class TestToolDirectivePreservation:
    """Integration tests for tool directive preservation during rewrapping."""

    def test_directive_preserved_in_block(self):
        """A tool directive embedded in a comment block is preserved on its own line."""
        # fmt: off
        content = (
            "# This is a long comment that should be rewrapped because it exceeds the line length limit set for this file.\n"
            "# fmt: off\n"
            "# This is another long comment that should also be rewrapped to the correct line length for the file.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        # The directive must appear on its own line
        result_lines = result.splitlines()
        assert "# fmt: off" in result_lines
        # Surrounding prose should be rewrapped (not preserved verbatim)
        assert any("exceeds the line length" in line for line in result_lines)

    def test_noqa_directive_preserved(self):
        """A noqa directive stays on its own line."""
        # fmt: off
        content = (
            "# This is a long comment that should be rewrapped because it exceeds the configured maximum line length.\n"
            "# noqa: E501\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        result_lines = result.splitlines()
        assert "# noqa: E501" in result_lines

    def test_type_ignore_directive_preserved(self):
        """A type: ignore directive stays on its own line."""
        # fmt: off
        content = (
            "# This is a long comment that should be rewrapped because it exceeds the configured maximum line length.\n"
            "# type: ignore[assignment]\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        result_lines = result.splitlines()
        assert "# type: ignore[assignment]" in result_lines


class TestPragma:
    """Tests for # octowrap: off/on pragma directives."""

    def test_pragma_off_preserves_block(self):
        content = (
            "# octowrap: off\n"
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
            "x = 1\n"
        )
        changed, result, _ = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_pragma_on_resumes_wrapping(self):
        # fmt: off
        content = (
            "# octowrap: off\n"
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
            "# octowrap: on\n"
            "# This is another comment that was wrapped\n"
            "# at a short width previously.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        # Protected block preserved
        assert "# This is a comment that was wrapped\n" in result
        assert "# at a short width previously.\n" in result
        # Re-enabled block rewrapped
        assert (
            "# This is another comment that was wrapped at a short width previously."
            in result
        )

    def test_pragma_off_on_sandwich(self):
        # fmt: off
        content = (
            "# This top comment was wrapped\n"
            "# at a short width previously.\n"
            "# octowrap: off\n"
            "# This middle comment was wrapped\n"
            "# at a short width previously.\n"
            "# octowrap: on\n"
            "# This bottom comment was wrapped\n"
            "# at a short width previously.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        # Top block rewrapped
        assert "# This top comment was wrapped at a short width previously." in result
        # Middle block preserved
        assert "# This middle comment was wrapped\n" in result
        # Bottom block rewrapped
        assert (
            "# This bottom comment was wrapped at a short width previously." in result
        )

    def test_pragma_case_insensitive(self):
        # fmt: off
        content = (
            "# OCTOWRAP: OFF\n"
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
            "# Octowrap: On\n"
            "# Another comment that was wrapped\n"
            "# at a short width previously.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        # Protected block preserved
        assert "# This is a comment that was wrapped\n" in result
        # Re-enabled block rewrapped
        assert (
            "# Another comment that was wrapped at a short width previously." in result
        )

    def test_pragma_with_extra_whitespace(self):
        # fmt: off
        content = (
            "#  octowrap:  off\n"
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert not changed

    def test_pragma_block_itself_preserved(self):
        content = "# octowrap: off\nx = 1\n"
        changed, result, _ = process_content(content, max_line_length=88)
        assert "# octowrap: off" in result

    def test_pragma_off_without_on(self):
        # fmt: off
        content = (
            "# octowrap: off\n"
            "# First block that was wrapped\n"
            "# at a short width previously.\n"
            "x = 1\n"
            "# Second block that was wrapped\n"
            "# at a short width previously.\n"
        )
        # fmt: on
        changed, result, _ = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_pragma_interactive_mode(self, monkeypatch):
        """Pragmas are respected even in interactive mode, so there's no prompt for
        disabled blocks."""
        content = (
            "# octowrap: off\n"
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
        )
        called = False

        def should_not_be_called(*_, **__):
            nonlocal called
            called = True
            return "a"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", should_not_be_called)
        changed, result, _ = process_content(
            content, max_line_length=88, interactive=True
        )
        assert not changed
        assert not called


class TestChangedLinesFiltering:
    """Tests for the changed_lines parameter on process_content/process_file."""

    # fmt: off
    TWO_BLOCK_CONTENT = (
        "# First block that was wrapped\n"   # line 0
        "# at a short width.\n"              # line 1
        "x = 1\n"                            # line 2
        "# Second block that was wrapped\n"  # line 3
        "# at a short width.\n"              # line 4
    )
    # fmt: on

    def test_none_processes_all(self):
        """changed_lines=None processes everything (default behavior)."""
        content = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines=None
        )
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in result
        )

    def test_overlapping_block_processed(self):
        """A comment block at lines 0-1 is rewrapped when line 0 is changed."""
        content = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={0}
        )
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in result
        )

    def test_non_overlapping_skipped(self):
        """A comment block at lines 0-1 is skipped when only line 2 is changed."""
        content = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={2}
        )
        assert not changed
        assert result == content

    def test_empty_set_skips_all(self):
        """An empty changed_lines set skips all blocks."""
        content = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines=set()
        )
        assert not changed
        assert result == content

    def test_partial_overlap(self):
        """A 3-line block is processed if only the middle line is in changed_lines."""
        # fmt: off
        content = (
            "# This is a long comment that was wrapped at a very short width and\n"
            "# needs to be rewrapped to the correct\n"
            "# line length.\n"
            "x = 1\n"
        )
        # fmt: on
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={1}
        )
        assert changed

    def test_selective_blocks(self):
        """Two blocks: only the second overlaps changed_lines, only it is rewrapped."""
        changed, result, _ = process_content(
            self.TWO_BLOCK_CONTENT, max_line_length=88, changed_lines={3}
        )
        assert changed
        # First block unchanged
        assert "# First block that was wrapped\n" in result
        assert "# at a short width.\n" in result
        # Second block rewrapped
        assert "# Second block that was wrapped at a short width." in result

    def test_inline_extraction_filtered(self):
        """An overflowing inline on an unchanged line is not extracted."""
        content = (
            "x = 1\n"
            "foo = bar()  # This inline comment is way too long and definitely"
            " exceeds the eighty-eight character line length limit set\n"
        )
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={0}
        )
        assert not changed
        assert result == content

    def test_inline_extraction_on_changed_line(self):
        """An overflowing inline on a changed line is extracted."""
        content = (
            "x = 1\n"
            "foo = bar()  # This inline comment is way too long and definitely"
            " exceeds the eighty-eight character line length limit set\n"
        )
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={1}
        )
        assert changed
        assert "foo = bar()" in result

    def test_pragma_state_tracked_regardless(self):
        """Pragma off outside changed_lines still disables subsequent blocks."""
        # fmt: off
        content = (
            "# octowrap: off\n"                                # line 0 (pragma)
            "# This block is disabled.\n"                      # line 1
            "x = 1\n"                                          # line 2
            "# This block is also disabled because\n"          # line 3
            "# no octowrap: on was ever issued.\n"             # line 4
        )
        # fmt: on
        changed, result, _ = process_content(
            content, max_line_length=88, changed_lines={3, 4}
        )
        assert not changed
        assert result == content

    def test_process_file_passes_through(self, tmp_path):
        """process_file forwards changed_lines to process_content."""
        f = tmp_path / "t.py"
        f.write_bytes(self.TWO_BLOCK_CONTENT.encode())
        changed, content = process_file(f, max_line_length=88, changed_lines={3})
        assert changed
        # First block unchanged
        assert "# First block that was wrapped\n" in content
        # Second block rewrapped
        assert "# Second block that was wrapped at a short width." in content

    def test_count_changed_blocks_filtered(self):
        """count_changed_blocks only counts blocks overlapping changed_lines."""
        count = count_changed_blocks(
            self.TWO_BLOCK_CONTENT, max_line_length=88, changed_lines={3}
        )
        # Only the second block overlaps; the first does not.
        assert count == 1

    def test_count_changed_blocks_none_counts_all(self):
        """count_changed_blocks with changed_lines=None counts all changed blocks."""
        count = count_changed_blocks(
            self.TWO_BLOCK_CONTENT, max_line_length=88, changed_lines=None
        )
        assert count == 2


class TestRelativePath:
    def test_path_inside_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "sub" / "file.py"
        result = _relative_path(target)
        assert result == Path("sub") / "file.py"

    def test_path_outside_cwd(self, tmp_path, monkeypatch):
        # CWD is a subdirectory that doesn't contain the target
        cwd = tmp_path / "a"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        target = tmp_path / "b" / "file.py"
        result = _relative_path(target)
        # Should fall back to the original path unchanged
        assert result == target


class TestTodoIntegration:
    """Integration tests for TODO rewrap through process_content."""

    def test_todo_rewrapped_in_content(self):
        content = "# TODO: This is a very long todo item that definitely exceeds the eighty-eight character line length limit and should be rewrapped\nx = 1\n"
        changed, result, _ = process_content(content, max_line_length=88)
        assert changed
        lines = result.splitlines()
        assert lines[0].startswith("# TODO: ")
        assert all(len(line) <= 88 for line in lines)

    def test_todo_multiline_in_content(self):
        content = (
            "# TODO: First line of the todo\n#  continuation of the todo item\nx = 1\n"
        )
        changed, result, _ = process_content(content, max_line_length=88)
        lines = result.splitlines()
        assert lines[0].startswith("# TODO: ")
        full = " ".join(line.lstrip("# ") for line in lines if line.startswith("#"))
        assert "First line" in full
        assert "continuation" in full

    def test_todo_with_custom_patterns_via_kwarg(self):
        content = "# NOTE: This is a long note that exceeds the line length limit and should be rewrapped as a todo-style marker\nx = 1\n"
        changed, result, _ = process_content(
            content, max_line_length=88, todo_patterns=["note"]
        )
        assert changed
        lines = result.splitlines()
        assert lines[0].startswith("# NOTE: ")

    def test_empty_patterns_disables_todo(self):
        content = "# TODO: short\nx = 1\n"
        _, result, _ = process_content(content, max_line_length=88, todo_patterns=[])
        assert "# TODO: short" in result

    def test_todo_rewrap_through_process_file(self, tmp_path):
        f = tmp_path / "t.py"
        f.write_bytes(
            b"# TODO: This is a very long todo item that definitely exceeds the eighty-eight character line length limit and should be rewrapped\nx = 1\n"
        )
        changed, content = process_file(f, max_line_length=88)
        assert changed
        lines = content.splitlines()
        assert lines[0].startswith("# TODO: ")
        assert all(len(line) <= 88 for line in lines)

    def test_todo_case_sensitive_through_process_file(self, tmp_path):
        f = tmp_path / "t.py"
        f.write_bytes(
            b"# todo: this is a long comment that exceeds the line length and will be rewrapped as regular prose in sensitive mode\nx = 1\n"
        )
        changed, content = process_file(f, max_line_length=88, todo_case_sensitive=True)
        assert changed
        lines = content.splitlines()
        # In case-sensitive mode, lowercase 'todo' is regular prose, not a marker It
        # should still be rewrapped, just not with marker-style continuation
        assert lines[0].startswith("# todo: ")


class TestUtf8:
    def test_utf8_roundtrip(self, tmp_path):
        """Non-ASCII characters in comments survive a process_file round trip."""
        raw = "# Erd\u0151s\u2013Kac theorem: \u03c0(x) ~ x / ln(x)\nx = 1\n"
        f = tmp_path / "utf8.py"
        f.write_bytes(raw.encode("utf-8"))
        changed, content = process_file(f, max_line_length=88)
        assert not changed
        assert content == raw


class TestInteractiveFilepath:
    def test_diff_header_shows_relative_path(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        sub = tmp_path / "pkg"
        sub.mkdir()
        f = sub / "mod.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        process_file(f, max_line_length=88, interactive=True)
        out = capsys.readouterr().out
        expected = os.path.join("pkg", "mod.py")
        assert expected in out


class TestDecisionRecording:
    """Phase 2: every accepted prompt action is appended to _state['decisions']."""

    def test_single_accept_records_one_decision(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        assert len(state["decisions"]) == 1
        decision = state["decisions"][0]
        assert isinstance(decision, Decision)
        assert decision.action == "a"
        assert len(decision.cursor) == 2  # paragraph cursor

    def test_sequence_of_actions_recorded_in_order(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
            b"y = 2\n"
            b"# Third block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        responses = iter(["a", "s", "e"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "e"]

    def test_quit_is_not_recorded(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "q")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        assert state["decisions"] == []

    def test_accept_all_records_one_decision_with_capital_A(
        self, tmp_path, monkeypatch
    ):
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "A")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        # One keypress, one decision — accept-all is recorded once even though it
        # applies to all subsequent paragraphs.
        assert len(state["decisions"]) == 1
        assert state["decisions"][0].action == "A"

    def test_paragraph_cursor_has_two_elements(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        cursor = state["decisions"][0].cursor
        assert len(cursor) == 2
        assert all(isinstance(x, int) for x in cursor)

    def test_inline_cursor_is_tagged(self, tmp_path, monkeypatch):
        """Inline-extraction prompts produce a 3-tuple cursor with 'inline' tag."""
        f = tmp_path / "t.py"
        # An overflowing inline comment that triggers extraction.
        long_code = (
            "x = 1  # this is a very long inline comment that pushes the line "
            "well past the eighty-eight character limit\n"
        )
        f.write_bytes(long_code.encode())
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        assert len(state["decisions"]) == 1
        cursor = state["decisions"][0].cursor
        assert len(cursor) == 3
        assert cursor[1] == "inline"

    def test_decision_filepath_matches_processed_file(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        # filepath stored on the Decision is whatever process_file passes to
        # process_content (relative to CWD when possible).
        assert state["decisions"][0].filepath
        assert state["decisions"][0].filepath.endswith("t.py")

    def test_state_keys_auto_initialized_for_interactive_runs(
        self, tmp_path, monkeypatch
    ):
        """process_file(interactive=True) with an empty state populates every session-
        driver key so recording and replay both work."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "a")
        state = {}  # No keys — process_file must initialize them.
        process_file(f, max_line_length=88, interactive=True, _state=state)
        assert "decisions" in state
        assert len(state["decisions"]) == 1
        assert {"originals", "last_written", "dirty", "rewind_target"} <= state.keys()


class TestDecisionReplay:
    """Phase 3: pre-populated decisions are replayed without prompting."""

    def test_replayed_decision_skips_prompt(self, tmp_path, monkeypatch):
        """When _state['decisions'] already contains a Decision matching the cursor,
        prompt_user is never called and the recorded action is applied silently."""
        from octowrap.rewrap import _relative_path

        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)

        call_count = 0

        def should_not_be_called(*_, **__):
            nonlocal call_count
            call_count += 1
            return "s"  # would skip if it ever fired

        monkeypatch.setattr("octowrap.rewrap.prompt_user", should_not_be_called)

        # Pre-populate a decision matching the only paragraph in WRAPPABLE_CONTENT.
        # Cursor for a paragraph is (block_start_idx, unit_raw_start) — the comment
        # block in this fixture starts at line 0 with raw_start 0.
        key = str(_relative_path(f))
        state = {
            "decisions": [Decision(filepath=key, cursor=(0, 0), action="a")],
        }

        changed, content = process_file(
            f, max_line_length=88, interactive=True, _state=state
        )

        assert call_count == 0, "prompt_user should never fire during replay"
        assert changed
        # Action was 'a' (accept) — content should be the rewrapped version.
        assert "wrapped at a short width previously." in content

    def test_replay_preserves_decision_log(self, tmp_path, monkeypatch):
        """Replayed actions are not re-recorded — the decisions list stays the same
        length after replay."""
        from octowrap.rewrap import _relative_path

        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "s")

        key = str(_relative_path(f))
        state = {
            "decisions": [Decision(filepath=key, cursor=(0, 0), action="a")],
        }
        process_file(f, max_line_length=88, interactive=True, _state=state)
        # Still exactly the one pre-populated decision; no duplicates from replay.
        assert len(state["decisions"]) == 1
        assert state["decisions"][0].action == "a"

    def test_replayed_skip_keeps_original(self, tmp_path, monkeypatch):
        """A pre-populated 's' decision replays as a skip — file unchanged."""
        from octowrap.rewrap import _relative_path

        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user",
            lambda: pytest.fail("prompt_user should not be called"),
        )

        key = str(_relative_path(f))
        state = {
            "decisions": [Decision(filepath=key, cursor=(0, 0), action="s")],
        }
        changed, _ = process_file(f, max_line_length=88, interactive=True, _state=state)
        assert not changed
        assert f.read_bytes() == WRAPPABLE_CONTENT

    def test_decisions_for_other_files_are_ignored(self, tmp_path, monkeypatch):
        """Only decisions whose filepath matches the current file are replayed."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        responses = iter(["a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )

        # Decision for a different file — should not be replayed for f.
        state = {
            "decisions": [
                Decision(filepath="other_file.py", cursor=(0, 0), action="s"),
            ],
        }
        changed, content = process_file(
            f, max_line_length=88, interactive=True, _state=state
        )
        # The user's actual prompt response 'a' was used (not the irrelevant 's').
        assert changed
        assert "wrapped at a short width previously." in content


class TestUndoAction:
    """Phase 4: u (undo) action — pop, rewind, lazy re-write, q-flush."""

    def _make_three_paragraph_file(self, path):
        """Three rewrappable comment blocks separated by code lines."""
        path.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
            b"y = 2\n"
            b"# Third block that was also wrapped\n"
            b"# at a short width.\n"
            b"z = 3\n"
        )

    def test_in_file_undo_of_accept(self, tmp_path, monkeypatch):
        """Sequence a a u s s on three paragraphs: undo pops the second a;
        re-prompted at paragraph 2 the user picks s; paragraph 3 then s."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        responses = iter(["a", "a", "u", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped\n" in content
        assert "# Third block that was also wrapped\n" in content
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "s"]

    def test_in_file_undo_of_skip(self, tmp_path, monkeypatch):
        """Sequence s u a a on three paragraphs: undo pops the s at
        paragraph 1; re-prompted there the user picks a; finishes with a, a."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        responses = iter(["s", "u", "a", "a", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped at a short width." in content
        assert "# Third block that was also wrapped at a short width." in content
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "a", "a"]

    def test_undo_of_exclude_removes_pragmas(self, tmp_path, monkeypatch):
        """Excluding a paragraph wraps it in pragmas; undoing the exclude and accepting
        strips the pragmas."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        # e at paragraph 1 (records the exclude). u at paragraph 2 prompt (pops the
        # exclude). Re-prompted at paragraph 1: a a a.
        responses = iter(["e", "u", "a", "a", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "# octowrap: off" not in content
        assert "# octowrap: on" not in content
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped at a short width." in content

    def test_undo_of_flag_removes_fixme(self, tmp_path, monkeypatch):
        """Flagging inserts a FIXME marker; undoing the flag and accepting leaves no
        FIXME or pragmas in the final content."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        responses = iter(["f", "u", "a", "a", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "FIXME" not in content
        assert "# octowrap: off" not in content
        assert "# First block that was wrapped at a short width." in content

    def test_undo_of_accept_all_cross_file(self, tmp_path, monkeypatch):
        """A in file 1 propagates accept_all there; u at file 2 rewinds back into file
        1's first paragraph (where A was pressed)."""
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        self._make_three_paragraph_file(a)
        b.write_bytes(WRAPPABLE_CONTENT)
        # A applies to all 3 of A's paragraphs (silently). Then we hit B's first prompt:
        # u rewinds back into A's first paragraph (the paragraph where A was pressed).
        # Re-prompted there the user picks s, then s, s, s for the rest.
        responses = iter(["A", "u", "s", "s", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        from octowrap.rewrap import _run_session

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )
        # A is skipped (reverted via flush since previously written).
        assert a.read_bytes() == (
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
            b"y = 2\n"
            b"# Third block that was also wrapped\n"
            b"# at a short width.\n"
            b"z = 3\n"
        )
        actions = [d.action for d in state["decisions"]]
        assert actions == ["s", "s", "s", "s"]

    def test_replay_does_not_reprompt(self, tmp_path, monkeypatch):
        """Decisions made before an undo are silently replayed on re-entry — the user is
        only prompted at and beyond the rewind cursor."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)

        prompts: list = []
        responses = iter(["a", "a", "u", "s", "s"])

        def tracking_prompt(*_, **__):
            r = next(responses)
            prompts.append(r)
            return r

        monkeypatch.setattr("octowrap.rewrap.prompt_user", tracking_prompt)
        state = {}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        # 5 prompts fired: 3 on the first pass, then 2 more after replay of the
        # un-undone first decision. The first 'a' is replayed silently (not a 6th
        # prompt).
        assert prompts == ["a", "a", "u", "s", "s"]
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "s"]

    def test_undo_at_session_start_is_a_no_op(self, tmp_path, monkeypatch):
        """When decisions is empty, the prompt loops past 'u' (can_undo=False rejects
        it) and accepts the next valid keypress."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        # Drive the real prompt_user via _getch mocking so the can_undo gating actually
        # fires. With decisions empty, can_undo=False, and the 'u' keypress should be
        # silently rejected; the prompt loops and the next keypress ('a') takes effect.
        gets = iter(["u", "a"])
        monkeypatch.setattr("octowrap.rewrap._getch", lambda: next(gets))
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        state = {}
        changed, content = process_file(
            f, max_line_length=88, interactive=True, _state=state
        )
        # 'u' was rejected (can_undo=False at session start), 'a' was used.
        assert changed
        assert "wrapped at a short width previously." in content
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a"]

    def test_q_flush_reverts_undone_writes_across_files(self, tmp_path, monkeypatch):
        """Cross-file undo + q: the undone file's on-disk content is reverted to match
        the (now shorter) decision log."""
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_bytes(WRAPPABLE_CONTENT)
        b.write_bytes(WRAPPABLE_CONTENT)
        # Sequence: in A press 'a' (A written, rewrapped), in B at first prompt press
        # 'u' (pops the A decision, rewinds to A), at A's re-prompt press 'q' (quit).
        responses = iter(["a", "u", "q"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        # Drive both files through the real session driver.
        from octowrap.rewrap import _run_session

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )
        # The flush ran in finally. A's on-disk should now match the empty decision log
        # → original content (because undo + skip-on-quit produces the original).
        assert a.read_bytes() == WRAPPABLE_CONTENT
        # B was never written.
        assert b.read_bytes() == WRAPPABLE_CONTENT

    def test_cross_file_undo_re_walks_to_finish(self, tmp_path, monkeypatch):
        """Cross-file undo where the user walks back to completion: A is re-written with
        the new decision; B is written exactly once at the end."""
        import octowrap.rewrap as mod
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_bytes(WRAPPABLE_CONTENT)
        b.write_bytes(WRAPPABLE_CONTENT)

        write_log: list[str] = []
        real_atomic = mod._atomic_write

        def tracking_write(filepath, new_content):
            write_log.append(filepath.name)
            real_atomic(filepath, new_content)

        monkeypatch.setattr("octowrap.rewrap._atomic_write", tracking_write)

        # A.p1: a (A written rewrapped). B.p1: u (pops A's a, rewinds to A). A
        # re-prompt: s (new decision, A re-written as original). B re-prompt: a (B
        # written once).
        responses = iter(["a", "u", "s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        # Final decision log: A=s, B=a (in order encountered post-rewind).
        actions = [d.action for d in state["decisions"]]
        assert actions == ["s", "a"]

        rewrapped = (
            b"# This is a comment that was wrapped at a short width previously.\n"
            b"x = 1\n"
        )
        # A finished as 'skip' → original on disk. B finished as 'accept' → rewrapped.
        assert a.read_bytes() == WRAPPABLE_CONTENT
        assert b.read_bytes() == rewrapped
        # A was atomic-written twice (once for the initial 'a', once to revert via 's');
        # B was atomic-written exactly once.
        assert write_log == [a.name, a.name, b.name]

    def test_lazy_rewrite_on_cross_file_undo(self, tmp_path, monkeypatch):
        """After a cross-file undo, the previously-written file's on-disk content keeps
        its first decision until the user walks back through it.

        The re-write only happens once that file's loop completes a second time.
        """
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_bytes(WRAPPABLE_CONTENT)
        b.write_bytes(WRAPPABLE_CONTENT)

        a_disk_at_each_prompt: list[bytes] = []
        responses = iter(["a", "u", "s", "a"])

        def tracking_prompt(*_, **__):
            a_disk_at_each_prompt.append(a.read_bytes())
            return next(responses)

        monkeypatch.setattr("octowrap.rewrap.prompt_user", tracking_prompt)
        state = _init_session_state(None)
        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        rewrapped = (
            b"# This is a comment that was wrapped at a short width previously.\n"
            b"x = 1\n"
        )
        # A not yet written before its first prompt.
        assert a_disk_at_each_prompt[0] == WRAPPABLE_CONTENT
        # By B's first prompt, A's loop has completed → atomic-write happened.
        assert a_disk_at_each_prompt[1] == rewrapped
        # Lazy: undo is in-memory only; A on disk is unchanged at the rewind step.
        assert a_disk_at_each_prompt[2] == rewrapped
        # By B's re-prompt, A's loop has since re-completed with 's' → reverted.
        assert a_disk_at_each_prompt[3] == WRAPPABLE_CONTENT

    def test_q_flush_full_revert_of_two_written_files(self, tmp_path, monkeypatch):
        """Two files atomic-written, then both reverted via undo + undo + quit.

        The third file in the list provides the prompt position for the first undo.
        """
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        c = tmp_path / "c.py"
        a.write_bytes(WRAPPABLE_CONTENT)
        b.write_bytes(WRAPPABLE_CONTENT)
        c.write_bytes(WRAPPABLE_CONTENT)
        # A.p1: a (A written). B.p1: a (B written). C.p1: u (pops B → B dirty). B
        # re-prompt: u (pops A → A dirty). A re-prompt: q.
        responses = iter(["a", "a", "u", "u", "q"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        list(
            _run_session(
                [a, b, c],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )
        # Decision log empty: every action was undone or was the quit itself.
        assert state["decisions"] == []
        # Both written files reverted to their originals; the third file untouched.
        assert a.read_bytes() == WRAPPABLE_CONTENT
        assert b.read_bytes() == WRAPPABLE_CONTENT
        assert c.read_bytes() == WRAPPABLE_CONTENT

    def test_q_flush_partial_state_after_undo(self, tmp_path, monkeypatch):
        """Single file with four paragraphs, sequence ``a a a u q``.

        The first two paragraphs end up rewrapped on disk; paragraphs three and four
        stay original.
        """
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
            b"y = 2\n"
            b"# Third block that was also wrapped\n"
            b"# at a short width.\n"
            b"z = 3\n"
            b"# Fourth block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        responses = iter(["a", "a", "a", "u", "q"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state: dict = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)
        # u popped the third 'a'; q was not recorded.
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "a"]
        # Paragraphs 1 and 2 rewrapped.
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped at a short width." in content
        # Paragraphs 3 and 4 untouched (stay in their original two-line form).
        assert "# Third block that was also wrapped\n# at a short width.\n" in content
        assert "# Fourth block that was also wrapped\n# at a short width.\n" in content

    def test_undo_with_diff_only_filtering(self, tmp_path, monkeypatch):
        """When ``changed_lines`` filters out a paragraph, undo cursors for the
        unfiltered paragraphs still match correctly on replay."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"# First block that was wrapped\n"           # 0
            b"# at a short width.\n"                      # 1
            b"x = 1\n"                                    # 2
            b"# Second block that was also wrapped\n"     # 3
            b"# at a short width.\n"                      # 4
            b"y = 2\n"                                    # 5
            b"# Third block that was also wrapped\n"      # 6
            b"# at a short width.\n"                      # 7
        )
        # fmt: on
        # Only blocks 1 and 3 overlap the changed-line set; block 2 is filtered out.
        changed_lines = {0, 1, 6, 7}
        # Block 1: a. Block 3: u (pops block 1's a, rewinds to block 1). Block 1
        # re-prompt: s. Block 3 re-prompt: a.
        responses = iter(["a", "u", "s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state: dict = {}
        _, content = process_file(
            f,
            max_line_length=88,
            interactive=True,
            _state=state,
            changed_lines=changed_lines,
        )
        actions = [d.action for d in state["decisions"]]
        assert actions == ["s", "a"]
        # Block 1 skipped → original preserved.
        assert "# First block that was wrapped\n# at a short width.\n" in content
        # Block 2 filtered out → untouched.
        assert "# Second block that was also wrapped\n# at a short width.\n" in content
        # Block 3 accepted → rewrapped to a single line.
        assert "# Third block that was also wrapped at a short width." in content

    def test_undo_of_inline_extraction(self, tmp_path, monkeypatch):
        """An overflowing inline-comment prompt is undoable like a paragraph prompt; the
        recorded cursor is the inline 3-tuple (block_start_idx, "inline", line_idx)."""
        f = tmp_path / "t.py"
        # Two inline overflows give us the second prompt position needed to fire 'u'.
        f.write_bytes(
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
            b"y = 2  # another long inline comment that also pushes its line well past"
            b" the eighty-eight character limit easily\n"
        )
        # Inline 1: a. Inline 2: u (pops inline 1=a, rewinds). Inline 1 re-prompt: s.
        # Inline 2 re-prompt: a.
        responses = iter(["a", "u", "s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state: dict = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)
        actions = [d.action for d in state["decisions"]]
        assert actions == ["s", "a"]
        # Both decisions carry inline cursors.
        assert all(
            len(d.cursor) == 3 and d.cursor[1] == "inline" for d in state["decisions"]
        )
        lines = content.splitlines()
        # Line 1 was skipped — its inline overflow stays in place on the same line.
        x_line = next(ln for ln in lines if ln.startswith("x = 1"))
        assert "this inline comment" in x_line
        # Line 2 was accepted — the inline was extracted to a comment block above and
        # the code line itself no longer carries the trailing comment.
        y_line = next(ln for ln in lines if ln.startswith("y = 2"))
        assert "#" not in y_line
        assert "# another long inline comment" in content

    def test_progress_counter_rolls_back_after_undo(
        self, tmp_path, monkeypatch, capsys
    ):
        """Undo decrements the [X/Y] progress indicator: ``block_total`` is unchanged;
        ``block_current`` is recomputed from ``len(decisions)`` on each re-entry."""
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        responses = iter(["a", "a", "u", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        state["block_total"] = 3
        state["block_current"] = 0
        process_file(f, max_line_length=88, interactive=True, _state=state)

        # block_total is never decremented by undo.
        assert state["block_total"] == 3
        # Final decisions [a, s, s] → block_current ended at 3 (last prompt's
        # increment).
        assert state["block_current"] == 3

        out = capsys.readouterr().out
        # First pass shows [1/3], [2/3], [3/3]. After undo, p1 replays silently (no
        # progress increment), so the second pass shows [2/3] and [3/3] only.
        assert out.count("[1/3]") == 1
        assert out.count("[2/3]") == 2
        assert out.count("[3/3]") == 2

    def test_undo_after_a_then_A_rewinds_to_A_position(
        self, tmp_path, monkeypatch, capsys
    ):
        """Sequence ``a, A, u`` across files: the first paragraph is plainly accepted,
        the second paragraph is the A-press (auto-accepting the third), and ``u`` at the
        next file's first prompt must pop the most recent decision — the A — rewinding
        to *that* paragraph (not back to paragraph 1).

        Pins down: ``u`` pops the latest decision regardless of position in the
        decision log, so the re-prompt lands on the A-position. Verified via the
        ``Lines X-Y`` markers and progress indicators in show_block_diff output.
        """
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        # File 1: 3 wrappable paragraphs (Lines 1-2, 4-5, 7-8).
        self._make_three_paragraph_file(a)
        # File 2: 2 wrappable paragraphs (Lines 1-2, 4-5).
        b.write_bytes(
            b"# First B-block that was wrapped\n"
            b"# at a short width.\n"
            b"p = 1\n"
            b"# Second B-block that was also wrapped\n"
            b"# at a short width.\n"
        )

        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        # a, A, u, then s for the four remaining prompts after rewind.
        responses = iter(["a", "A", "u", "s", "s", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )

        state = _init_session_state(None)
        state["block_total"] = 5
        state["block_current"] = 0

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        out = capsys.readouterr().out
        # Sequence of "Lines X-Y" markers in the captured diff output. We expect:
        #   1. file1 paragraph 1 (Lines 1-2) — `a`
        #   2. file1 paragraph 2 (Lines 4-5) — `A` (paragraph 3 auto-accepts silently)
        #   3. file2 paragraph 1 (Lines 1-2) — `u` rewinds back into file 1
        #   4. file1 paragraph 2 (Lines 4-5) — re-prompt at the A position
        #   5. file1 paragraph 3 (Lines 7-8) — `s` (was auto-accepted; now re-prompts)
        #   6. file2 paragraph 1 (Lines 1-2) — `s`
        #   7. file2 paragraph 2 (Lines 4-5) — `s`
        line_markers = re.findall(r"Lines (\d+-\d+)", out)
        assert line_markers == [
            "1-2",
            "4-5",
            "1-2",
            "4-5",
            "7-8",
            "1-2",
            "4-5",
        ], f"unexpected prompt order: {line_markers}"

        # Progress indicators on the diff headers, in order. The third prompt (file 2
        # paragraph 1) shows [4/5] because file 1's auto-accept of paragraph 3 added 1
        # to block_current via a_extras at file 2 entry. After undo, recompute drops the
        # a_extras padding, so the re-prompt at paragraph 2 of file 1 shows [2/5].
        progress_markers = re.findall(r"\[(\d+/\d+)\]", out)
        assert progress_markers == [
            "1/5",
            "2/5",
            "4/5",
            "2/5",
            "3/5",
            "4/5",
            "5/5",
        ], f"unexpected progress sequence: {progress_markers}"

        # Final decision log: only the original a@paragraph1_file1 survived; A was
        # popped and everything from paragraph2_file1 onward was re-prompted as `s`.
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "s", "s", "s"]
        # a_extras emptied (the only A was popped).
        assert state["a_extras"] == {}

    def test_progress_counter_includes_auto_accepts_under_A(
        self, tmp_path, monkeypatch
    ):
        """Pressing A bumps [X/Y] for the prompt itself plus every silently auto-
        accepted paragraph that follows in the same file.

        Regression: previously block_current was incremented only at the A prompt, so
        a file with N changed paragraphs where the user pressed A on the first prompt
        finished with block_current=1 instead of N — and the indicator at the next
        file's first prompt under-reported total progress by N-1.
        """
        f = tmp_path / "t.py"
        self._make_three_paragraph_file(f)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "A")
        state = _init_session_state(None)
        state["block_total"] = 3
        state["block_current"] = 0
        process_file(f, max_line_length=88, interactive=True, _state=state)

        # 3 changed paragraphs, A on the first; the other 2 auto-accept.
        assert len(state["decisions"]) == 1
        assert state["decisions"][0].action == "A"
        # a_extras records the count of subsequent auto-accepted paragraphs (2).
        a_cursor = state["decisions"][0].cursor
        a_filepath = state["decisions"][0].filepath
        assert state["a_extras"][(a_filepath, a_cursor)] == 2

    def test_progress_counter_carries_auto_accepts_into_next_file(
        self, tmp_path, monkeypatch, capsys
    ):
        """[X/Y] at the next file's first prompt reflects the auto-accepts from the
        prior file's A press.

        Two files, 3 changed paragraphs each (block_total=6). Press A on file 1's
        first prompt: 3 paragraphs of file 1 are processed (1 prompt + 2 auto-
        accepts). The next prompt — file 2's first — should display [4/6], not
        [2/6].
        """
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        self._make_three_paragraph_file(a)
        self._make_three_paragraph_file(b)

        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        # A in a.py auto-accepts a.py's remaining 2 paragraphs; then we hit b.py's first
        # prompt. 's' there leaves the rest unchanged.
        responses = iter(["A", "s", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        state["block_total"] = 6
        state["block_current"] = 0

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        out = capsys.readouterr().out
        # File 1 prompt 1 (the A): [1/6]. File 2 prompt 1: [4/6] — *not* [2/6].
        assert "[1/6]" in out
        assert "[4/6]" in out
        assert "[2/6]" not in out, (
            f"the indicator under-reported auto-accepts under A; output:\n{out}"
        )

    def test_progress_counter_under_A_at_inline_prompt(self, tmp_path, monkeypatch):
        """A pressed at an inline-extraction prompt also records its auto-accept count,
        covering the inline branch of ``_record_a_extras``."""
        f = tmp_path / "t.py"
        inline_overflow = (
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
        )
        # Two overflowing inline comments + one wrappable comment block — three changed
        # paragraphs total. A on the first inline prompt auto-accepts the other two.
        f.write_bytes(
            inline_overflow
            + b"# First block that was wrapped\n"
            + b"# at a short width.\n"
            + b"y = 2  # another long inline comment that exceeds the eighty-eight"
            + b" character line length limit too\n"
        )
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda *_, **__: "A")
        state = _init_session_state(None)
        state["block_total"] = 3
        state["block_current"] = 0
        process_file(f, max_line_length=88, interactive=True, _state=state)

        assert len(state["decisions"]) == 1
        assert state["decisions"][0].action == "A"
        assert state["decisions"][0].cursor[1] == "inline"
        # 2 paragraphs auto-accepted after the A.
        a_cursor = state["decisions"][0].cursor
        a_filepath = state["decisions"][0].filepath
        assert state["a_extras"][(a_filepath, a_cursor)] == 2

    def test_a_extras_cleaned_up_on_undo_of_inline_A(self, tmp_path, monkeypatch):
        """Inline-extraction undo path also drops a_extras when the popped decision is
        an A pressed at an inline prompt."""
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        inline_overflow = (
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
            b"y = 2  # another long inline comment that exceeds the eighty-eight"
            b" character line length limit too\n"
        )
        a.write_bytes(inline_overflow)
        b.write_bytes(inline_overflow)

        # A at a.py's first inline prompt auto-accepts the second inline. At b.py's
        # first inline prompt, u rewinds back to a.py's first inline (popping the A and
        # clearing its a_extras entry).
        responses = iter(["A", "u", "s", "s", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        state["block_total"] = 4
        state["block_current"] = 0

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        assert state["a_extras"] == {}

    def test_a_extras_cleaned_up_on_undo_of_A(self, tmp_path, monkeypatch):
        """Undoing the A decision itself drops its a_extras entry so the recomputed
        block_current at re-entry no longer includes its (now-invalid) auto-accept
        padding."""
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        self._make_three_paragraph_file(a)
        self._make_three_paragraph_file(b)

        # A in a.py (auto-accepts the other 2). At b.py's first prompt: u rewinds back
        # to a.py's first paragraph (popping the A and clearing its a_extras). a.py's
        # three paragraphs are then re-prompted: s s s. b.py: s s s.
        responses = iter(["A", "u", "s", "s", "s", "s", "s", "s"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        state["block_total"] = 6
        state["block_current"] = 0

        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )

        # a_extras is empty after the A is popped.
        assert state["a_extras"] == {}
        # 6 prompts after the rewind (3 in a.py + 3 in b.py), all 's'.
        actions = [d.action for d in state["decisions"]]
        assert actions == ["s", "s", "s", "s", "s", "s"]
        # block_current ends at len(decisions) + 0 (no surviving A) = 6.
        assert state["block_current"] == 6

    def test_mixed_paragraph_and_inline_cursors(self, tmp_path, monkeypatch):
        """A file with both inline and paragraph prompts disambiguates cursors via the
        ``"inline"`` tag, so undoing a paragraph decision after an inline one pops the
        right entry from the log."""
        f = tmp_path / "t.py"
        # fmt: off
        f.write_bytes(
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
            b"# This first comment block was wrapped\n"
            b"# at a short width previously.\n"
            b"y = 2\n"
            b"# This second comment block was also wrapped\n"
            b"# at a short width previously.\n"
        )
        # fmt: on
        # Inline: a. Paragraph 1: a. Paragraph 2: u (pops p1=a, rewinds to p1).
        # Paragraph 1 re-prompt: s. Paragraph 2 re-prompt: a.
        responses = iter(["a", "a", "u", "s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state: dict = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "a"]
        # The inline decision (first) keeps its 3-tuple "inline" cursor; the two
        # paragraph decisions are 2-tuples without that tag.
        assert len(state["decisions"][0].cursor) == 3
        assert state["decisions"][0].cursor[1] == "inline"
        assert len(state["decisions"][1].cursor) == 2
        assert len(state["decisions"][2].cursor) == 2
        # Inline accepted → comment lifted above x = 1; paragraph 1 skipped → original
        # preserved; paragraph 2 accepted → rewrapped to a single line.
        assert (
            "# This first comment block was wrapped\n# at a short width previously.\n"
            in content
        )
        assert (
            "# This second comment block was also wrapped at a short width previously."
            in content
        )

    def test_cross_file_inline_undo_marks_prior_file_dirty(self, tmp_path, monkeypatch):
        """Undoing an inline-extraction decision after the prior file was atomic-written
        marks that file dirty so the q-flush reverts it to the original."""
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        inline_overflow = (
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
        )
        a.write_bytes(inline_overflow)
        b.write_bytes(inline_overflow)
        # A.inline: a (A written). B.inline: u (pops A's inline decision; A is in
        # last_written, so A is marked dirty). A re-prompt: q.
        responses = iter(["a", "u", "q"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        list(
            _run_session(
                [a, b],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )
        # A reverted to original via direct re-write on the post-rewind quit; B was
        # never written.
        assert a.read_bytes() == inline_overflow
        assert b.read_bytes() == inline_overflow
        assert state["decisions"] == []

    def test_flush_replays_inline_decision_in_replay_only_mode(
        self, tmp_path, monkeypatch
    ):
        """When a file with an inline-extraction decision is undone and never re-walked
        (the user quits in a different file), the q-flush replays its loop in
        ``replay_only`` mode — the un-decided inline cursor defaults to skip and the
        original line is preserved on disk."""
        from octowrap.rewrap import _run_session

        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        c = tmp_path / "c.py"
        inline_overflow = (
            b"x = 1  # this inline comment is way too long and definitely exceeds the"
            b" eighty-eight character line length limit set\n"
        )
        a.write_bytes(inline_overflow)
        b.write_bytes(inline_overflow)
        c.write_bytes(inline_overflow)
        # A: a (written). B: a (written). C: u (pops B → B dirty). B re-prompt: u (pops
        # A → A dirty). A re-prompt: q.
        responses = iter(["a", "a", "u", "u", "q"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state = _init_session_state(None)
        list(
            _run_session(
                [a, b, c],
                state,
                max_line_length=88,
                dry_run=False,
                interactive=True,
            )
        )
        # A reverted via direct re-write on quit; B reverted via the flush's replay-only
        # walk (which routes the un-decided inline cursor through the skip branch); C
        # never touched.
        assert a.read_bytes() == inline_overflow
        assert b.read_bytes() == inline_overflow
        assert c.read_bytes() == inline_overflow
        assert state["decisions"] == []

    def test_process_file_interactive_propagates_session_errors(self, tmp_path):
        """Errors yielded by ``_run_session`` (e.g. a missing file) propagate out of
        ``process_file`` when the interactive single-file path is in use."""
        missing = tmp_path / "does-not-exist.py"
        with pytest.raises(FileNotFoundError):
            process_file(missing, max_line_length=88, interactive=True)

    def test_within_block_undo_replays_exclude_correctly(self, tmp_path, monkeypatch):
        """When `e` and later decisions all live inside a single multi-paragraph block,
        an undo at a later paragraph must replay the earlier `e` (re-emitting its
        pragmas) and the intervening decisions while still matching the rewind cursor.

        This pins down the cursor-stability invariant: replay re-parses the original
        content, so the in-memory pragma lines added by `e` never shift later units'
        cursors. A future change that walked the mutated buffer instead would
        silently break this case.
        """
        f = tmp_path / "t.py"
        # Four wrappable prose paragraphs separated by blank `#` lines — all the same
        # indent, so parse_comment_blocks produces a single block with four wrap units
        # at raw_start 0, 3, 6, 9.
        # fmt: off
        f.write_bytes(
            b"# This is paragraph 1 that was wrapped\n"
            b"# at a short width.\n"
            b"#\n"
            b"# This is paragraph 2 that was wrapped\n"
            b"# at a short width.\n"
            b"#\n"
            b"# This is paragraph 3 that was wrapped\n"
            b"# at a short width.\n"
            b"#\n"
            b"# This is paragraph 4 that was wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: on
        # p1: e (pragmas wrap p1 in memory). p2: a. p3: a. p4: u (pops p3=a, rewinds to
        # p3). p3 re-prompt: s. p4 re-prompt: a.
        responses = iter(["e", "a", "a", "u", "s", "a"])
        monkeypatch.setattr(
            "octowrap.rewrap.prompt_user", lambda *_, **__: next(responses)
        )
        state: dict = {}
        _, content = process_file(f, max_line_length=88, interactive=True, _state=state)

        # Decision log reflects the replay: p1=e and p2=a survived the undo; p3=s is the
        # new decision; p4=a was made after the rewind.
        actions = [d.action for d in state["decisions"]]
        assert actions == ["e", "a", "s", "a"]
        # The decisions still carry the original cursors (raw_starts 0, 3, 6, 9).
        cursors = [d.cursor for d in state["decisions"]]
        assert cursors == [(0, 0), (0, 3), (0, 6), (0, 9)]

        # p1's pragmas were re-emitted on replay — the excluded paragraph is bracketed
        # by exactly one off/on pair and its original two lines are preserved verbatim
        # between them.
        lines = content.splitlines()
        off_idx = lines.index("# octowrap: off")
        on_idx = lines.index("# octowrap: on")
        assert lines[off_idx + 1 : on_idx] == [
            "# This is paragraph 1 that was wrapped",
            "# at a short width.",
        ]
        assert content.count("# octowrap: off") == 1
        assert content.count("# octowrap: on") == 1
        # p2's `a` was replayed → joined onto a single line.
        assert "# This is paragraph 2 that was wrapped at a short width." in content
        # p3 was re-decided as skip → still its original two-line form.
        assert "# This is paragraph 3 that was wrapped\n# at a short width." in content
        # p4's new `a` decision applied → single-line rewrap.
        assert "# This is paragraph 4 that was wrapped at a short width." in content
