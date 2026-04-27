# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

octowrap is a Python CLI tool that rewraps Python `#` comments to a specified line length. It intelligently reformats comment blocks while preserving commented-out code, section dividers, section headers (e.g. `# === Title ===`), and tool directives (type: ignore, noqa, fmt: off, pragma: no cover, etc.). List items are rewrapped with hanging indent aligned to the text after the marker (`list-wrap`, enabled by default). TODO/FIXME markers are detected and rewrapped with proper continuation indent (one space), with configurable patterns, case sensitivity, and multi-line collection. Overflowing inline comments (`code  # comment`) are extracted into standalone block comments above the code line and wrapped normally; tool directives are always preserved in place.

## Commands

```bash
# Install in dev mode with all dependencies
uv sync

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

# Run all pre-commit hooks (ruff-check, ruff-format, codespell, docformatter, octowrap,
# and ty)
pre-commit run --all-files
```

## Architecture

Core logic lives in `src/octowrap/rewrap.py`. `config.py` handles `pyproject.toml` config discovery and validation. `diff.py` provides git diff parsing and changed-line detection for `--diff-only` mode. `cli.py` imports and exposes `main` from `rewrap.py` to serve as the package entry point, and `__main__.py` enables `python -m octowrap`.

### rewrap.py pipeline

1. **CLI parsing** (`main()`): accepts paths (or `-` for stdin), `--line-length` (default 88), `--dry-run`, `--diff`, `--check`, `--no-recursive`, `--no-inline`, `-i` interactive, `--color`/`--no-color`, `--stdin-filename` (config discovery and diff labels in stdin mode), `--diff-only` (only process blocks overlapping lines changed in git), `--diff-base REF` (git ref to diff against, default HEAD, implies `--diff-only`). Recursive and inline are on by default. Color auto-detects TTY and respects the `NO_COLOR` env var.
2. **Config loading**: `config.py` discovers `pyproject.toml` walking up from CWD (or uses `--config PATH`), reads `[tool.octowrap]`, validates keys/types. Raises `ConfigError` for malformed TOML or invalid settings (unknown keys, type mismatches). Supports `inline` (bool), `list-wrap` (bool, default true), `todo-patterns` (list, replaces defaults), `extend-todo-patterns` (list, adds to effective list), `todo-case-sensitive` (bool), `todo-multiline` (bool), `diff-only` (bool), `diff-base` (str). Precedence: hardcoded defaults < config file < CLI args
3. **Stdin mode**: when `-` is passed as the sole path, reads from stdin, rewraps via `process_content()`, and writes to stdout. Supports `--diff`, `--check`, and `-l`. Cannot be mixed with other paths or `-i`.
4. **File discovery**: walks directories for `*.py` files, filtering out excluded paths (`DEFAULT_EXCLUDES` + config `exclude`/`extend-exclude`)
5. **Block parsing** (`parse_comment_blocks()`): groups consecutive same-indent comment lines into blocks, separating them from code
6. **Pragma handling**: `parse_pragma()` detects `# octowrap: off` / `# octowrap: on` directives (case-insensitive). When a block contains pragmas, it's split at pragma boundaries; segments between off/on are preserved as-is. State carries across blocks.
7. **Preservation checks**: each comment is tested against heuristics:
   - `is_likely_code()`: two-pass detection. 21 regex patterns match commented-out Python code, then `_looks_like_prose()` rescues false positives where a keyword is followed by a determiner (the/this/that/these/those) or specific phrases like "return to" / "assert that"
   - `is_divider()`: repeated-character separator lines
   - `is_section_header()`: lines like `# === Title ===` with the same delimiter character (`-`, `=`, `#`, `*`, `_`) on both sides, at least three per side, asymmetric counts allowed, padding optional. Preserved verbatim including overflow.
   - `is_list_item()` / `extract_list_marker()`: bullets, numbered items; when `list-wrap` is enabled (default), long list items are rewrapped with hanging indent
   - `is_tool_directive()`: tool directives (`type: ignore`, `noqa`, `fmt: off/on/skip`, `pragma: no cover`, `isort: skip`, `pylint: disable/enable`, `mypy:`, `pyright:`, `ruff: noqa`, `noinspection`, PEP 484 type comments)
   - `is_todo_marker()`: detects TODO/FIXME-style markers (configurable patterns, case-insensitive by default, no colon required)
   - `is_todo_continuation()`: detects one-space-indented continuation lines for multi-line TODOs
   - `find_inline_comment()`: string-aware scanner that returns the index of the `#` starting an inline comment, tracking single/double/triple quotes and backslash escapes
   - `extract_inline_comment()`: splits a code line into `(code_part, comment_text)` using `find_inline_comment()`; returns `None` for full-line comments or lines without `#`
   - `_should_extract_inline()`: returns `True` when a line overflows `max_line_length`, has an extractable inline comment, and the comment is not a tool directive
