"""Rewrap # comments to a specified line width.

This script identifies contiguous blocks of # comments at the same indentation level and
rewraps them using textwrap. It preserves:
- Commented out code (heuristic detection)
- Section dividers (lines of repeated characters like # ---- or # ====)
- Inline comments (# after code on the same line)
- Intentional short lines and blank comment lines
- Lists and bullet points
"""

import argparse
import difflib
import fnmatch
import os
import re
import stat
import sys
import tempfile
import textwrap
from pathlib import Path

from octowrap.config import ConfigError, load_config

# Platform specific imports for single keypress input (_getch). msvcrt is Windows only;
# termios/tty are Unix only. The type: ignore comments suppress errors from type
# checkers that cannot resolve modules only available on the other platform.
if sys.platform == "win32":  # pragma: no cover
    import msvcrt  # noqa: F401
else:  # pragma: no cover
    import termios  # noqa: F401
    import tty  # noqa: F401

DEFAULT_EXCLUDES: list[str] = [
    ".git",
    ".hg",
    ".svn",
    ".bzr",
    ".venv",
    "venv",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "__pycache__",
    "__pypackages__",
    "_build",
    "build",
    "dist",
    "node_modules",
    ".eggs",
]

DEFAULT_TODO_PATTERNS: list[str] = ["todo", "fixme"]
DEFAULT_TODO_CASE_SENSITIVE: bool = False
DEFAULT_TODO_MULTILINE: bool = True


def is_excluded(path: Path, exclude_patterns: list[str]) -> bool:
    """Check if any component of *path* matches an exclude pattern."""
    for part in path.parts:
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def is_likely_code(text: str) -> bool:
    """Heuristic: detect if a comment line is probably commented out code."""
    code_patterns = [
        r"^\s*[\w_]+\s*=",  # assignment
        r"^\s*def\s+\w+",  # function def
        r"^\s*class\s+\w+",  # class def
        r"^\s*import\s+",  # import
        r"^\s*from\s+\w+\s+import",  # from import
        r"^\s*if\s+.*:",  # if statement
        r"^\s*for\s+.*:",  # for loop
        r"^\s*while\s+.*:",  # while loop
        r"^\s*return\s+",  # return
        r"^\s*raise\s+",  # raise
        r"^\s*try\s*:",  # try
        r"^\s*except\s*",  # except
        r"^\s*with\s+.*:",  # with statement
        r"^\s*assert\s+",  # assert
        r"^\s*yield\s+",  # yield
        r"^\s*lambda\s+",  # lambda
        r"^\s*@\w+",  # decorator
        r"^\s*print\s*\(",  # print call
        r"^\s*self\.",  # self reference
        r"^\s*\w+\.\w+\s*\(",  # method call
        r"^\s*\w+\s*\([^)]*\)\s*$",  # function call
    ]
    return any(re.match(p, text) for p in code_patterns)


def is_divider(text: str) -> bool:
    """Check if a comment is a section divider like # ---- or # ====."""
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    # Check if it's mostly repeated characters
    char_counts = {}
    for c in stripped:
        char_counts[c] = char_counts.get(c, 0) + 1
    most_common_count = max(char_counts.values())
    return most_common_count >= len(stripped) * 0.7 and len(stripped) >= 4


def is_list_item(text: str) -> bool:
    """Check if a comment line is a list item or bullet point."""
    list_patterns = [
        r"^\s*[-*•]\s+",  # bullet points
        r"^\s*\d+[.)]\s+",  # numbered lists
        r"^\s*[a-zA-Z][.)]\s+",  # lettered lists
    ]
    return any(re.match(p, text) for p in list_patterns)


