import runpy
import subprocess

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
    """End to end tests for pyproject.toml config support."""

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
        """Unknown config keys cause a non zero exit."""
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
    """Tests for --color/--no-color/auto detect."""

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
