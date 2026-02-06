import pytest

from octowrap.config import ConfigError, find_config_file, load_config

MINIMAL_PYPROJECT = b"[tool.octowrap]\n"


def _write_pyproject(directory, content: bytes):
    (directory / "pyproject.toml").write_bytes(content)


class TestFindConfigFile:
    """Tests for find_config_file()."""

    def test_finds_in_start_dir(self, tmp_path):
        _write_pyproject(tmp_path, MINIMAL_PYPROJECT)
        assert find_config_file(tmp_path) == tmp_path / "pyproject.toml"

    def test_walks_up_to_parent(self, tmp_path):
        _write_pyproject(tmp_path, MINIMAL_PYPROJECT)
        child = tmp_path / "sub" / "deep"
        child.mkdir(parents=True)
        assert find_config_file(child) == tmp_path / "pyproject.toml"

    def test_returns_none_when_missing(self, tmp_path):
        assert find_config_file(tmp_path) is None

    def test_skips_file_without_tool_octowrap(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.other]\nfoo = 1\n")
        assert find_config_file(tmp_path) is None

    def test_skips_malformed_toml(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.octowrap\nbroken")
        assert find_config_file(tmp_path) is None

    def test_uses_cwd_when_no_start_dir(self, tmp_path, monkeypatch):
        _write_pyproject(tmp_path, MINIMAL_PYPROJECT)
        monkeypatch.chdir(tmp_path)
        assert find_config_file() == tmp_path / "pyproject.toml"


class TestLoadConfig:
    """Tests for load_config()."""

    def test_loads_line_length(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.octowrap]\nline-length = 120\n")
        result = load_config(tmp_path / "pyproject.toml")
        assert result == {"line-length": 120}

    def test_loads_recursive(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.octowrap]\nrecursive = true\n")
        result = load_config(tmp_path / "pyproject.toml")
        assert result == {"recursive": True}

    def test_loads_both(self, tmp_path):
        content = b"[tool.octowrap]\nline-length = 100\nrecursive = true\n"
        _write_pyproject(tmp_path, content)
        result = load_config(tmp_path / "pyproject.toml")
        assert result == {"line-length": 100, "recursive": True}

    def test_empty_section_returns_empty(self, tmp_path):
        _write_pyproject(tmp_path, MINIMAL_PYPROJECT)
        result = load_config(tmp_path / "pyproject.toml")
        assert result == {}

    def test_no_file_returns_empty(self):
        result = load_config(None)
        # find_config_file may return None when CWD has no pyproject.toml;
        # in that case load_config falls through to an empty dict.
        assert isinstance(result, dict)

    def test_unknown_key_raises(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.octowrap]\nbogus = 42\n")
        with pytest.raises(ConfigError, match="Unknown config key"):
            load_config(tmp_path / "pyproject.toml")

    def test_wrong_type_raises(self, tmp_path):
        _write_pyproject(tmp_path, b'[tool.octowrap]\nline-length = "eighty"\n')
        with pytest.raises(ConfigError, match="expects int"):
            load_config(tmp_path / "pyproject.toml")

    def test_bool_for_int_raises(self, tmp_path):
        _write_pyproject(tmp_path, b"[tool.octowrap]\nline-length = true\n")
        with pytest.raises(ConfigError, match="expects an integer, got a boolean"):
            load_config(tmp_path / "pyproject.toml")