def is_tool_directive(text: str) -> bool:
    """Check if a comment line is a tool directive (type: ignore, noqa, fmt: off, etc.)."""
    directive_patterns = [
        r"type:\s*ignore",  # mypy/pyright inline suppression
        r"noqa(\s*:\s*\S+)?$",  # flake8/ruff lint suppression
        r"pragma:\s*no\s+(cover|branch)",  # coverage.py
        r"fmt:\s*(off|on|skip)",  # black/ruff formatter
        r"isort:\s*(skip|skip_file|split)",  # isort
        r"pylint:\s*(disable|enable)",  # pylint
        r"mypy:\s*\S",  # mypy config comments
        r"pyright:\s*\S",  # pyright config comments
        r"ruff:\s*noqa",  # ruff-specific suppression
        r"type:\s*\S+",  # PEP 484 type comments (e.g. type: int)
    ]
    stripped = text.strip()
    return any(re.match(p, stripped) for p in directive_patterns)


def is_todo_marker(
    text: str,
    patterns: list[str] | None = None,
    case_sensitive: bool = False,
) -> bool:
    """Check if *text* starts with a TODO/FIXME-style marker.

    Matches at the start of *text* (after optional whitespace) so that
    continuation lines with a leading space do **not** match.
    """
    if patterns is None:
        patterns = DEFAULT_TODO_PATTERNS
    if not patterns:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    # Sort longest-first to avoid prefix ambiguity
    for p in sorted(patterns, key=lambda s: len(s), reverse=True):
        if re.match(rf"{re.escape(p)}\b", text.lstrip(), flags):
            return True
    return False


def is_todo_continuation(text: str) -> bool:
    """Return ``True`` if *text* looks like a TODO continuation line.

    A continuation line starts with exactly one space and has
    non-whitespace content after it.
    """
    return text.startswith(" ") and not text.startswith("  ") and text.strip() != ""


def extract_todo_marker(
    text: str,
    patterns: list[str] | None = None,
    case_sensitive: bool = False,
) -> tuple[str, str]:
    """Extract the marker prefix and remaining content from a TODO line.

    Returns ``(marker_prefix, content)`` — e.g. ``("TODO: ", "fix the bug")``.
    If *text* does not match any pattern, returns ``("", text)``.
    """
    if patterns is None:
        patterns = DEFAULT_TODO_PATTERNS
    stripped = text.lstrip()
    leading = text[: len(text) - len(stripped)]
    flags = 0 if case_sensitive else re.IGNORECASE
    for p in sorted(patterns, key=lambda s: len(s), reverse=True):
        m = re.match(rf"({re.escape(p)}\b\s*:?\s*)(.*)", stripped, flags)
        if m:
            return (leading + m.group(1), m.group(2))
    return ("", text)


def should_preserve_line(text: str) -> bool:
    """Determine if a comment line should be preserved as is."""
    if not text.strip():
        return True  # blank comment line
    if is_likely_code(text):
        return True
    if is_divider(text):
        return True
    return False


def parse_pragma(line: str) -> str | None:
    """Check if a raw source line is an octowrap pragma.

    Returns "off", "on", or None.
    """
    match = re.match(r"^\s*#\s*octowrap:\s*(off|on)\s*$", line, re.IGNORECASE)
    return match.group(1).lower() if match else None


def parse_comment_blocks(lines: list[str]) -> list[dict]:
    """Parse file lines into code sections and comment blocks.

    Returns a list of dicts with:
    - type: 'code' or 'comment_block'
    - lines: the original lines
    - indent: indentation level (for comment blocks)
    - start_idx: starting line index
    """
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a pure comment line (not inline)
        match = re.match(r"^(\s*)#(.*)$", line)

        if match and not line.rstrip().startswith("#!"):  # skip shebang
            # Start of a potential comment block
            indent = match.group(1)
            block_lines = []
            start_idx = i

            while i < len(lines):
                line = lines[i]
                match = re.match(r"^(\s*)#(.*)$", line)
                if match and match.group(1) == indent:
                    block_lines.append(line)
                    i += 1
                else:
                    break

            result.append(
                {
                    "type": "comment_block",
                    "lines": block_lines,
                    "indent": indent,
                    "start_idx": start_idx,
                }
            )
        else:
            # Code line or other
            if result and result[-1]["type"] == "code":
                result[-1]["lines"].append(line)
            else:
                result.append({"type": "code", "lines": [line], "start_idx": i})
            i += 1

    return result


