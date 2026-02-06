from octowrap.rewrap import process_content, process_file

# fmt: off
WRAPPABLE_CONTENT = (
    b"# This is a comment that was wrapped\n"
    b"# at a short width previously.\n"
    b"x = 1\n"
)
# fmt: on


class TestProcessContent:
    """Tests for the process_content() pure-transformation function."""

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
        assert f.read_text(newline="") == content


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

    def test_accept_all_applies_remaining(self, tmp_path, monkeypatch):
        """Accept-all applies rewrapped content to all subsequent blocks."""
        f = tmp_path / "t.py"
        # fmt: on
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: off
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "A")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# First block that was wrapped at a short width." in content
        assert "# Second block that was also wrapped at a short width." in content

    def test_accept_all_skips_prompting(self, tmp_path, monkeypatch):
        """After accept-all, prompt_user is not called for subsequent blocks."""
        f = tmp_path / "t.py"
        # fmt: on
        f.write_bytes(
            b"# First block that was wrapped\n"
            b"# at a short width.\n"
            b"x = 1\n"
            b"# Second block that was also wrapped\n"
            b"# at a short width.\n"
        )
        # fmt: off
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
