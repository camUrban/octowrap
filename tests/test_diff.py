"""Tests for octowrap.diff — unified diff parsing."""

from octowrap.diff import parse_diff_line_numbers


class TestParseDiffLineNumbers:
    """Tests for parse_diff_line_numbers()."""

    def test_empty_input(self):
        """Empty string returns empty dict."""
        assert parse_diff_line_numbers("") == {}

    def test_single_file_single_hunk(self):
        """A diff with one file and one hunk maps the correct 0-based lines."""
        diff_text = (
            "diff --git a/foo.py b/foo.py\n"
            "index abc1234..def5678 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,2 +1,3 @@\n"
            "+added line\n"
            " unchanged\n"
            "-removed\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"foo.py": {0, 1, 2}}

    def test_single_line_no_comma(self):
        """A hunk header with no comma means a single changed line."""
        diff_text = (
            "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -5 +5 @@\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"foo.py": {4}}

    def test_deletion_only_hunk(self):
        """A hunk with 0 added lines results in the file key with an empty set."""
        diff_text = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -5,3 +7,0 @@\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"foo.py": set()}

    def test_multiple_hunks_same_file(self):
        """Two hunks in the same file produce a union of line numbers."""
        diff_text = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "@@ -10,2 +10,3 @@\n"
            " ctx\n"
            "-old\n"
            "+new1\n"
            "+new2\n"
        )
        result = parse_diff_line_numbers(diff_text)
        # First hunk: line 1 (0-based: 0). Second hunk: lines 10-12 (0-based: 9,10,11).
        assert result == {"foo.py": {0, 9, 10, 11}}

    def test_multiple_files(self):
        """Two different files each get their own key in the dict."""
        diff_text = (
            "diff --git a/alpha.py b/alpha.py\n"
            "--- a/alpha.py\n"
            "+++ b/alpha.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
            "diff --git a/beta.py b/beta.py\n"
            "--- a/beta.py\n"
            "+++ b/beta.py\n"
            "@@ -3,2 +3,2 @@\n"
            "-old1\n"
            "-old2\n"
            "+new1\n"
            "+new2\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"alpha.py": {0}, "beta.py": {2, 3}}

    def test_new_file(self):
        """A newly added file (--- /dev/null) maps to the new filename."""
        diff_text = (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+line1\n"
            "+line2\n"
            "+line3\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"new.py": {0, 1, 2}}

    def test_subdir_path(self):
        """Paths within subdirectories are preserved as-is."""
        diff_text = (
            "diff --git a/src/octowrap/rewrap.py b/src/octowrap/rewrap.py\n"
            "--- a/src/octowrap/rewrap.py\n"
            "+++ b/src/octowrap/rewrap.py\n"
            "@@ -42 +42 @@\n"
            "-old\n"
            "+new\n"
        )
        result = parse_diff_line_numbers(diff_text)
        assert result == {"src/octowrap/rewrap.py": {41}}