def rewrap_comment_block(
    block: dict,
    max_line_length: int = 88,
    comment_prefix: str = "# ",
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
) -> list[str]:
    """Rewrap a comment block to the specified line length."""
    indent = block["indent"]
    lines = block["lines"]

    if todo_patterns is None:
        todo_patterns = DEFAULT_TODO_PATTERNS

    # Calculate available width for text
    prefix = indent + comment_prefix
    text_width = max_line_length - len(prefix)

    if text_width < 20:
        # Too narrow to rewrap meaningfully
        return lines

    # Extract comment content
    contents = []
    for line in lines:
        match = re.match(r"^\s*#\s?(.*)$", line)
        if match:
            contents.append(match.group(1))
        else:
            # Defensive: parse_comment_blocks only yields # lines, so the regex above
            # will always match.
            contents.append("")  # pragma: no cover

    # Group into paragraphs (separated by blank comment lines or preserved lines)
    paragraphs: list[tuple[str, list[str]]] = []
    current_para: list[str] = []
    i = 0

    while i < len(contents):
        content = contents[i]
        if not content.strip():
            # Blank line: end current paragraph
            if current_para:
                paragraphs.append(("wrap", current_para))
                current_para = []
            paragraphs.append(("blank", [""]))
        elif (
            should_preserve_line(content)
            or is_list_item(content)
            or is_tool_directive(content)
        ):
            # Preserve this line as is
            if current_para:
                paragraphs.append(("wrap", current_para))
                current_para = []
            paragraphs.append(("preserve", [content]))
        elif is_todo_marker(content, todo_patterns, todo_case_sensitive):
            # Flush current paragraph
            if current_para:
                paragraphs.append(("wrap", current_para))
                current_para = []
            # Collect TODO + continuation lines
            todo_lines = [content]
            if todo_multiline:
                while i + 1 < len(contents) and is_todo_continuation(contents[i + 1]):
                    i += 1
                    todo_lines.append(contents[i])
            paragraphs.append(("todo", todo_lines))
        else:
            current_para.append(content)
        i += 1

    if current_para:
        paragraphs.append(("wrap", current_para))

    # Rewrap and reconstruct
    result = []
    for para_type, para_contents in paragraphs:
        if para_type == "blank":
            result.append(indent + "#")
        elif para_type == "preserve":
            for content in para_contents:
                if content:
                    result.append(prefix + content)
                else:
                    # Defensive: preserved lines always have non empty content since
                    # blank lines are handled above.
                    result.append(indent + "#")  # pragma: no cover
        elif para_type == "todo":
            marker_prefix, first_content = extract_todo_marker(
                para_contents[0], todo_patterns, todo_case_sensitive
            )
            # Join first-line content + stripped continuation lines
            parts = [first_content] + [c.strip() for c in para_contents[1:]]
            full_text = " ".join(parts).strip()

            # If there is no content after the TODO marker (e.g. "# TODO:"), preserve
            # the original lines instead of emitting a blank line.
            if not full_text:
                for content in para_contents:
                    result.append(prefix + content)
            else:
                initial = prefix + marker_prefix
                subsequent = prefix + " "
                first_width = max_line_length - len(initial)
                cont_width = max_line_length - len(subsequent)

                if first_width < 10 or cont_width < 10:
                    # Too narrow — preserve as-is
                    for content in para_contents:
                        result.append(prefix + content)
                else:
                    wrapped = textwrap.fill(
                        full_text,
                        width=max_line_length,
                        initial_indent=initial,
                        subsequent_indent=subsequent,
                    )
                    result.extend(wrapped.split("\n"))
        else:  # wrap
            text = " ".join(para_contents)
            wrapped = textwrap.fill(text, width=text_width)
            for wrapped_line in wrapped.split("\n"):
                result.append(prefix + wrapped_line)

    return result


_USE_COLOR: bool = True


