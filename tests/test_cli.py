import io
import runpy
import subprocess
from pathlib import Path

import pytest

import octowrap.rewrap as mod
from octowrap.cli import main

# fmt: off
WRAPPABLE_CONTENT = (
    b"# This is a comment that was wrapped\n"
    b"# at a short width previously.\n"
    b"x = 1\n"
)
# fmt: on


class TestMain:
    """Tests for the main() CLI orchestration function."""

    def test_default_non_interactive(self, tmp_path, monkeypatch, capsys):
        """By default, changes are applied without prompting."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        out = capsys.readouterr().out
        assert "Reformatted:" in out
        assert "1 file(s) reformatted." in out

    def test_interactive_flag(self, tmp_path, monkeypatch, capsys):
        """With -i, the user is prompted per block."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "-i", str(f)])
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_dry_run(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--dry-run", str(f)])
        main()
        out = capsys.readouterr().out
        assert "Would reformat:" in out
        assert "would be reformatted" in out
        # File should not have been modified
        assert f.read_bytes() == WRAPPABLE_CONTENT

    def test_diff_output(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--diff", str(f)])
        main()
        out = capsys.readouterr().out
        assert "---" in out
        assert "+++" in out
        # --diff implies --dry-run
        assert f.read_bytes() == WRAPPABLE_CONTENT

    def test_no_changes(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        out = capsys.readouterr().out
        assert "0 file(s) reformatted." in out

    def test_custom_line_length(self, tmp_path, monkeypatch, capsys):
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 120 but not at 40.\nx = 1\n"
        )
        monkeypatch.setattr("sys.argv", ["octowrap", "-l", "40", str(f)])
        main()
        content = f.read_text()
        assert all(len(line) <= 40 for line in content.splitlines())

    def test_missing_path_warns(self, tmp_path, monkeypatch, capsys):
        fake = tmp_path / "nonexistent.py"
        monkeypatch.setattr("sys.argv", ["octowrap", str(fake)])
        main()
        out = capsys.readouterr().out
        assert "not found, skipping" in out

    def test_directory_non_recursive(self, tmp_path, monkeypatch, capsys):
        """With --no-recursive, only top level .py files are processed."""
        (tmp_path / "top.py").write_bytes(WRAPPABLE_CONTENT)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--no-recursive", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_directory_recursive(self, tmp_path, monkeypatch, capsys):
        """Directories recurse by default (no flag needed)."""
        (tmp_path / "top.py").write_bytes(WRAPPABLE_CONTENT)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "2 file(s) reformatted." in out

    def test_quit_stops_remaining_files(self, tmp_path, monkeypatch, capsys):
        """Pressing quit during interactive mode skips all remaining files."""
        a = tmp_path / "a.py"
        a.write_bytes(WRAPPABLE_CONTENT)
        b = tmp_path / "b.py"
        b.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
        monkeypatch.setattr("sys.argv", ["octowrap", "-i", str(a), str(b)])
        main()
        out = capsys.readouterr().out
        # First file is processed (user quits within it), second is skipped entirely
        assert "0 file(s) reformatted." in out
        # b.py should be untouched on disk
        assert b.read_bytes() == WRAPPABLE_CONTENT

    def test_error_handling(self, tmp_path, monkeypatch, capsys):
        """A file that can't be processed should log an error and continue."""
        good = tmp_path / "good.py"
        good.write_bytes(WRAPPABLE_CONTENT)
        bad = tmp_path / "bad.py"
        bad.write_bytes(WRAPPABLE_CONTENT)

        real_process_file = mod.process_file

        def failing_process_file(filepath, *args, **kwargs):
            if filepath.name == "bad.py":
                raise RuntimeError("fake read error")
            return real_process_file(filepath, *args, **kwargs)

        monkeypatch.setattr(mod, "process_file", failing_process_file)
        monkeypatch.setattr("sys.argv", ["octowrap", str(good), str(bad)])
        main()
        out = capsys.readouterr().out
        assert "Error processing" in out
        assert "fake read error" in out


class TestEntryPoints:
    """Tests that exercise __main__.py and cli.py entry points."""

    def test_dunder_main(self, tmp_path, monkeypatch, capsys):
        """Running via python -m octowrap exercises __main__.py in process."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        runpy.run_module("octowrap", run_name="__main__")
        out = capsys.readouterr().out
        assert "0 file(s) reformatted." in out

    def test_console_script(self, tmp_path):
        """The installed 'octowrap' console script works end to end."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        result = subprocess.run(
            ["octowrap", str(f)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "1 file(s) reformatted." in result.stdout


class TestConfigIntegration:
    """End-to-end tests for pyproject.toml config support."""

    def test_config_sets_line_length(self, tmp_path, monkeypatch, capsys):
        """Config line-length is respected when CLI flag is absent."""
        (tmp_path / "pyproject.toml").write_text("[tool.octowrap]\nline-length = 40\n")
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        content = f.read_text()
        assert all(len(line) <= 40 for line in content.splitlines())

    def test_cli_overrides_config_line_length(self, tmp_path, monkeypatch, capsys):
        """CLI --line-length takes precedence over config."""
        (tmp_path / "pyproject.toml").write_text("[tool.octowrap]\nline-length = 40\n")
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", "-l", "88", str(f)])
        main()
        content = f.read_text()
        # At width 88 the comment fits on one line
        assert content.startswith(
            "# A moderately long comment that fits at 88 but not at 40.\n"
        )

    def test_config_sets_recursive_false(self, tmp_path, monkeypatch, capsys):
        """Config recursive = false disables the default recursion."""
        (tmp_path / "pyproject.toml").write_text("[tool.octowrap]\nrecursive = false\n")
        (tmp_path / "top.py").write_bytes(WRAPPABLE_CONTENT)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_invalid_config_exits(self, tmp_path, monkeypatch, capsys):
        """Unknown config keys cause a non-zero exit."""
        (tmp_path / "pyproject.toml").write_text("[tool.octowrap]\nbogus = 42\n")
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        with pytest.raises(SystemExit, match="1"):
            main()
        err = capsys.readouterr().err
        assert "config error" in err

    def test_no_config_uses_defaults(self, tmp_path, monkeypatch, capsys):
        """Without a pyproject.toml, default behavior is preserved."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_config_exclude_replaces_defaults(self, tmp_path, monkeypatch, capsys):
        """Config exclude replaces the default exclude list."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\nexclude = ["custom_dir"]\n'
        )
        # .venv should NOT be excluded since defaults are replaced
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "a.py").write_bytes(WRAPPABLE_CONTENT)
        # custom_dir SHOULD be excluded
        custom_dir = tmp_path / "custom_dir"
        custom_dir.mkdir()
        (custom_dir / "b.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        # Only .venv/a.py should be processed (custom_dir excluded)
        assert "1 file(s) reformatted." in out

    def test_config_extend_exclude(self, tmp_path, monkeypatch, capsys):
        """Config extend-exclude adds to the default exclude list."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\nextend-exclude = ["extra"]\n'
        )
        # .venv should still be excluded (defaults preserved)
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "a.py").write_bytes(WRAPPABLE_CONTENT)
        # extra should also be excluded
        extra_dir = tmp_path / "extra"
        extra_dir.mkdir()
        (extra_dir / "b.py").write_bytes(WRAPPABLE_CONTENT)
        # top level file should be processed
        (tmp_path / "c.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_config_todo_patterns_replaces_defaults(
        self, tmp_path, monkeypatch, capsys
    ):
        """Config todo-patterns replaces the default TODO/FIXME patterns."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\ntodo-patterns = ["note"]\n'
        )
        f = tmp_path / "a.py"
        # NOTE should now be treated as a TODO marker and rewrapped
        f.write_bytes(
            b"# NOTE: This is a long note that exceeds the line length and should be rewrapped as a todo-style marker item\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        content = f.read_text()
        lines = content.splitlines()
        assert lines[0].startswith("# NOTE: ")
        # TODO should NOT be treated as a marker since defaults are replaced
        f2 = tmp_path / "b.py"
        f2.write_bytes(b"# TODO: short\nx = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f2)])
        main()
        assert "# TODO: short" in f2.read_text()

    def test_config_empty_todo_patterns_ignores_extend(self, tmp_path, monkeypatch):
        """An explicit empty todo-patterns disables TODO detection entirely."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\ntodo-patterns = []\nextend-todo-patterns = ["note"]\n'
        )
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# TODO: This is a long todo that exceeds the line length and should be rewrapped as a normal prose comment now\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        content = f.read_text()
        lines = content.splitlines()
        # TODO should NOT be treated as a marker — continuation lines should use
        # prose style ("# ") not TODO continuation style ("#  ")
        assert len(lines) > 2  # Should be rewrapped across multiple lines
        assert lines[1].startswith("# ") and not lines[1].startswith("#  ")

    def test_config_todo_patterns_with_extend(self, tmp_path, monkeypatch):
        """Both todo-patterns and extend-todo-patterns combine when non-empty."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\ntodo-patterns = ["note"]\nextend-todo-patterns = ["hack"]\n'
        )
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# HACK: This is a long hack comment that exceeds the line length and should be rewrapped as a todo-style marker item\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        content = f.read_text()
        lines = content.splitlines()
        # HACK should be treated as a marker via extend-todo-patterns
        assert lines[0].startswith("# HACK: ")
        assert lines[1].startswith("#  ")

    def test_config_extend_todo_patterns(self, tmp_path, monkeypatch, capsys):
        """Config extend-todo-patterns adds to the default patterns."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.octowrap]\nextend-todo-patterns = ["note"]\n'
        )
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# NOTE: This is a long note that exceeds the line length and should be rewrapped as a todo-style marker item\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        content = f.read_text()
        lines = content.splitlines()
        assert lines[0].startswith("# NOTE: ")


class TestConfigFlag:
    """Tests for the --config flag."""

    def test_config_flag_reads_specified_file(self, tmp_path, monkeypatch, capsys):
        """--config points to a specific pyproject.toml."""
        cfg = tmp_path / "custom" / "pyproject.toml"
        cfg.parent.mkdir()
        cfg.write_text("[tool.octowrap]\nline-length = 40\n")
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        )
        monkeypatch.setattr("sys.argv", ["octowrap", "--config", str(cfg), str(f)])
        main()
        content = f.read_text()
        assert all(len(line) <= 40 for line in content.splitlines())

    def test_config_flag_overridden_by_cli(self, tmp_path, monkeypatch, capsys):
        """CLI --line-length takes precedence over --config values."""
        cfg = tmp_path / "pyproject.toml"
        cfg.write_text("[tool.octowrap]\nline-length = 40\n")
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        )
        monkeypatch.setattr(
            "sys.argv", ["octowrap", "--config", str(cfg), "-l", "88", str(f)]
        )
        main()
        content = f.read_text()
        assert content.startswith(
            "# A moderately long comment that fits at 88 but not at 40.\n"
        )

    def test_config_flag_ignores_auto_discovery(self, tmp_path, monkeypatch, capsys):
        """--config prevents auto-discovery of a nearer pyproject.toml."""
        # Place a config in CWD that sets line-length = 40
        (tmp_path / "pyproject.toml").write_text("[tool.octowrap]\nline-length = 40\n")
        # Point --config at an empty config (no octowrap section)
        alt = tmp_path / "other" / "pyproject.toml"
        alt.parent.mkdir()
        alt.write_text("[tool.other]\nfoo = 1\n")
        f = tmp_path / "a.py"
        f.write_bytes(
            b"# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr("sys.argv", ["octowrap", "--config", str(alt), str(f)])
        main()
        content = f.read_text()
        # Should use default 88, not the CWD config's 40
        assert content.startswith(
            "# A moderately long comment that fits at 88 but not at 40.\n"
        )

    def test_config_flag_invalid_file_exits(self, tmp_path, monkeypatch, capsys):
        """--config pointing to a file with bad config causes exit."""
        cfg = tmp_path / "pyproject.toml"
        cfg.write_text("[tool.octowrap]\nbogus = 42\n")
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", "--config", str(cfg), str(f)])
        with pytest.raises(SystemExit, match="1"):
            main()
        err = capsys.readouterr().err
        assert "config error" in err


class TestCheckMode:
    """Tests for the --check flag."""

    def test_check_exits_zero_when_clean(self, tmp_path, monkeypatch, capsys):
        """No changes needed -> exit 0."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", str(f)])
        main()  # should not raise
        out = capsys.readouterr().out
        assert "0 file(s) would be reformatted." in out

    def test_check_exits_one_when_dirty(self, tmp_path, monkeypatch, capsys):
        """Changes needed -> exit 1."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", str(f)])
        with pytest.raises(SystemExit, match="1"):
            main()

    def test_check_with_diff(self, tmp_path, monkeypatch, capsys):
        """--check --diff shows diff AND exits 1."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", "--diff", str(f)])
        with pytest.raises(SystemExit, match="1"):
            main()
        out = capsys.readouterr().out
        assert "---" in out
        assert "+++" in out

    def test_check_does_not_write(self, tmp_path, monkeypatch, capsys):
        """--check must not modify files on disk."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", str(f)])
        with pytest.raises(SystemExit):
            main()
        assert f.read_bytes() == WRAPPABLE_CONTENT


class TestDefaultExcludes:
    """Tests for default directory exclusion."""

    def test_default_excludes_skip_venv(self, tmp_path, monkeypatch, capsys):
        """.venv/ is auto skipped by default excludes."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        (venv_dir / "a.py").write_bytes(WRAPPABLE_CONTENT)
        (tmp_path / "b.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_default_excludes_skip_pycache(self, tmp_path, monkeypatch, capsys):
        """__pycache__/ is auto skipped by default excludes."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "a.py").write_bytes(WRAPPABLE_CONTENT)
        (tmp_path / "b.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_excludes_do_not_affect_explicit_files(self, tmp_path, monkeypatch, capsys):
        """Passing a file directly always processes it, even in excluded dir."""
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()
        f = venv_dir / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out


class TestColorFlags:
    """Tests for --color/--no-color/auto-detect."""

    def test_force_color_on(self, tmp_path, monkeypatch, capsys):
        """--color forces _USE_COLOR to True regardless of TTY."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--color", "-i", str(f)])
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "s")
        main()
        assert mod._USE_COLOR is True

    def test_force_color_off(self, tmp_path, monkeypatch, capsys):
        """--no-color forces _USE_COLOR to False regardless of TTY."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "--no-color", str(f)])
        main()
        assert mod._USE_COLOR is False

    def test_auto_detect_tty(self, tmp_path, monkeypatch, capsys):
        """Without flags, color is enabled when stdout is a TTY."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.delenv("NO_COLOR", raising=False)
        main()
        assert mod._USE_COLOR is True

    def test_auto_detect_non_tty(self, tmp_path, monkeypatch, capsys):
        """Without flags, color is disabled when stdout is not a TTY."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        main()
        assert mod._USE_COLOR is False

    def test_no_color_env_var(self, tmp_path, monkeypatch, capsys):
        """NO_COLOR env var disables color even on a TTY."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        monkeypatch.setenv("NO_COLOR", "1")
        main()
        assert mod._USE_COLOR is False

    def test_color_flag_overrides_no_color_env(self, tmp_path, monkeypatch, capsys):
        """Explicit --color wins over NO_COLOR env var."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", "--color", str(f)])
        monkeypatch.setenv("NO_COLOR", "1")
        main()
        assert mod._USE_COLOR is True

    def test_color_and_no_color_mutually_exclusive(self, tmp_path, monkeypatch):
        """--color and --no-color cannot be used together."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", "--color", "--no-color", str(f)])
        with pytest.raises(SystemExit, match="2"):
            main()


