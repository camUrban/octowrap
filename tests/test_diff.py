"""Tests for octowrap.diff: unified diff parsing and git integration."""

import shutil
import subprocess
from pathlib import Path

import pytest

from octowrap.diff import (
    NotAGitRepoError,
    get_changed_lines,
    get_repo_root,
    parse_diff_line_numbers,
)


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


class TestGetRepoRoot:
    """Tests for get_repo_root()."""

    def test_returns_path_in_git_repo(self, monkeypatch):
        """Returns a Path when inside a git repository."""
        monkeypatch.setattr(
            "octowrap.diff.subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(
                a[0], 0, stdout="/repo/root\n"
            ),
        )
        assert get_repo_root() == Path("/repo/root")

    def test_returns_none_outside_git_repo(self, monkeypatch):
        """Returns None when not inside a git repository."""

        # noinspection PyUnusedLocal
        def _fail(*args, **kwargs):
            raise subprocess.CalledProcessError(128, "git")

        monkeypatch.setattr("octowrap.diff.subprocess.run", _fail)
        assert get_repo_root() is None

    def test_returns_none_when_git_not_installed(self, monkeypatch):
        """Returns None when git is not installed."""

        # noinspection PyUnusedLocal
        def _fail(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("octowrap.diff.subprocess.run", _fail)
        assert get_repo_root() is None


class TestGetChangedLines:
    """Tests for get_changed_lines()."""

    @staticmethod
    def _mock_subprocess(monkeypatch, repo_root, diff_stdout):
        """Set up monkeypatches for both git rev-parse and git diff calls."""
        calls = []

        # noinspection PyUnusedLocal
        def _fake_run(cmd, **kwargs):
            calls.append(cmd)
            if "rev-parse" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=repo_root + "\n")
            if "diff" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=diff_stdout)
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr("octowrap.diff.subprocess.run", _fake_run)
        return calls

    def test_basic_diff(self, monkeypatch):
        """Returns correct changed line numbers from diff output."""
        diff_output = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        self._mock_subprocess(monkeypatch, "/repo", diff_output)
        result = get_changed_lines()
        assert result == {"foo.py": {0}}

    def test_custom_base(self, monkeypatch):
        """Passes the custom base ref to git diff."""
        calls = self._mock_subprocess(monkeypatch, "/repo", "")
        get_changed_lines(base="main")
        diff_cmd = [c for c in calls if "diff" in c][0]
        assert "main" in diff_cmd

    def test_default_base_is_head(self, monkeypatch):
        """Default base ref is HEAD."""
        calls = self._mock_subprocess(monkeypatch, "/repo", "")
        get_changed_lines()
        diff_cmd = [c for c in calls if "diff" in c][0]
        assert "HEAD" in diff_cmd

    def test_not_a_git_repo(self, monkeypatch):
        """Raises NotAGitRepoError when not in a git repository."""

        # noinspection PyUnusedLocal
        def _fail(*args, **kwargs):
            raise subprocess.CalledProcessError(128, "git")

        monkeypatch.setattr("octowrap.diff.subprocess.run", _fail)
        with pytest.raises(NotAGitRepoError):
            get_changed_lines()

    def test_git_not_installed(self, monkeypatch):
        """Raises NotAGitRepoError when git is not installed."""

        # noinspection PyUnusedLocal
        def _fail(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr("octowrap.diff.subprocess.run", _fail)
        with pytest.raises(NotAGitRepoError):
            get_changed_lines()


# noinspection PyDeprecation
@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
class TestGetChangedLinesIntegration:
    """Integration tests using real git repos in tmp_path."""

    @staticmethod
    def _git(repo_dir, *args):
        """Run a git command in the given directory."""
        return subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_modified_line(self, tmp_path, monkeypatch):
        """Modifying a single line reports that line as changed."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")
        self._git(tmp_path, "config", "user.email", "test@test.com")
        self._git(tmp_path, "config", "user.name", "Test")

        f = tmp_path / "example.py"
        f.write_text("line1\nline2\nline3\n")
        self._git(tmp_path, "add", "example.py")
        self._git(tmp_path, "commit", "-m", "initial")

        # Modify line 2 (0-based index 1)
        f.write_text("line1\nchanged\nline3\n")

        result = get_changed_lines(base="HEAD")
        assert "example.py" in result
        assert 1 in result["example.py"]  # 0-based: line 2
        assert 0 not in result["example.py"]
        assert 2 not in result["example.py"]

    def test_added_lines(self, tmp_path, monkeypatch):
        """Adding lines at the end reports only those new lines."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")
        self._git(tmp_path, "config", "user.email", "test@test.com")
        self._git(tmp_path, "config", "user.name", "Test")

        f = tmp_path / "example.py"
        f.write_text("line1\nline2\n")
        self._git(tmp_path, "add", "example.py")
        self._git(tmp_path, "commit", "-m", "initial")

        f.write_text("line1\nline2\nline3\nline4\n")

        result = get_changed_lines(base="HEAD")
        assert result["example.py"] == {2, 3}

    def test_new_untracked_file_not_in_diff(self, tmp_path, monkeypatch):
        """An untracked file does not appear in the diff against HEAD."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")
        self._git(tmp_path, "config", "user.email", "test@test.com")
        self._git(tmp_path, "config", "user.name", "Test")

        # Need at least one commit for HEAD to exist.
        (tmp_path / "existing.py").write_text("x = 1\n")
        self._git(tmp_path, "add", "existing.py")
        self._git(tmp_path, "commit", "-m", "initial")

        # Create a new file but don't stage it.
        (tmp_path / "new.py").write_text("# new file\n")

        result = get_changed_lines(base="HEAD")
        assert "new.py" not in result

    def test_unchanged_file_not_in_diff(self, tmp_path, monkeypatch):
        """A committed file with no modifications does not appear."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")
        self._git(tmp_path, "config", "user.email", "test@test.com")
        self._git(tmp_path, "config", "user.name", "Test")

        f = tmp_path / "example.py"
        f.write_text("line1\nline2\n")
        self._git(tmp_path, "add", "example.py")
        self._git(tmp_path, "commit", "-m", "initial")

        result = get_changed_lines(base="HEAD")
        assert result == {}

    def test_subdir_file(self, tmp_path, monkeypatch):
        """A modified file in a subdirectory has the correct relative path key."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")
        self._git(tmp_path, "config", "user.email", "test@test.com")
        self._git(tmp_path, "config", "user.name", "Test")

        sub = tmp_path / "src" / "pkg"
        sub.mkdir(parents=True)
        f = sub / "mod.py"
        f.write_text("original\n")
        self._git(tmp_path, "add", "src/pkg/mod.py")
        self._git(tmp_path, "commit", "-m", "initial")

        f.write_text("modified\n")

        result = get_changed_lines(base="HEAD")
        assert "src/pkg/mod.py" in result
        assert result["src/pkg/mod.py"] == {0}

    def test_get_repo_root_real(self, tmp_path, monkeypatch):
        """get_repo_root() returns the correct path for a real repo."""
        monkeypatch.chdir(tmp_path)
        self._git(tmp_path, "init")

        root = get_repo_root()
        assert root is not None
        assert root.resolve() == tmp_path.resolve()