def colorize(text: str, color: str) -> str:
    """Add ANSI color codes to text."""
    if not _USE_COLOR:
        return text
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "cyan": "\033[96m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def show_block_diff(
    original_lines: list[str],
    new_lines: list[str],
    start_line: int,
    filepath: str = "",
) -> bool:
    """Display a diff for a single comment block.

    Returns True if there are changes, False otherwise.
    """
    if original_lines == new_lines:
        return False

    end = start_line + len(original_lines)
    if filepath:
        header = colorize(f"{filepath} Lines {start_line + 1}-{end}:", "bold")
    else:
        header = colorize(f"Lines {start_line + 1}-{end}:", "bold")
    print(f"\n{header}")
    print(colorize("─" * 60, "cyan"))

    for line in original_lines:
        print(colorize(f"- {line}", "red"))
    for line in new_lines:
        print(colorize(f"+ {line}", "green"))

    print(colorize("─" * 60, "cyan"))
    return True


def _getch() -> str:
    """Read a single character without waiting for Enter.

    Uses platform specific APIs (msvcrt on Windows, termios/tty on Unix),
    imported conditionally at module level.
    """
    if sys.platform == "win32":
        return msvcrt.getwch()

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)  # type: ignore[possibly-unbound]
    try:
        tty.setcbreak(fd)  # type: ignore[possibly-unbound]
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)  # type: ignore[possibly-unbound]


def prompt_user() -> str:
    """Prompt user for action on a block.

    Returns: 'a' (accept), 'A' (accept all), 'e' (exclude), 's' (skip), or 'q' (quit)
    """
    prompt = (
        f"[{colorize('a', 'green')}]ccept / "
        f"accept [{colorize('A', 'green')}]ll / "
        f"[{colorize('e', 'cyan')}]xclude / "
        f"[{colorize('s', 'yellow')}]kip / "
        f"[{colorize('q', 'red')}]uit? "
    )
    while True:
        try:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            ch = _getch()
            sys.stdout.write(ch + "\n")
            sys.stdout.flush()
            if ch == "A":
                return "A"
            ch = ch.lower()
            if ch in ("a", "e", "s", "q"):
                return ch
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"


def process_content(
    content: str,
    max_line_length: int = 88,
    interactive: bool = False,
    _state: dict | None = None,
    filepath: str = "",
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
) -> tuple[bool, str]:
    """Rewrap comment blocks in a string of Python source.

    Returns (changed, new_content).  When *_state* is a dict and the user
    presses quit in interactive mode, ``_state["quit"]`` is set to ``True``.
    """
    lines = content.splitlines(keepends=True)

    # Normalize line endings for processing
    lines_stripped = [line.rstrip("\n\r") for line in lines]

    blocks = parse_comment_blocks(lines_stripped)

    new_lines = []
    user_quit = False
    accept_all = False
    disabled = False

    for block in blocks:
        if block["type"] == "code":
            new_lines.extend(block["lines"])
            continue

        # Check if this block contains any pragma directives
        has_pragma = any(parse_pragma(bline) is not None for bline in block["lines"])

        if has_pragma:
            # Split the block into sub blocks at pragma boundaries, processing each
            # segment according to the current disabled state.
            segment_lines: list[str] = []
            segment_start = block["start_idx"]

            for bline in block["lines"]:
                p = parse_pragma(bline)
                if p is not None:
                    # Process accumulated segment before this pragma.
                    if segment_lines:
                        sub = {
                            "type": "comment_block",
                            "lines": segment_lines,
                            "indent": block["indent"],
                            "start_idx": segment_start,
                        }
                        if disabled:
                            new_lines.extend(segment_lines)
                        else:
                            new_lines.extend(
                                rewrap_comment_block(
                                    sub,
                                    max_line_length,
                                    todo_patterns=todo_patterns,
                                    todo_case_sensitive=todo_case_sensitive,
                                    todo_multiline=todo_multiline,
                                )
                            )
                        segment_start += len(segment_lines)
                        segment_lines = []
                    # Preserve the pragma line itself and update state.
                    new_lines.append(bline)
                    disabled = p == "off"
                    segment_start += 1
                else:
                    segment_lines.append(bline)

            # Process any remaining segment after the last pragma.
            if segment_lines:
                sub = {
                    "type": "comment_block",
                    "lines": segment_lines,
                    "indent": block["indent"],
                    "start_idx": segment_start,
                }
                if disabled:
                    new_lines.extend(segment_lines)
                else:
                    new_lines.extend(
                        rewrap_comment_block(
                            sub,
                            max_line_length,
                            todo_patterns=todo_patterns,
                            todo_case_sensitive=todo_case_sensitive,
                            todo_multiline=todo_multiline,
                        )
                    )
            continue

        if disabled:
            # Rewrapping is suppressed, so preserve as is.
            new_lines.extend(block["lines"])
            continue

        # Use the normal rewrap logic.
        rewrapped = rewrap_comment_block(
            block,
            max_line_length,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
        )

        if not interactive:
            new_lines.extend(rewrapped)
        elif accept_all:
            new_lines.extend(rewrapped)
        else:
            has_changes = not user_quit and show_block_diff(
                block["lines"], rewrapped, block["start_idx"], filepath=filepath
            )

            if has_changes:
                action = prompt_user()

                if action == "A":
                    accept_all = True
                    new_lines.extend(rewrapped)
                elif action == "a":
                    new_lines.extend(rewrapped)
                elif action == "e":
                    indent = block["indent"]
                    new_lines.append(f"{indent}# octowrap: off")
                    new_lines.extend(block["lines"])
                    new_lines.append(f"{indent}# octowrap: on")
                elif action == "q":
                    user_quit = True
                    if _state is not None:
                        _state["quit"] = True
                    new_lines.extend(block["lines"])
                else:  # skip
                    new_lines.extend(block["lines"])
            else:
                new_lines.extend(block["lines"])

    # Restore the original line ending style.
    if lines and lines[0].endswith("\r\n"):
        ending = "\r\n"
    elif lines and lines[0].endswith("\r"):
        ending = "\r"
    else:
        ending = "\n"

    new_content = ending.join(new_lines)
    if content.endswith(("\n", "\r")):
        new_content += ending

    changed = new_content != content

    return changed, new_content


