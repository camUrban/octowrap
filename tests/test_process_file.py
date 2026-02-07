from octowrap.rewrap import process_content, process_file

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
        changed, result = process_content(content, max_line_length=88)
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in result
        )

    def test_unchanged(self):
        """Clean code returns changed=False with identical content."""
        content = "x = 1\ny = 2\n"
        changed, result = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_empty_string(self):
        """Empty string returns (False, '')."""
        changed, result = process_content("", max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
        assert changed
        # Protected block preserved
        assert "# This is a comment that was wrapped\n" in result
        assert "# at a short width previously.\n" in result
        # Re enabled block rewrapped
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
        assert changed
        # Protected block preserved
        assert "# This is a comment that was wrapped\n" in result
        # Re enabled block rewrapped
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
        changed, result = process_content(content, max_line_length=88)
        assert not changed

    def test_pragma_block_itself_preserved(self):
        content = "# octowrap: off\nx = 1\n"
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88)
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
        changed, result = process_content(content, max_line_length=88, interactive=True)
        assert not changed
        assert not called
