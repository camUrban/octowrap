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
octowrap <files_or_dirs> [--line-length 88] [--dry-run] [--diff] [-r] [-i]
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

## Configuration

Add a `[tool.octowrap]` section to your `pyproject.toml` to set project-level defaults:

```toml
[tool.octowrap]
line-length = 120
recursive = true
```

| Key           | Type | Default | CLI equivalent  |
|---------------|------|---------|-----------------|
| `line-length` | int  | 88      | `--line-length` |
| `recursive`   | bool | false   | `-r`            |

CLI flags always take precedence over config values.

## License

[MIT](LICENSE.md)