def _relative_path(filepath: Path) -> Path:
    """Return *filepath* relative to CWD when possible, otherwise unchanged."""
    try:
        return filepath.resolve().relative_to(Path.cwd())
    except ValueError:
        return filepath


def process_file(
    filepath: Path,
    max_line_length: int = 88,
    dry_run: bool = False,
    interactive: bool = False,
    _state: dict | None = None,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
) -> tuple[bool, str]:
    """Process a single file, rewrapping comment blocks.

    Returns (changed, new_content).
    """
    with open(filepath, newline="") as f:
        content = f.read()

    changed, new_content = process_content(
        content,
        max_line_length,
        interactive=interactive and not dry_run,
        _state=_state,
        filepath=str(_relative_path(filepath)),
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
    )

    if changed and not dry_run:
        original_mode = stat.S_IMODE(os.stat(filepath).st_mode)
        tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
        try:
            with open(tmp_fd, "w", newline="") as f:
                f.write(new_content)
            os.chmod(tmp_path, original_mode)
            os.replace(tmp_path, filepath)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    return changed, new_content


def main():
    parser = argparse.ArgumentParser(
        description="Rewrap # block comments to a specified line width."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Files or directories to process (use '-' to read from stdin)",
    )
    parser.add_argument(
        "-l",
        "--line-length",
        type=int,
        default=None,
        help="Maximum line length (default: 88)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--diff", action="store_true", help="Show diff of changes (implies --dry-run)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit with code 1 if files would be changed (implies --dry-run)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        default=None,
        help="Only process top level .py files in directories",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Review each change interactively before applying",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to pyproject.toml config file (default: auto-discover)",
    )

    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument(
        "--color",
        dest="color",
        action="store_true",
        default=None,
        help="Force colored output",
    )
    color_group.add_argument(
        "--no-color",
        dest="color",
        action="store_false",
        help="Disable colored output",
    )

    args = parser.parse_args()

    # Resolve color setting: --color -> on, --no-color -> off, neither -> auto detect.
    global _USE_COLOR
    if args.color is None:
        _USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    else:
        _USE_COLOR = args.color

    # Load config from pyproject.toml and merge with CLI args. Precedence: hardcoded
    # defaults < config file < CLI args.
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"octowrap: config error: {exc}", file=sys.stderr)
        raise SystemExit(1)

    if args.line_length is None:
        args.line_length = config.get("line-length", 88)

    # Recursive: default True, config can override, --no-recursive wins
    if args.no_recursive is None:
        args.recursive = config.get("recursive", True)
    else:
        args.recursive = False

    # Build effective exclude list
    exclude_patterns = list(DEFAULT_EXCLUDES)
    if "exclude" in config:
        exclude_patterns = config["exclude"]
    if "extend-exclude" in config:
        exclude_patterns = exclude_patterns + config["extend-exclude"]

    # Build effective TODO settings
    todo_patterns: list[str] = list(DEFAULT_TODO_PATTERNS)
    if "todo-patterns" in config:
        todo_patterns = config["todo-patterns"]
        if not todo_patterns:
            # Explicit empty list disables TODO detection entirely; ignore extend-todo-
            # patterns.
            pass
        elif "extend-todo-patterns" in config:
            todo_patterns = todo_patterns + config["extend-todo-patterns"]
    elif "extend-todo-patterns" in config:
        todo_patterns = todo_patterns + config["extend-todo-patterns"]
    todo_case_sensitive = config.get("todo-case-sensitive", DEFAULT_TODO_CASE_SENSITIVE)
    todo_multiline = config.get("todo-multiline", DEFAULT_TODO_MULTILINE)

    if args.diff or args.check:
        args.dry_run = True

    # Handle stdin mode when '-' is passed as a path
    stdin_mode = any(str(p) == "-" for p in args.paths)
    if stdin_mode:
        if len(args.paths) > 1:
            print(
                "octowrap: error: '-' cannot be mixed with other paths",
                file=sys.stderr,
            )
            raise SystemExit(1)
        if args.interactive:
            print(
                "octowrap: error: --interactive cannot be used with stdin",
                file=sys.stderr,
            )
            raise SystemExit(1)

        content = sys.stdin.read()
        changed, new_content = process_content(
            content,
            args.line_length,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
        )

        if args.diff and changed:
            diff = difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile="<stdin>",
                tofile="<stdin>",
            )
            sys.stdout.write("".join(diff))
        elif not (args.diff or args.check):
            sys.stdout.write(new_content)

        if args.check:
            raise SystemExit(1 if changed else 0)

        raise SystemExit(0)

    files_to_process = []
    for path in args.paths:
        if path.is_file():
            files_to_process.append(path)
        elif path.is_dir():
            if args.recursive:
                files_to_process.extend(
                    p
                    for p in path.rglob("*.py")
                    if not is_excluded(p, exclude_patterns)
                )
            else:
                files_to_process.extend(
                    p for p in path.glob("*.py") if not is_excluded(p, exclude_patterns)
                )
        else:
            print(f"Warning: {path} not found, skipping")

    changed_count = 0
    interactive_state: dict = {}
    for filepath in files_to_process:
        try:
            original: str | None = filepath.read_text() if args.diff else None
            changed, new_content = process_file(
                filepath,
                args.line_length,
                dry_run=args.dry_run,
                interactive=args.interactive,
                _state=interactive_state,
                todo_patterns=todo_patterns,
                todo_case_sensitive=todo_case_sensitive,
                todo_multiline=todo_multiline,
            )

            if changed:
                changed_count += 1
                if args.diff:
                    assert type(original) is str

                    diff = difflib.unified_diff(
                        original.splitlines(keepends=True),
                        new_content.splitlines(keepends=True),
                        fromfile=str(filepath),
                        tofile=str(filepath),
                    )
                    print("".join(diff))
                elif args.dry_run:
                    print(f"Would reformat: {filepath}")
                else:
                    print(f"Reformatted: {filepath}")
        except Exception as e:
            print(f"Error processing {filepath}: {e}")

        if interactive_state.get("quit"):
            break

    action = "would be reformatted" if args.dry_run else "reformatted"
    print(f"\n{changed_count} file(s) {action}.")

    if args.check and changed_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