class TestStdinMode:
    """Tests for reading from stdin when '-' is passed."""

    def test_stdin_basic(self, monkeypatch, capsys):
        """Output contains rewrapped comment, no status messages."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert (
            "# This is a comment that was wrapped at a short width previously." in out
        )
        assert "Reformatted" not in out
        assert "file(s)" not in out

    def test_stdin_no_changes(self, monkeypatch, capsys):
        """When nothing changes, output equals input."""
        src = "x = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert out == src

    def test_stdin_check_clean(self, monkeypatch, capsys):
        """--check with clean input exits 0."""
        monkeypatch.setattr("sys.stdin", io.StringIO("x = 1\n"))
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()

    def test_stdin_check_dirty(self, monkeypatch, capsys):
        """--check with dirty input exits 1."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "--check", "-"])
        with pytest.raises(SystemExit, match="1"):
            main()

    def test_stdin_diff(self, monkeypatch, capsys):
        """--diff output contains unified diff with <stdin>."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "--diff", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert "--- <stdin>" in out
        assert "+++ <stdin>" in out

    def test_stdin_diff_check_dirty(self, monkeypatch, capsys):
        """--diff --check with dirty input shows diff and exits 1."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "--diff", "--check", "-"])
        with pytest.raises(SystemExit, match="1"):
            main()
        out = capsys.readouterr().out
        assert "--- <stdin>" in out
        assert "+++ <stdin>" in out

    def test_stdin_diff_check_clean(self, monkeypatch, capsys):
        """--diff --check with clean input exits 0 with no output."""
        monkeypatch.setattr("sys.stdin", io.StringIO("x = 1\n"))
        monkeypatch.setattr("sys.argv", ["octowrap", "--diff", "--check", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert out == ""

    def test_stdin_mixed_paths_error(self, monkeypatch, capsys):
        """Mixing '-' with other paths prints error and exits 1."""
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.argv", ["octowrap", "-", "foo.py"])
        with pytest.raises(SystemExit, match="1"):
            main()
        err = capsys.readouterr().err
        assert "cannot be mixed" in err

    def test_stdin_interactive_error(self, monkeypatch, capsys):
        """--interactive with stdin prints error and exits 1."""
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.argv", ["octowrap", "-i", "-"])
        with pytest.raises(SystemExit, match="1"):
            main()
        err = capsys.readouterr().err
        assert "cannot be used with stdin" in err

    def test_stdin_empty(self, monkeypatch, capsys):
        """Empty stdin produces empty output and exits 0."""
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        monkeypatch.setattr("sys.argv", ["octowrap", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert out == ""

    def test_stdin_line_length(self, monkeypatch, capsys):
        """Respects -l flag for stdin input."""
        src = "# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr("sys.argv", ["octowrap", "-l", "40", "-"])
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert all(len(line) <= 40 for line in out.splitlines())


class TestStdinFilename:
    """Tests for the --stdin-filename flag."""

    def test_stdin_filename_in_diff(self, monkeypatch, capsys):
        """--stdin-filename shows the given name in diff headers instead of <stdin>."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr(
            "sys.argv", ["octowrap", "--diff", "--stdin-filename", "src/app.py", "-"]
        )
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        expected = str(Path("src/app.py"))
        assert f"--- {expected}" in out
        assert f"+++ {expected}" in out

    def test_stdin_filename_without_stdin_errors(self, tmp_path, monkeypatch, capsys):
        """--stdin-filename without '-' prints an error and exits 1."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr(
            "sys.argv", ["octowrap", "--stdin-filename", "foo.py", str(f)]
        )
        with pytest.raises(SystemExit, match="1"):
            main()
        err = capsys.readouterr().err
        assert "--stdin-filename requires" in err

    def test_stdin_filename_config_discovery(self, tmp_path, monkeypatch, capsys):
        """Config is discovered from --stdin-filename's parent, not CWD."""
        # Create a pyproject.toml in a subdirectory with a short line-length
        sub = tmp_path / "project"
        sub.mkdir()
        (sub / "pyproject.toml").write_text(
            "[tool.octowrap]\nline-length = 40\n", encoding="utf-8"
        )
        # CWD has no config
        monkeypatch.chdir(tmp_path)
        src = "# A moderately long comment that fits at 88 but not at 40.\nx = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr(
            "sys.argv",
            ["octowrap", "--stdin-filename", str(sub / "mod.py"), "-"],
        )
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert all(len(line) <= 40 for line in out.splitlines())

    def test_stdin_filename_with_explicit_config(self, tmp_path, monkeypatch, capsys):
        """--config takes precedence over --stdin-filename for config discovery."""
        # stdin-filename's parent has one config
        sub = tmp_path / "project"
        sub.mkdir()
        (sub / "pyproject.toml").write_text(
            "[tool.octowrap]\nline-length = 40\n", encoding="utf-8"
        )
        # Explicit config has a different line-length
        explicit = tmp_path / "custom.toml"
        explicit.write_text("[tool.octowrap]\nline-length = 60\n", encoding="utf-8")

        monkeypatch.chdir(tmp_path)
        src = "# A moderately long comment that fits at 88 and at 60 but not at 40.\nx = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr(
            "sys.argv",
            [
                "octowrap",
                "--config",
                str(explicit),
                "--stdin-filename",
                str(sub / "mod.py"),
                "-",
            ],
        )
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        # With line-length=60, the comment should be wrapped (not at 40)
        assert all(len(line) <= 60 for line in out.splitlines())
        # But it should NOT be all on one line (which 88 would allow)
        comment_lines = [ln for ln in out.splitlines() if ln.startswith("#")]
        assert len(comment_lines) > 1

    def test_stdin_filename_basic_output(self, monkeypatch, capsys):
        """Normal output is unaffected by --stdin-filename."""
        src = "# This is a comment that was wrapped\n# at a short width previously.\nx = 1\n"
        monkeypatch.setattr("sys.stdin", io.StringIO(src))
        monkeypatch.setattr(
            "sys.argv", ["octowrap", "--stdin-filename", "src/app.py", "-"]
        )
        with pytest.raises(SystemExit, match="0"):
            main()
        out = capsys.readouterr().out
        assert (
            "# This is a comment that was wrapped at a short width previously." in out
        )
        assert "x = 1" in out


class TestDiffUtf8:
    """Tests for UTF-8 handling in diff mode."""

    def test_diff_reads_utf8(self, tmp_path, monkeypatch, capsys):
        """--diff correctly reads and diffs files with non-ASCII comments."""
        raw = (
            b"# Erd\xc5\x91s\xe2\x80\x93Kac theorem says \xcf\x80(x) is\n"
            b"# approximately x divided by ln x.\n"
            b"x = 1\n"
        )
        f = tmp_path / "utf8.py"
        f.write_bytes(raw)
        monkeypatch.setattr("sys.argv", ["octowrap", "--diff", str(f)])
        main()
        out = capsys.readouterr().out
        assert "Erd\u0151s" in out
