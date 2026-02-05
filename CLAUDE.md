# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

octowrap is a Python CLI tool that rewraps Python `#` comments to a specified line length. It intelligently reformats comment blocks while preserving commented-out code, section dividers, list items, and special markers (TODO, FIXME, NOTE, XXX, HACK).

## Commands

```bash
# Install in dev mode with all dependencies
uv pip install -e ".[dev]"

# Run the tool
python src/octowrap/rewrap.py <files_or_dirs>

# Run tests
pytest tests/

# Lint and format
ruff check .
ruff format .

# Run all pre-commit hooks
pre-commit run --all-files
```

## Architecture

All logic currently lives in `src/octowrap/rewrap.py`. `cli.py` imports and exposes `main` from `rewrap.py` to serve as the package entry point, and `__main__.py` enables `python -m octowrap`.

### rewrap.py pipeline

1. **CLI parsing** (`main()`) — accepts paths, `--line-length` (default 88), `--dry-run`, `--diff`, `-r` recursive, `-a` accept-all
2. **File discovery** — walks directories for `*.py` files
3. **Block parsing** (`parse_comment_blocks()`) — groups consecutive same-indent comment lines into blocks, separating them from code
4. **Preservation checks** — each comment is tested against heuristics:
   - `is_likely_code()` — 21 patterns detecting commented-out Python code
   - `is_divider()` — repeated-character separator lines
   - `is_list_item()` — bullets, numbered items, special markers
5. **Rewrapping** (`rewrap_comment_block()`) — uses `textwrap.fill()` respecting indent and max line length (min text width: 20 chars)
6. **Output** — interactive per-block approval with colorized diffs, or batch mode with `-a`

## Tooling

- **Python 3.10+**, no runtime dependencies (stdlib only)
- **uv** for package management
- **ruff** for linting and formatting (default config, no overrides in pyproject.toml)
- **pytest** for testing
- **pre-commit** hooks run ruff-check and ruff-format
