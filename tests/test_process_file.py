from octowrap.rewrap import process_file


class TestProcessFile:
    def test_basic_rewrap(self, tmp_path):
        """Comments in a file get rewrapped to the target width."""
        f = tmp_path / "example.py"
        f.write_bytes(
            b"# This is a comment that was wrapped\n"
            b"# at a short width previously.\n"
            b"x = 1\n"
        )
        changed, content = process_file(f, max_line_length=88, accept_all=True)
        assert changed
        assert (
            "# This is a comment that was wrapped at a short width previously."
            in content
        )

    def test_unchanged_file_returns_false(self, tmp_path):
        """A file with no rewrappable changes should return changed=False."""
        f = tmp_path / "clean.py"
        f.write_bytes(b"x = 1\ny = 2\n")
        changed, content = process_file(f, max_line_length=88, accept_all=True)
        assert not changed

    def test_dry_run_does_not_write(self, tmp_path):
        """dry_run=True should not modify the file on disk."""
        original = (
            b"# This is a comment that was wrapped\n# at a short width previously.\n"
        )
        f = tmp_path / "readonly.py"
        f.write_bytes(original)
        changed, _ = process_file(f, max_line_length=88, dry_run=True, accept_all=True)
        assert changed
        assert f.read_bytes() == original

    def test_preserves_lf_endings(self, tmp_path):
        """Unix style \\n line endings should be preserved."""
        f = tmp_path / "unix.py"
        f.write_bytes(b"# Short comment.\nx = 1\n")
        _, content = process_file(f, max_line_length=88, accept_all=True)
        assert "\r\n" not in content
        assert content.endswith("\n")

    def test_preserves_crlf_endings(self, tmp_path):
        """Windows style \\r\\n line endings should be preserved."""
        f = tmp_path / "win.py"
        f.write_bytes(b"# Short comment.\r\nx = 1\r\n")
        _, content = process_file(f, max_line_length=88, accept_all=True)
        assert "\r\n" in content

    def test_file_actually_written(self, tmp_path):
        """With accept_all and not dry_run, the file should be updated on disk."""
        f = tmp_path / "writable.py"
        f.write_bytes(b"# This was wrapped at a very\n# short width before.\n")
        changed, content = process_file(f, max_line_length=88, accept_all=True)
        assert changed
        assert f.read_text(newline="") == content
