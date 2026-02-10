# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

octowrap is a Python CLI tool that rewraps Python `#` comments to a specified line length. It intelligently reformats comment blocks while preserving commented-out code, section dividers, list items, and tool directives (type: ignore, noqa, fmt: off, pragma: no cover, etc.). TODO/FIXME markers are detected and rewrapped with proper continuation indent (one space), with configurable patterns, case sensitivity, and multi-line collection.

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
codespell
docformatter --check --diff --config ./pyproject.toml .
ty check .

# Run all pre-commit hooks (ruff-check, ruff-format, codespell, docformatter, octowrap, ty)
pre-commit run --all-files
```

## Architecture

Core logic lives in `src/octowrap/rewrap.py`. `config.py` handles `pyproject.toml` config discovery and validation. `cli.py` imports and exposes `main` from `rewrap.py` to serve as the package entry point, and `__main__.py` enables `python -m octowrap`.

### rewrap.py pipeline

1. **CLI parsing** (`main()`): accepts paths (or `-` for stdin), `--line-length` (default 88), `--dry-run`, `--diff`, `--check`, `--no-recursive`, `-i` interactive, `--color`/`--no-color`, `--stdin-filename` (config discovery and diff labels in stdin mode). Recursive is on by default. Color auto-detects TTY and respects the `NO_COLOR` env var.
2. **Config loading**: `config.py` discovers `pyproject.toml` walking up from CWD (or uses `--config PATH`), reads `[tool.octowrap]`, validates keys/types. Raises `ConfigError` for malformed TOML or invalid settings (unknown keys, type mismatches). Supports `todo-patterns` (list, replaces defaults), `extend-todo-patterns` (list, adds to effective list), `todo-case-sensitive` (bool), `todo-multiline` (bool). Precedence: hardcoded defaults < config file < CLI args
3. **Stdin mode**: when `-` is passed as the sole path, reads from stdin, rewraps via `process_content()`, and writes to stdout. Supports `--diff`, `--check`, and `-l`. Cannot be mixed with other paths or `-i`.
4. **File discovery**: walks directories for `*.py` files, filtering out excluded paths (`DEFAULT_EXCLUDES` + config `exclude`/`extend-exclude`)
5. **Block parsing** (`parse_comment_blocks()`): groups consecutive same-indent comment lines into blocks, separating them from code
6. **Pragma handling**: `parse_pragma()` detects `# octowrap: off` / `# octowrap: on` directives (case-insensitive). When a block contains pragmas, it's split at pragma boundaries; segments between off/on are preserved as-is. State carries across blocks.
7. **Preservation checks**: each comment is tested against heuristics:
   - `is_likely_code()`: two-pass detection — 21 regex patterns match commented-out Python code, then `_looks_like_prose()` rescues false positives where a keyword is followed by a determiner (the/this/that/these/those) or specific phrases like "return to" / "assert that"
   - `is_divider()`: repeated-character separator lines
   - `is_list_item()`: bullets, numbered items
   - `is_tool_directive()`: tool directives (`type: ignore`, `noqa`, `fmt: off/on/skip`, `pragma: no cover`, `isort: skip`, `pylint: disable/enable`, `mypy:`, `pyright:`, `ruff: noqa`, PEP 484 type comments)
   - `is_todo_marker()`: detects TODO/FIXME-style markers (configurable patterns, case-insensitive by default, no colon required)
   - `is_todo_continuation()`: detects one-space-indented continuation lines for multi-line TODOs
8. **Rewrapping** (`rewrap_comment_block()`): uses `textwrap.fill()` with `break_on_hyphens=False` and `break_long_words=False`, respecting indent and max line length (min text width: 20 chars). Hyphenated words and URLs are kept intact (long words overflow rather than break). `_join_comment_lines()` heals previously broken hyphenated words when re-joining lines. TODO markers are rewrapped with their marker prefix on the first line and one-space continuation indent on subsequent lines.
9. **Output**: interactive per block approval (`a` accept, `A` accept all, `e` exclude, `f` flag, `s` skip, `q` quit) with colorized diffs showing the relative filepath, or batch mode. The `e` action wraps the original block with `# octowrap: off` / `# octowrap: on` pragmas so future runs skip it. The `f` action inserts a `# FIXME: Manually fix the below comment` marker above the original block for later human attention. Quitting stops all processing, including remaining files in a multi file run.

### Key functions

- `process_content(content, max_line_length, interactive)`: pure string-in/string-out transformation; core rewrap logic shared by both file and stdin paths
- `process_file(filepath, max_line_length, dry_run, interactive)`: reads file, calls `process_content()`, conditionally writes back. Uses atomic writes (temp file + `os.replace()`) to protect original files against interruptions.

## Tooling

- **Python 3.11+**, no runtime dependencies (stdlib only, uses `tomllib` for config)
- **uv** for package management; `.python-version` pins dev to 3.13 (docformatter's `untokenize` dep doesn't build on 3.14)
- **ruff** for linting, formatting, and import sorting
- **codespell** for spell checking
- **docformatter** for docstring formatting (config in `[tool.docformatter]` in pyproject.toml)
- **ty** for type checking
- **pytest** for testing (with pytest-cov for coverage)
- **pre-commit** hooks run ruff-check, ruff-format, codespell, docformatter, octowrap, and ty
- `.pre-commit-hooks.yaml` defines the `octowrap` hook for external consumers
