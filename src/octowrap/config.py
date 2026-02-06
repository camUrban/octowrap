"""Load octowrap settings from pyproject.toml [tool.octowrap]."""

import tomllib
from pathlib import Path


class ConfigError(Exception):
    """Raised when the [tool.octowrap] section contains invalid settings."""


_SCALAR_KEYS: dict[str, type] = {
    "line-length": int,
    "recursive": bool,
}

_LIST_STR_KEYS: set[str] = {"exclude", "extend-exclude"}

VALID_KEYS: set[str] = {*_SCALAR_KEYS, *_LIST_STR_KEYS}


def find_config_file(start_dir: Path | None = None) -> Path | None:
    """Walk up from *start_dir* looking for a pyproject.toml with [tool.octowrap].

    Returns the path to the first matching file, or ``None``.
    Malformed TOML files are silently skipped.
    """
    if start_dir is None:
        start_dir = Path.cwd()

    current = start_dir.resolve()
    while True:
        candidate = current / "pyproject.toml"
        if candidate.is_file():
            try:
                with open(candidate, "rb") as f:
                    data = tomllib.load(f)
                if "tool" in data and "octowrap" in data["tool"]:
                    return candidate
            except tomllib.TOMLDecodeError:
                pass
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def load_config(config_path: Path | None = None) -> dict:
    """Load and validate ``[tool.octowrap]`` from *config_path*.

    If *config_path* is ``None``, :func:`find_config_file` is called first.
    Returns a ``dict`` of validated settings (may be empty).
    Raises :class:`ConfigError` on unknown keys or type mismatches.
    """
    if config_path is None:
        config_path = find_config_file()
    if config_path is None:
        return {}

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    section = data.get("tool", {}).get("octowrap", {})
    if not section:
        return {}

    result: dict = {}
    for key, value in section.items():
        if key not in VALID_KEYS:
            raise ConfigError(f"Unknown config key: {key!r}")

        if key in _LIST_STR_KEYS:
            if not isinstance(value, list):
                raise ConfigError(
                    f"Config key {key!r} expects a list of strings, "
                    f"got {type(value).__name__}"
                )
            for i, item in enumerate(value):
                if not isinstance(item, str):
                    raise ConfigError(
                        f"Config key {key!r} expects a list of strings, "
                        f"but element {i} is {type(item).__name__}"
                    )
        else:
            expected_type = _SCALAR_KEYS[key]

            # bool is a subclass of int in Python, so guard against it explicitly.
            if expected_type is int and isinstance(value, bool):
                raise ConfigError(
                    f"Config key {key!r} expects an integer, got a boolean"
                )

            if not isinstance(value, expected_type):
                raise ConfigError(
                    f"Config key {key!r} expects {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

        result[key] = value

    return result
