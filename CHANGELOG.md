# Changelog

## 0.6.0 - 2026-04-26

### Added
- Section header detection: lines like `# === Title ===`, `# --- Title ---`, `# ### Title ###`, `# *** Title ***`, and `# ___ Title ___` are now preserved verbatim instead of being merged into surrounding prose. Requires the same delimiter character (`-`, `=`, `#`, `*`, `_`) on both sides with at least three of that character per side; asymmetric counts (e.g. `# === Title ====`) and zero-padding (e.g. `# ===Title===`) are accepted. Overflowing headers pass through unchanged, matching how dividers are handled.
- `u` (undo) action in interactive mode (`-i`) that pops the most recent decision from a session-wide log and re-prompts at that position. Undo works across files: when undo lands in a previously-written file, the on-disk content is reverted lazily — either when the user re-walks through that file or at session end via the q-flush, which reconciles every file on disk with the final decision log so undone writes never persist. Decisions made before the undo are silently replayed on re-entry, so the user is only re-prompted at and beyond the rewind cursor. The `[u]ndo` label is hidden at the very first prompt of a session when there is nothing to pop.

### Fixed
- Pressing the up arrow key in interactive mode no longer silently triggers "accept all remaining paragraphs". `_getch()` now consumes escape sequences (arrow keys, function keys, etc.) as a single logical event using a 50ms drain timeout that matches ncurses' `ESCDELAY` convention, so the trailing `A` of `\x1b[A` can no longer collide with the accept-all action. Bare ESC presses and other escape sequences (mouse, focus, window-resize) are likewise swallowed cleanly.
- Pasting text into an interactive prompt no longer leaks subsequent characters into following prompts. After each accepted keypress, `_getch()` now drains any remaining buffered input (`termios.tcflush(TCIFLUSH)` on Unix, `msvcrt.kbhit()` loop on Windows). The first character of a paste is still consumed as that prompt's answer, but the rest is discarded instead of bleeding into later block prompts.
- `prompt_user()` now validates input before echoing, so an unrecognized keypress no longer writes its raw bytes (ESC, backspace, control characters) to the terminal. Previously these could scramble terminal state, particularly when ESC put the terminal into "expecting an escape sequence" mode and consumed the next real keystroke.
- `--interactive` now exits cleanly with `octowrap: error: --interactive requires a TTY` when stdin is not a terminal, instead of crashing partway through with `termios.error` on the first prompt.
- Windows special-key prefixes (`\x00`/`\xe0` followed by a scancode) are now consumed as a single non-action keypress instead of being returned as a literal `\x00` or `\xe0` character.
- A `UnicodeDecodeError` from a malformed byte on stdin no longer crashes interactive mode; it is treated as a non-action keypress and the loop re-prompts.

## 0.5.1 - 2026-04-17

### Added
- JetBrains/PyCharm `# noinspection <InspectionName>` suppression comments are now recognized as tool directives and preserved in place on their own line instead of being merged into surrounding prose. Both single and comma-separated inspection names are supported.

### Changed
- Interactive mode (`-i`) now prompts at the paragraph level instead of the whole comment block. A block mixing prose, a TODO, and a tool directive now reviews as up to three separate diffs — one per changed paragraph — instead of one bundled diff that obscures what's changing. Unchanged paragraphs (preserved tool directives, dividers) pass through silently without prompting. Consecutive list items are grouped into a single prompt so multi-item lists review as one logical change. The `[X/Y]` progress indicator counts paragraphs instead of blocks. The `e` (exclude) and `f` (flag) actions apply to the selected paragraph, not the whole block.
- The `f` (flag) action now wraps both the FIXME marker and the original paragraph in `# octowrap: off` / `# octowrap: on` pragmas, so a rerun skips the flagged region entirely instead of re-prompting on the bare original.

### Fixed
- `#` characters inside a string literal that spans multiple lines (e.g. a `#` fragment in a long URL inside a multi-line string) are no longer misread as inline comments and extracted. octowrap now uses Python's `tokenize` module to identify authoritative comment-start positions; on syntactically invalid Python, it falls back to the existing single-line string-aware scanner.
- Pre-existing whitespace just inside brackets (`( x`, `x )`, `[ y`, `y ]`) is now stripped during comment rewrapping. This fixes a case where a prior wrap placed a bracket at the end (or start) of a line and `textwrap` then broke between the bracket and its contents on subsequent passes, orphaning an open paren at the end of a line.

## 0.5.0 - 2026-04-16

### Added
- Incremental adoption via `--diff-only`: only process comment blocks overlapping lines changed in git, so teams can adopt octowrap gradually without reformatting the entire codebase
- `--diff-base REF` flag to specify the git ref to diff against (default: `HEAD`); implies `--diff-only`
- `diff-only` config key (bool, default `false`) in `[tool.octowrap]`
- `diff-base` config key (str, default `"HEAD"`) in `[tool.octowrap]`
- GitHub Actions example for incremental CI checks using `--diff-only --diff-base origin/main --check`

## 0.4.0 - 2026-02-10

### Added
- List item wrapping: long list items (bullets, numbered, lettered) are now rewrapped with hanging indent aligned to the text after the marker. Continuation lines indented to the marker's text column are collected before wrapping. Nesting is handled naturally — each item wraps independently at its own indent level. Disable with `list-wrap = false` in config.
- `list-wrap` config key (bool, default `true`) in `[tool.octowrap]`
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