8. **Inline comment extraction**: during code block iteration in `process_content()`, each line is checked via `_should_extract_inline()`. When True, the inline comment is extracted into a synthetic comment block above the code line and wrapped using `rewrap_comment_block()`. Skipped when disabled (pragma off), `inline=False`, or the comment is a tool directive. A tokenize-derived position set (`compute_comment_positions()`) gates extraction so that `#` characters living inside a string literal that spans multiple lines (where the single-line scanner has no visible quote context) are never mistaken for inline comments; when tokenize fails (syntactically invalid Python), the check is skipped and the single-line string-aware scanner is trusted on its own. In interactive mode, inline extractions use the same accept/exclude/flag/skip/undo/quit flow as comment blocks.
9. **Rewrapping** (`rewrap_comment_block()` -> `_block_prompt_units()` -> `_render_paragraph()`): `_block_prompt_units()` splits a same-indent comment block into paragraph units (wrap / blank / preserve / todo / list), groups consecutive list items into a single unit, renders each via `_render_paragraph()`, and returns `(raw_start, original, rewrapped)` tuples. `rewrap_comment_block()` is a thin wrapper that concatenates all rewrapped lines for the non-interactive path. `_render_paragraph()` uses `textwrap.fill()` with `break_on_hyphens=False` and `break_long_words=False`, respecting indent and max line length (min text width: 20 chars); hyphenated words and URLs stay intact (long words overflow rather than break). `_join_comment_lines()` heals previously broken hyphenated words and erroneous bracket-adjacent whitespace (`(`, `)`, `[`, `]`). TODO markers rewrap with their marker on the first line and one-space continuation indent; list items rewrap with hanging indent aligned to the text after the marker (`list-wrap` config key, default `True`).
10. **Output**: interactive prompts happen at the **paragraph** level, not the whole block (`a` accept, `A` accept all remaining paragraphs in the file, `e` exclude, `f` flag, `s` skip, `u` undo, `q` quit), with colorized diffs showing the relative filepath and a `[X/Y]` progress indicator, or batch mode. A block containing mixed paragraph types (e.g. prose + TODO, or prose + a tool directive) produces one prompt per changed paragraph; unchanged paragraphs (preserved dividers, tool directives that wouldn't move) pass through silently without prompting. Consecutive list items are grouped into a single prompt so a multi-item list reviews as one logical change. The progress indicator is powered by an upfront pre-scan (`count_changed_blocks()`) that counts how many **paragraphs** will change across all files. The `e` action wraps just the selected paragraph with `# octowrap: off` / `# octowrap: on` pragmas so future runs skip it. The `f` action inserts a `# FIXME: Manually fix the below comment` marker above the selected paragraph and wraps both the marker and the original paragraph in `# octowrap: off` / `# octowrap: on` pragmas, so subsequent runs skip the flagged region rather than re-prompting on the bare original. The `u` action pops the most recent decision from a session-wide log and re-prompts at that position; it works across files (a previously-written file is reverted on disk lazily at q-flush or on the next walk-through). `[u]ndo` is hidden at the very first prompt of a session when there is nothing to pop. Quitting stops all processing, including remaining files in a multi file run; on quit, every file on disk is reconciled with the final decision log so undone writes are reverted.

### Key functions

- `process_content(content, max_line_length, interactive, ..., changed_lines)`: pure string-in/string-out transformation; core rewrap logic shared by both file and stdin paths. When `changed_lines` (a set of 0-based line indices) is not `None`, only blocks overlapping those lines are processed.
- `process_file(filepath, max_line_length, dry_run, interactive, ..., changed_lines)`: reads a file and writes it back. Non-interactive runs go through `_drive_file()` + `_atomic_write()`. Interactive runs are routed through `_run_session([filepath], ...)` so single-file callers exercise the same replay-aware driver that `main()` uses. Atomic writes (temp file + `os.replace()`) protect originals against interruptions.
- `_run_session(filepaths, _state, ...)`: session driver shared by `main()` and interactive `process_file()`. Iterates files, caches each file's original in `_state["originals"]`, runs `process_content()` with the file's slice of `_state["decisions"]`, atomic-writes when output differs from `last_written`, and on a `"rewind"` status jumps back to the rewind target's file. A `finally`-block flush (`_flush_dirty_at_quit()`) reconciles every dirty file with the final decision log on quit or normal exit. Yields one result dict per processed file so callers can interleave per-file output with subsequent prompts.
- `Decision(filepath, cursor, action)`: one recorded interactive decision in the session-wide log. The cursor is `(block_start_idx, unit_raw_start)` for paragraph prompts and `(block_start_idx, "inline", line_idx)` for inline-extraction prompts; both are computed against the *original* file content so they survive `e`/`f` mutations during replay. The session log is the source of truth for replay and undo.
- `count_changed_blocks(content, max_line_length, ..., changed_lines)`: counts paragraph-level prompt units whose rewrapped output differs from the original, respecting pragmas. When `inline=True`, also counts overflowing inline comments that would be extracted. Used by `main()` to pre-scan files for the interactive progress indicator. Only counts non-pragma blocks (pragma blocks are auto-applied, not prompted). Respects `changed_lines` filtering.
- `_block_prompt_units(block, max_line_length, ...)`: splits a comment block into paragraph units with `raw_start`, `original`, and `rewrapped` fields. Consecutive list-item paragraphs are merged into a single unit. Used by both `process_content()` (interactive loop) and `count_changed_blocks()`. `rewrap_comment_block()` delegates to this and flattens.
- `parse_diff_line_numbers(diff_text)` (in `diff.py`): parses `git diff -U0` output into a dict mapping file paths to sets of 0-based changed line indices.
- `get_changed_lines(base)` (in `diff.py`): runs `git diff -U0` against a base ref and returns the parsed result. Raises `NotAGitRepoError` outside a git repo.

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
