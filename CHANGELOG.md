# Changelog

## Unreleased

### Added
- Inline comment extraction: when a code line with an inline comment (`code  # comment`) exceeds the line length, the comment is extracted into a standalone block comment above the code line and wrapped normally. Tool directives (`# type: ignore`, `# noqa`, etc.) are always preserved in place. Disable with `--no-inline` or `inline = false` in config.
- `--no-inline` CLI flag to disable inline comment extraction
- `inline` config key (bool, default `true`) in `[tool.octowrap]`
- Interactive mode (`-i`) now shows a `[X/Y]` progress indicator in the diff header, where X is the current changed block and Y is the total across all files. A pre-scan counts changed blocks upfront so the total is known before prompting begins.

### Changed
- File processing errors now print to stderr (instead of stdout) and cause exit code 2, matching ruff's behavior
- Malformed `pyproject.toml` files now raise an error instead of being silently skipped during config discovery

### Fixed
- `[f]lag` action in interactive mode prompt was rendered without color because `magenta` was missing from the ANSI color dictionary; added it so the flag option is now correctly colorized
- `todo-patterns` containing trailing punctuation (e.g. `"TEST:"`) failed to match due to a `\b` word boundary being appended after non-word characters; the boundary is now only added when the pattern ends with a word character
- Rewrapping no longer introduces erroneous spaces after opening brackets (`(`, `[`) or before closing brackets (`)`, `]`) when a line break falls at a bracket boundary

## 0.3.1 - 2026-02-09

### Added
- An editor integration section to `README.md` that describes setting up octowrap as a PyCharm file watcher
- `--stdin-filename` flag for editor integrations: provides a filename for config discovery (finds the right `pyproject.toml` based on the file's location) and diff display labels when piping via stdin
- `f` (flag) action in interactive mode (`-i`) that inserts a `# FIXME: Manually fix the below comment` marker above the original block for later human attention, without modifying the block itself
- codespell for spell checking (pre-commit hook, CI lint step, `[tool.codespell]` config)
- docformatter for docstring formatting (pre-commit hook, CI lint step, `[tool.docformatter]` config)
- `.python-version` pins dev environment to Python 3.13 (docformatter's `untokenize` dependency doesn't build on 3.14)

### Fixed
- All file I/O now explicitly uses UTF-8 encoding, fixing silent corruption of non-ASCII comments on Windows (where the default encoding is cp1252)
- Reduced `is_likely_code()` false positives: tightened `def`, `for`, `except`, and method-call patterns, and added a `_looks_like_prose()` second-pass filter that rescues natural English comments starting with Python keywords followed by determiners (e.g. "if the server is down:", "return the result to the caller", "for example: this shows the pattern")
- Hyphenated words (e.g. `command-line-interface`) are no longer broken at hyphens during rewrapping (`break_on_hyphens=False`)
- Long words and URLs are no longer broken mid-word; they overflow the line length instead of being split (`break_long_words=False`)
- Previously broken hyphenated words (e.g. `re-` / `validate` on separate lines) are now healed back into `re-validate` on rewrap, fixing an idempotency bug where successive runs would corrupt hyphenated words by inserting a space (`re- validate`)

## 0.2.0 - 2026-02-07

### Changed
- NOTE, XXX, and HACK are no longer treated as special markers; they are now rewrapped as regular prose

### Added
- Dogfooding: octowrap now runs on its own codebase via a local pre-commit hook and a CI lint step (`octowrap --check .`)
- Interactive mode diffs now display the relative filepath alongside line numbers
- `e` (exclude) action in interactive mode (`-i`) that wraps the current block with `# octowrap: off` / `# octowrap: on` pragmas so future runs skip it automatically
- Atomic file writes (temp file + rename) to protect against interruptions and power loss
- TODO/FIXME markers are now intelligently rewrapped instead of preserved as is, with the marker on the first line and a one space continuation indent on subsequent lines
- Multi line TODO collection: continuation lines (starting with exactly one space) are gathered and rewrapped together
- Case insensitive TODO/FIXME detection by default (no colon required)
- New `pyproject.toml` config options: `todo-patterns`, `extend-todo-patterns`, `todo-case-sensitive`, `todo-multiline`
- `todo-patterns` replaces the default patterns (`["todo", "fixme"]`); `extend-todo-patterns` adds to them
- Setting `todo-patterns = []` disables TODO detection, causing those lines to be rewrapped as regular prose
- A new section to the README for setting up octowrap as a CI test using GitHub Actions

### Fixed
- `q` (quit) in interactive mode now stops all processing, including remaining files in a multi file run
- `--diff --check` in stdin mode now correctly exits 1 when changes are needed (previously always exited 0)

## 0.1.0 - 2026-02-05

### Added
- Comment rewrapping engine using `textwrap.fill()` with configurable line length (default 88)
- Intelligent preservation of commented-out code, section dividers, list items, special markers (TODO, FIXME, NOTE, XXX, HACK), and tool directives (type: ignore, noqa, fmt: off, pragma: no cover, etc.)
- `# octowrap: off` / `# octowrap: on` pragmas to skip specific sections
- Stdin/stdout support (`octowrap -` for use in pipelines)
- Interactive mode (`-i`) with per-block approval (accept, accept all, skip, quit)
- `--check` flag for CI (exits non-zero if changes would be made)
- `--diff` and `--dry-run` flags for previewing changes
- Colorized diff output with TTY auto-detection and `--color`/`--no-color` flags, respecting `NO_COLOR` env var
- `pyproject.toml` configuration via `[tool.octowrap]` with `exclude` and `extend-exclude` support
- `--config` flag to specify an alternate config file
- Recursive directory processing (on by default, disable with `--no-recursive`)
- Pre-commit hook support via `.pre-commit-hooks.yaml`
- Cross-platform interactive input support (Windows and Unix)
