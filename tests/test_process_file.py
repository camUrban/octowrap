import os
from pathlib import Path

import pytest

# noinspection PyProtectedMember
from octowrap.rewrap import (
    Decision,
    _block_prompt_units,
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "wrapped at a short width previously." in content

    def test_skip_keeps_original(self, tmp_path, monkeypatch):
        """When the user skips, the original block is preserved."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "s")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "A")
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

        def counting_prompt():
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

        def should_not_be_called():
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "e")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# octowrap: off" in content
        assert "# octowrap: on" in content

    def test_exclude_adds_exactly_two_lines(self, tmp_path, monkeypatch):
        """Excluding a block adds exactly two lines (the off/on pragmas)."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        original_line_count = WRAPPABLE_CONTENT.count(b"\n")
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "e")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "e")
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "    # octowrap: off" in content
        assert "    # octowrap: on" in content

    def test_excluded_block_ignored_on_rerun(self, tmp_path, monkeypatch):
        """Re-running on an excluded file produces no changes (idempotent)."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "e")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
        _, content = process_file(f, max_line_length=88, interactive=True)
        assert "    # FIXME: Manually fix the below comment" in content

    def test_flag_wraps_at_line_length(self, tmp_path, monkeypatch):
        """A short line length forces the FIXME comment to wrap."""
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
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

    def test_prose_and_todo_prompted_separately(self, tmp_path, monkeypatch):
        """A block with prose + TODO triggers exactly two prompts."""
        f = tmp_path / "t.py"
        f.write_bytes(self._mixed_block_content())
        call_count = 0

        def counting_prompt() -> str:
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

        def counting_prompt() -> str:
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))
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

        def should_not_be_called():
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        actions = [d.action for d in state["decisions"]]
        assert actions == ["a", "s", "e"]

    def test_quit_is_not_recorded(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "A")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        # One keypress, one decision — accept-all is recorded once even though it
        # applies to all subsequent paragraphs.
        assert len(state["decisions"]) == 1
        assert state["decisions"][0].action == "A"

    def test_paragraph_cursor_has_two_elements(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
        state = {"decisions": []}
        process_file(f, max_line_length=88, interactive=True, _state=state)
        assert len(state["decisions"]) == 1
        cursor = state["decisions"][0].cursor
        assert len(cursor) == 3
        assert cursor[1] == "inline"

    def test_decision_filepath_matches_processed_file(self, tmp_path, monkeypatch):
        f = tmp_path / "t.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
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

        def should_not_be_called():
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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "s")

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
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: next(responses))

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
