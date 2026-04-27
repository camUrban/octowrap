# octowrap

[![CI](https://github.com/camUrban/octowrap/actions/workflows/ci.yml/badge.svg)](https://github.com/camUrban/octowrap/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/octowrap)](https://pypi.org/project/octowrap/)
[![Python](https://img.shields.io/pypi/pyversions/octowrap)](https://pypi.org/project/octowrap/)
[![License](https://img.shields.io/github/license/camUrban/octowrap)](LICENSE.md)

Rewrap Python `#` comments to a line length you choose — without touching commented-out code, section dividers, TODO/FIXME markers, or tool directives.

<p align="center">
  <img src="https://raw.githubusercontent.com/camUrban/octowrap/main/docs/hero/demo.svg" alt="Animated terminal demo of `octowrap -i` reviewing three comment changes in a small Python file: a long prose comment, a TODO marker, and an overflowing inline comment. Each diff appears in red/green and is accepted with a single keystroke." width="840">
</p>

## Features

- Rewraps comment blocks to a configurable line length (default 88)
- Keeps hyphenated words intact (never breaks `command-line-interface` at hyphens)
- Keeps long words and URLs intact (they overflow the line length rather than being broken mid-word)
- Heals previously broken hyphenated words on rewrap (e.g. `re-` / `validate` -> `re-validate`)
- Heals erroneous spaces at bracket boundaries on rewrap (e.g. `( text)` -> `(text)`, `text )` -> `text)`)
- Preserves commented-out Python code (detected via 21 heuristic patterns with a prose disqualifier to avoid false positives on natural English)
- Preserves section dividers (`# --------`, `# ========`, etc.)
- Preserves section headers (`# === Title ===`, `# --- Title ---`, `# ### Title ###`, `# *** Title ***`, `# ___ Title ___`) — same delimiter character on both sides, three or more per side, asymmetric counts allowed
- Rewraps list items (bullets, numbered, lettered) with hanging indent aligned to the text after the marker; collects continuation lines and handles nesting naturally. Disable with `list-wrap = false`.
- Rewraps TODO/FIXME markers with proper continuation indent, with configurable patterns, case sensitivity, and multi-line collection
- Extracts overflowing inline comments (`code  # comment`) into standalone block comments above the code line when the line exceeds the line length, then wraps them normally. Tool directives (`# type: ignore`, `# noqa`, etc.) are always preserved in place. Disable with `--no-inline`.
- Preserves tool directives (`type: ignore`, `noqa`, `fmt: off`, `pragma: no cover`, `pylint: disable`, `noinspection`, etc.)
- Supports `# octowrap: off` / `# octowrap: on` pragma comments to disable rewrapping for regions of a file
- Applies changes automatically by default, or use `-i` for interactive per-paragraph approval with colorized diffs and a `[X/Y]` progress indicator (`a` accept, `A` accept all remaining paragraphs in the file, `e` exclude, `f` flag, `s` skip, `u` undo, `q` quit). A single comment block that mixes prose, a TODO, and a tool directive reviews as separate diffs — one per changed paragraph — so you can see exactly what's changing. Consecutive list items group into a single prompt. Flagging wraps the paragraph with a FIXME marker and `# octowrap: off` / `# octowrap: on` pragmas so reruns skip it. Undo pops the most recent decision and re-prompts at that position; it works across files (a previously-written file is reverted on disk lazily — at quit or on the next walk-through). Quitting stops all processing, including remaining files; on quit, every file on disk is reconciled with the final decision log so undone writes are reverted.
- Reads from stdin when `-` is passed as the path (like black/ruff/isort)
- Auto-detects color support; respects `--no-color`, `--color`, and the `NO_COLOR` env var
- Atomic file writes (temp file + rename) to protect against interruptions and power loss
- Incremental adoption via `--diff-only`: only process comments on lines changed in git, so teams can adopt octowrap gradually without reformatting the entire codebase
- Project-level configuration via `[tool.octowrap]` in `pyproject.toml`

## Development Setup

```bash
git clone https://github.com/camUrban/octowrap.git
cd octowrap
uv venv            # uses .python-version (3.13)
uv pip install -e ".[dev]"
```

> **Note:** The dev environment is pinned to Python 3.13 via `.python-version` because docformatter's `untokenize` dependency doesn't build on 3.14. The runtime itself supports 3.11+.

## Usage

```bash
octowrap <files_or_dirs> [--line-length 88] [--config PATH] [--stdin-filename PATH] [--dry-run] [--diff] [--check] [--no-recursive] [--no-inline] [--diff-only] [--diff-base REF] [-i] [--color | --no-color]
```

### Stdin/stdout

Pass `-` as the path to read from stdin and write to stdout:

```bash
echo "# A very long comment that needs rewrapping to a shorter width." | octowrap -
cat file.py | octowrap - --diff          # show diff
cat file.py | octowrap - --check         # exit 1 if changes needed
cat file.py | octowrap - -l 79           # custom line length
```

Use `--stdin-filename` to provide the original file path for config discovery and diff labels (useful for editor integrations like VS Code and Vim that pipe buffers via stdin):

```bash
cat file.py | octowrap - --stdin-filename src/app.py --diff
```

Note: `-` cannot be mixed with other paths and is incompatible with `-i` (interactive mode). `--stdin-filename` requires `-`.

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

## Inline Comment Extraction

When a code line with an inline comment exceeds the line length, octowrap extracts the comment into a standalone block comment above the code:

Before:

```python
x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit
```

After (`--line-length 88`):

```python
# This comment pushes the line way past the limit
x = some_really_long_function_call(arg1, arg2)
```

Tool directives (`# type: ignore`, `# noqa`, `# fmt: off`, etc.) are never extracted, even when the line overflows. Disable this behavior entirely with `--no-inline` or `inline = false` in config.

## TODO/FIXME Rewrapping

By default, `TODO` and `FIXME` markers are detected (case-insensitive, no colon required) and rewrapped with the marker on the first line and a one-space continuation indent on subsequent lines:

Before:

```python
# TODO: Refactor this function to use the new async API instead of the old synchronous one, and update all callers.
```

After (`--line-length 88`):

```python
# TODO: Refactor this function to use the new async API instead of the old
#  synchronous one, and update all callers.
```

Multi-line TODOs (continuation lines starting with exactly one space) are collected and rewrapped together:

```python
# TODO: This is a long todo
#  that continues on the next line
```

Configure TODO handling via `pyproject.toml`:

```toml
[tool.octowrap]
todo-patterns = ["todo", "fixme", "hack"]    # replace default patterns
extend-todo-patterns = ["note"]              # add to effective patterns
todo-case-sensitive = true                   # match patterns literally
todo-multiline = false                       # don't collect continuations
```

Setting `todo-patterns = []` disables TODO detection entirely, causing former TODO lines to be rewrapped as regular prose.

## List Item Wrapping

Long list items are rewrapped with hanging indent aligned to the text after the marker:

Before:

```python
# - This is a very long bullet point that exceeds the line length and should be wrapped to fit within the configured width.
# 1. This is a very long numbered item that also exceeds the line length and needs to be wrapped properly.
```

After (`--line-length 72`):

```python
# - This is a very long bullet point that exceeds the line length and
#   should be wrapped to fit within the configured width.
# 1. This is a very long numbered item that also exceeds the line length
#    and needs to be wrapped properly.
```

Nesting is handled naturally — each item wraps independently at its own indent level:

```python
# - Top-level item
#   - Nested item that is quite long and will be wrapped with its own
#     hanging indent aligned to the nested marker
```

Continuation lines indented to at least the marker's text column are collected and rewrapped together. Disable with `list-wrap = false` in `pyproject.toml`.

## Disabling Rewrapping

Use pragma comments to protect regions of a file from rewrapping, similar to `# fmt: off/on` in black/ruff:

```python
# octowrap: off
# This comment will not be rewrapped,
# no matter how long or short
# the lines are.
# octowrap: on

# This comment will be rewrapped normally.
```

- Directives are case-insensitive (`# OCTOWRAP: OFF` works)
- Must be a standalone comment line (inline `x = 1  # octowrap: off` is ignored)
- `# octowrap: off` without a matching `on` disables rewrapping through end of file
- Pragma lines themselves are always preserved as-is

## Incremental Adoption

Use `--diff-only` to only process comment blocks that overlap with lines changed in git. This lets teams adopt octowrap gradually without reformatting the entire codebase in one go:

```bash
# Only rewrap comments on lines you've changed vs HEAD
octowrap --diff-only .

# Only rewrap comments changed relative to main (useful in CI)
octowrap --diff-only --diff-base main --check .

# Preview what would change
octowrap --diff-only --diff .
```

`--diff-base REF` specifies the git ref to diff against (default: `HEAD`). Passing `--diff-base` implies `--diff-only`.

Comment blocks are processed at the block level: if any line in a comment block overlaps with a changed line, the entire block is rewrapped. This is safe because comment blocks are syntactically independent.

### Pre-commit with `--diff-only`

The most common use case is adding octowrap to pre-commit so it only enforces wrapping on comments you're already changing:

```yaml
- repo: https://github.com/camUrban/octowrap
  rev: v0.6.0
  hooks:
    - id: octowrap
      args: [--diff-only]
```

Or in check-only mode (fail without modifying):

```yaml
- repo: https://github.com/camUrban/octowrap
  rev: v0.6.0
  hooks:
    - id: octowrap
      args: [--diff-only, --check]
```

Both `diff-only` and `diff-base` can also be set in `pyproject.toml`:

```toml
[tool.octowrap]
diff-only = true
diff-base = "main"
```

Note: `--diff-only` requires a git repository and cannot be used with stdin mode (`-`).

## Editor Integration

### PyCharm

Settings -> Tools -> File Watchers -> Add:

- **File type:** Python
- **Program:** `$ProjectFileDir$/.venv/Scripts/octowrap.exe` (or `.venv/bin/octowrap` on Unix)
- **Arguments:** `$FilePath$`
- **Output paths to refresh:** `$FilePath$`
- **Working directory:** `$ProjectFileDir$`

## Pre-commit Hook

Add octowrap to your `.pre-commit-config.yaml`:

```yaml
- repo: https://github.com/camUrban/octowrap
  rev: v0.6.0
  hooks:
    - id: octowrap
      # args: [-l, "79"]       # custom line length
      # args: [--check]        # fail without modifying (useful for CI)
      # args: [--diff-only]    # only process comments on changed lines
```

## Exit Codes

| Code | Meaning                                                                      |
|------|------------------------------------------------------------------------------|
| 0    | Success (no changes needed, or changes applied)                              |
| 1    | `--check` mode: files would be reformatted                                   |
| 2    | Error processing one or more files (e.g., encoding error, permission denied) |

Errors are printed to stderr. This behavior matches ruff.

## GitHub Actions

Use `--check` in CI to fail if any comments would be rewrapped:

```yaml
- name: Install octowrap
  run: pip install octowrap

- name: Check comment wrapping
  run: octowrap --check .
```

### Incremental CI check

To only enforce wrapping on comments changed in the PR (for gradual adoption), use `--diff-only --diff-base origin/main`. A full git history is required so that `origin/main` is available for comparison:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- name: Install octowrap
  run: pip install octowrap

- name: Check changed comments
  run: octowrap --diff-only --diff-base origin/main --check .
```

## Configuration

Add a `[tool.octowrap]` section to your `pyproject.toml` to set project-level defaults:

```toml
[tool.octowrap]
line-length = 120
recursive = false
inline = true
exclude = ["migrations", "generated"]
extend-exclude = ["vendor"]
```

| Key                    | Type      | Default             | CLI equivalent   |
|------------------------|-----------|---------------------|------------------|
| `line-length`          | int       | 88                  | `--line-length`  |
| `recursive`            | bool      | true                | `--no-recursive` |
| `inline`               | bool      | true                | `--no-inline`    |
| `list-wrap`            | bool      | true                | —                |
| `diff-only`            | bool      | false               | `--diff-only`    |
| `diff-base`            | str       | `"HEAD"`            | `--diff-base`    |
| `exclude`              | list[str] | —                   | —                |
| `extend-exclude`       | list[str] | —                   | —                |
| `todo-patterns`        | list[str] | `["todo", "fixme"]` | —                |
| `extend-todo-patterns` | list[str] | —                   | —                |
| `todo-case-sensitive`  | bool      | false               | —                |
| `todo-multiline`       | bool      | true                | —                |

CLI flags always take precedence over config values. Use `--config PATH` to point to a specific `pyproject.toml` instead of relying on auto-discovery.

`exclude` replaces the built-in default exclude list entirely. `extend-exclude` adds patterns to the defaults (or to `exclude` if set). Default excludes: `.git`, `.hg`, `.svn`, `.bzr`, `.venv`, `venv`, `.tox`, `.nox`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `__pycache__`, `__pypackages__`, `_build`, `build`, `dist`, `node_modules`, `.eggs`. Patterns are matched against individual folder or file names using `fnmatch`, not full paths. For example, `"vendor"` excludes any folder named `vendor` anywhere in the tree, while `"docs/vendor"` would never match (use `"vendor"` instead). Glob wildcards work: `"test_*"` excludes any folder starting with `test_`.

`todo-patterns` replaces the default TODO marker patterns (`["todo", "fixme"]`). `extend-todo-patterns` adds to the effective list. Both can be combined. Setting `todo-patterns = []` disables TODO detection entirely.

## License

[MIT](LICENSE.md)
