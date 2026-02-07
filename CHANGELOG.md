# Changelog

## 0.2.0 - 2026-02-07

### Added
- `e` (exclude) action in interactive mode (`-i`) that wraps the current block with `# octowrap: off` / `# octowrap: on` pragmas so future runs skip it automatically

### Fixed
- `q` (quit) in interactive mode now stops all processing, including remaining files in a multi file run

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
