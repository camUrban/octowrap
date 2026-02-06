# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

octowrap is a Python CLI tool that rewraps Python `#` comments to a specified line length. It intelligently reformats comment blocks while preserving commented-out code, section dividers, list items, special markers (TODO, FIXME, NOTE, XXX, HACK), and tool directives (type: ignore, noqa, fmt: off, pragma: no cover, etc.).

## Commands

```bash
# Install in dev mode with all dependencies
uv pip install -e ".[dev]"

# Run the tool
octowrap <files_or_dirs>

# Run tests (coverage enabled by default via pyproject.toml)
pytest tests/

# Lint, format, and type-check
ruff check .
ruff format .
ty check .

# Run all pre-commit hooks (ruff-check, ruff-format, ty)
pre-commit run --all-files
```

## Architecture

Core logic lives in `src/octowrap/rewrap.py`. `config.py` handles `pyproject.toml` config discovery and validation. `cli.py` imports and exposes `main` from `rewrap.py` to serve as the package entry point, and `__main__.py` enables `python -m octowrap`.

### rewrap.py pipeline

1. **CLI parsing** (`main()`) — accepts paths (or `-` for stdin), `--line-length` (default 88), `--dry-run`, `--diff`, `--check`, `--no-recursive`, `-i` interactive, `--color`/`--no-color`. Recursive is on by default. Color auto-detects TTY and respects the `NO_COLOR` env var.
2. **Config loading** — `config.py` discovers `pyproject.toml` walking up from CWD (or uses `--config PATH`), reads `[tool.octowrap]`, validates keys/types. Precedence: hardcoded defaults < config file < CLI args
3. **Stdin mode** — when `-` is passed as the sole path, reads from stdin, rewraps via `process_content()`, and writes to stdout. Supports `--diff`, `--check`, and `-l`. Cannot be mixed with other paths or `-i`.
4. **File discovery** — walks directories for `*.py` files, filtering out excluded paths (`DEFAULT_EXCLUDES` + config `exclude`/`extend-exclude`)
5. **Block parsing** (`parse_comment_blocks()`) — groups consecutive same-indent comment lines into blocks, separating them from code
6. **Pragma handling** — `parse_pragma()` detects `# octowrap: off` / `# octowrap: on` directives (case-insensitive). When a block contains pragmas, it's split at pragma boundaries; segments between off/on are preserved as-is. State carries across blocks.
7. **Preservation checks** — each comment is tested against heuristics:
   - `is_likely_code()` — 21 patterns detecting commented-out Python code
   - `is_divider()` — repeated-character separator lines
   - `is_list_item()` — bullets, numbered items, special markers
   - `is_tool_directive()` — tool directives (`type: ignore`, `noqa`, `fmt: off/on/skip`, `pragma: no cover`, `isort: skip`, `pylint: disable/enable`, `mypy:`, `pyright:`, `ruff: noqa`, PEP 484 type comments)
8. **Rewrapping** (`rewrap_comment_block()`) — uses `textwrap.fill()` respecting indent and max line length (min text width: 20 chars)
9. **Output** — interactive per-block approval (`a` accept, `A` accept all, `s` skip, `q` quit) with colorized diffs, or batch mode

### Key functions

- `process_content(content, max_line_length, interactive)` — pure string-in/string-out transformation; core rewrap logic shared by both file and stdin paths
- `process_file(filepath, max_line_length, dry_run, interactive)` — reads file, calls `process_content()`, conditionally writes back

## Tooling

- **Python 3.11+**, no runtime dependencies (stdlib only, uses `tomllib` for config)
- **uv** for package management
- **ruff** for linting, formatting, and import sorting
- **ty** for type checking
- **pytest** for testing (with pytest-cov for coverage)
- **pre-commit** hooks run ruff-check, ruff-format, and ty
- `.pre-commit-hooks.yaml` defines the `octowrap` hook for external consumers
