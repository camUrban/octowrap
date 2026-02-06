# octowrap

A CLI tool that rewraps octothorpe (`#`) Python comments to a specified line length while preserving commented-out code, section dividers, list items, and special markers.

## Features

- Rewraps comment blocks to a configurable line length (default 88)
- Preserves commented-out Python code (detected via 21 heuristic patterns)
- Preserves section dividers (`# --------`, `# ========`, etc.)
- Preserves list items (bullets, numbered items)
- Preserves special markers (`TODO`, `FIXME`, `NOTE`, `XXX`, `HACK`)
- Applies changes automatically by default, or use `-i` for interactive per-block approval with colorized diffs
- Project-level configuration via `[tool.octowrap]` in `pyproject.toml`

## Development Setup

```bash
git clone https://github.com/cameronurban/octowrap.git
cd octowrap
uv pip install -e ".[dev]"
```

## Usage

```bash
octowrap <files_or_dirs> [--line-length 88] [--dry-run] [--diff] [--check] [--no-recursive] [-i]
```

### Example

Before:

```python
# This is a long comment that has been written without much regard for line length and really should be wrapped to fit within a reasonable number of columns.
```

After (`--line-length 88`):

```python
# This is a long comment that has been written without much regard for line
# length and really should be wrapped to fit within a reasonable number of
# columns.
```

## Pre-commit Hook

Add octowrap to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/camUrban/octowrap
  rev: v0.1.0
  hooks:
    - id: octowrap
      # args: [-l, "79"]       # custom line length
      # args: [--check]        # fail without modifying (useful for CI)
```

## Configuration

Add a `[tool.octowrap]` section to your `pyproject.toml` to set project-level defaults:

```toml
[tool.octowrap]
line-length = 120
recursive = false
exclude = ["migrations", "generated"]
extend-exclude = ["vendor"]
```

| Key              | Type       | Default | CLI equivalent   |
|------------------|------------|---------|------------------|
| `line-length`    | int        | 88      | `--line-length`  |
| `recursive`      | bool       | true    | `--no-recursive` |
| `exclude`        | list[str]  | —       | —                |
| `extend-exclude` | list[str]  | —       | —                |

CLI flags always take precedence over config values.

`exclude` replaces the built-in default exclude list entirely. `extend-exclude` adds patterns to the defaults (or to `exclude` if set). Default excludes: `.git`, `.hg`, `.svn`, `.bzr`, `.venv`, `venv`, `.tox`, `.nox`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `__pycache__`, `__pypackages__`, `_build`, `build`, `dist`, `node_modules`, `.eggs`. Patterns are matched against individual path components using `fnmatch`.

## License

[MIT](LICENSE.md)