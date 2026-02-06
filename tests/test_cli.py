import runpy
import subprocess

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
        """Without -r, only top-level .py files are processed."""
        (tmp_path / "top.py").write_bytes(WRAPPABLE_CONTENT)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "1 file(s) reformatted." in out

    def test_directory_recursive(self, tmp_path, monkeypatch, capsys):
        """With -r, nested .py files are also found."""
        (tmp_path / "top.py").write_bytes(WRAPPABLE_CONTENT)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.py").write_bytes(WRAPPABLE_CONTENT)
        monkeypatch.setattr("sys.argv", ["octowrap", "-r", str(tmp_path)])
        main()
        out = capsys.readouterr().out
        assert "2 file(s) reformatted." in out

    def test_error_handling(self, tmp_path, monkeypatch, capsys):
        """A file that can't be processed should log an error and continue."""
        good = tmp_path / "good.py"
        good.write_bytes(WRAPPABLE_CONTENT)
        bad = tmp_path / "bad.py"
        bad.write_bytes(WRAPPABLE_CONTENT)

        import octowrap.rewrap as mod

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
        """Running via python -m octowrap exercises __main__.py in-process."""
        f = tmp_path / "a.py"
        f.write_bytes(b"x = 1\n")
        monkeypatch.setattr("sys.argv", ["octowrap", str(f)])
        runpy.run_module("octowrap", run_name="__main__")
        out = capsys.readouterr().out
        assert "0 file(s) reformatted." in out

    def test_console_script(self, tmp_path):
        """The installed 'octowrap' console script works end-to-end."""
        f = tmp_path / "a.py"
        f.write_bytes(WRAPPABLE_CONTENT)
        result = subprocess.run(
            ["octowrap", str(f)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "1 file(s) reformatted." in result.stdout
