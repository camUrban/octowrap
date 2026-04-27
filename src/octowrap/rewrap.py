"""Rewrap # comments to a specified line width.

This script identifies contiguous blocks of # comments at the same indentation level and
rewraps them using textwrap. It preserves:
- Commented out code (heuristic detection)
- Section dividers (lines of repeated characters like # ---- or # ====)
- Section headers (lines like # === Title === with matching delimiters on both sides)
- Short inline comments (# after code on the same line, within line length)
- Intentional short lines and blank comment lines
- Lists and bullet points (rewrapped with hanging indent when list-wrap is enabled)
"""

import argparse
import difflib
import fnmatch
import io
import os
import re
import shutil
import stat
import sys
import tempfile
import textwrap
import tokenize
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from octowrap.config import ConfigError, find_config_file, load_config
from octowrap.diff import NotAGitRepoError, get_changed_lines, get_repo_root

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
DEFAULT_LIST_WRAP: bool = True


@dataclass
class Decision:
    """One recorded interactive decision in a session-wide log.

    The cursor identifies a prompt position deterministically against the
    *original* file content, so it survives `e`/`f` mutations to the in-memory
    buffer during replay. Paragraph cursors are
    ``(block_start_idx, unit_raw_start)``; inline-extraction cursors are
    ``(block_start_idx, "inline", line_idx)``.
    """

    filepath: str
    cursor: tuple
    action: str


def is_excluded(path: Path, exclude_patterns: list[str]) -> bool:
    """Check if any component of *path* matches an exclude pattern."""
    for part in path.parts:
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False


def _looks_like_prose(text: str) -> bool:
    """Return True if *text* looks like natural-language prose.

    Called as a second pass after a code-pattern matched, to rescue false positives such
    as "if the server is down:" or "return the result".
    """
    lower = text.strip().lower()
    determiners = r"(?:the|this|that|these|those)"
    keywords = r"(?:if|while|with|return|raise|import|assert|yield)"
    # keyword + determiner + word  (e.g. "if the server …")
    if re.match(rf"{keywords}\s+{determiners}\s+[a-z]", lower):
        return True
    # "return to …"  (e.g. "return to the caller")
    if re.match(r"return\s+to\s+", lower):
        return True
    return False


def is_likely_code(text: str) -> bool:
    """Heuristic: detect if a comment line is probably commented out code."""
    code_patterns = [
        r"^\s*[\w_]+\s*=",  # assignment
        r"^\s*def\s+\w+\s*\(",  # function def
        r"^\s*class\s+\w+",  # class def
        r"^\s*import\s+",  # import
        r"^\s*from\s+\w+\s+import",  # from import
        r"^\s*if\s+.*:",  # if statement
        r"^\s*for\s+\w+(?:\s*,\s*\w+)*\s+in\s+",  # for loop
        r"^\s*while\s+.*:",  # while loop
        r"^\s*return\s+",  # return
        r"^\s*raise\s+",  # raise
        r"^\s*try\s*:",  # try
        r"^\s*except\s*($|[:(]|[A-Z])",  # except
        r"^\s*with\s+.*:",  # with statement
        r"^\s*assert\s+",  # assert
        r"^\s*yield\s+",  # yield
        r"^\s*lambda\s+",  # lambda
        r"^\s*@\w+",  # decorator
        r"^\s*print\s*\(",  # print call
        r"^\s*self\.",  # self reference
        r"^\s*\w+\.\w+\(",  # method call
        r"^\s*\w+\s*\([^)]*\)\s*$",  # function call
    ]
    if not any(re.match(p, text) for p in code_patterns):
        return False
    if _looks_like_prose(text):
        return False
    return True


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


_SECTION_HEADER_RE = re.compile(r"^([-=#*_])\1{2,}\s*(.+?)\s*\1{3,}$")


def is_section_header(text: str) -> bool:
    """Check if a comment is a section header like # === Title ===.

    Same delimiter character (one of ``- = # * _``) on both sides, at least
    three of that character per side. Asymmetric counts are allowed and
    padding around the title is optional. Title must contain a non-delimiter
    glyph; otherwise the line is just a fancy divider already covered by
    :func:`is_divider`.
    """
    match = _SECTION_HEADER_RE.match(text.strip())
    if not match:
        return False
    delim = match.group(1)
    title = match.group(2).strip()
    return bool(title.strip(delim))


def is_list_item(text: str) -> bool:
    """Check if a comment line is a list item or bullet point."""
    list_patterns = [
        r"^\s*[-*•]\s+",  # bullet points
        r"^\s*\d+[.)]\s+",  # numbered lists
        r"^\s*[a-zA-Z][.)]\s+",  # lettered lists
    ]
    return any(re.match(p, text) for p in list_patterns)


def is_tool_directive(text: str) -> bool:
    """Check if a comment line is a tool directive (type: ignore, noqa, fmt: off,
    etc.)."""
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
        r"noinspection\s+\S",  # JetBrains/PyCharm inspection suppression
        r"type:\s*\S+",  # PEP 484 type comments (e.g. type: int)
    ]
    stripped = text.strip()
    return any(re.match(p, stripped) for p in directive_patterns)


def find_inline_comment(line: str) -> int | None:
    """Return the index of the ``#`` that starts an inline comment, or ``None``.

    The line is scanned character by character while tracking whether the current
    position is inside a string literal (single-quoted, double-quoted, or
    triple-quoted) and handling backslash escapes so that any ``#`` characters
    that occur within string literals are ignored.

    A ``#`` is treated as starting an *inline* comment only if there is some
    non-whitespace text before it on the same line. If the ``#`` is preceded
    only by whitespace, it is considered a full-line comment and this function
    returns ``None``. ``None`` is also returned when there is no ``#`` outside
    of string literals.

    Note:
        This function does **not** track multi-line string state across lines; it
        only analyzes the single line passed in, matching the limitation of the
        existing block parser.
    """
    in_string: str | None = None  # None, or the quote character(s) (' / " / ''' / """)
    i = 0
    length = len(line)

    while i < length:
        ch = line[i]

        if in_string is not None:
            # Inside a string literal — look for the closing delimiter or escape.
            if ch == "\\" and i + 1 < length:
                i += 2  # skip escaped character
                continue
            if line[i:].startswith(in_string):
                i += len(in_string)
                in_string = None
                continue
            i += 1
            continue

        # Outside any string literal.
        if ch in ("'", '"'):
            # Check for triple-quote first.
            triple = ch * 3
            if line[i:].startswith(triple):
                in_string = triple
                i += 3
            else:
                in_string = ch
                i += 1
            continue

        if ch == "#":
            # Only treat as inline if there is non-whitespace code before it.
            prefix = line[:i]
            if prefix.strip():
                return i
            return None  # full-line comment

        i += 1

    return None


def extract_inline_comment(line: str) -> tuple[str, str] | None:
    """Split *line* into ``(code_part, comment_text)`` if it has an inline comment.

    Returns ``None`` when *line* has no inline comment.  The *code_part* has trailing
    whitespace stripped.  The *comment_text* is everything after the ``# `` prefix
    (leading hash-and-space removed).
    """
    idx = find_inline_comment(line)
    if idx is None:
        return None
    code_part = line[:idx].rstrip()
    raw_comment = line[idx + 1 :]  # everything after the '#'
    # Strip one optional leading space (standard "# comment" style).
    if raw_comment.startswith(" "):
        comment_text = raw_comment[1:]
    else:
        comment_text = raw_comment
    return code_part, comment_text


def is_todo_marker(
    text: str,
    patterns: list[str] | None = None,
    case_sensitive: bool = False,
) -> bool:
    """Check if *text* starts with a TODO/FIXME-style marker.

    Matches at the start of *text* (after optional whitespace) so that continuation
    lines with a leading space do **not** match.
    """
    if patterns is None:
        patterns = DEFAULT_TODO_PATTERNS
    if not patterns:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    # Sort longest-first to avoid prefix ambiguity
    for p in sorted(patterns, key=lambda s: len(s), reverse=True):
        boundary = r"\b" if re.match(r"\w", p[-1:]) else ""
        if re.match(rf"{re.escape(p)}{boundary}", text.lstrip(), flags):
            return True
    return False


def is_todo_continuation(text: str) -> bool:
    """Return ``True`` if *text* looks like a TODO continuation line.

    A continuation line starts with exactly one space and has non-whitespace content
    after it.
    """
    return text.startswith(" ") and not text.startswith("  ") and text.strip() != ""


def extract_todo_marker(
    text: str,
    patterns: list[str] | None = None,
    case_sensitive: bool = False,
) -> tuple[str, str]:
    # noinspection GrazieInspection
    """Extract the marker prefix and remaining content from a TODO line.

    Returns ``(marker_prefix, content)`` — e.g. ``("TODO: ", "fix the bug")``. If *text*
    does not match any pattern, returns ``("", text)``.
    """
    if patterns is None:
        patterns = DEFAULT_TODO_PATTERNS
    stripped = text.lstrip()
    leading = text[: len(text) - len(stripped)]
    flags = 0 if case_sensitive else re.IGNORECASE
    for p in sorted(patterns, key=lambda s: len(s), reverse=True):
        boundary = r"\b" if re.match(r"\w", p[-1:]) else ""
        m = re.match(rf"({re.escape(p)}{boundary}\s*:?\s*)(.*)", stripped, flags)
        if m:
            return leading + m.group(1), m.group(2)
    return "", text


def extract_list_marker(text: str) -> tuple[str, str]:
    """Extract list marker prefix and remaining content.

    Returns ``(marker_prefix, content)`` — e.g. ``("- ", "fix the bug")`` or
    ``("  1. ", "first item")``.  The *marker_prefix* includes any leading whitespace
    (nesting indent).  Returns ``("", text)`` on no match.
    """
    list_patterns = [
        r"^(\s*[-*•]\s+)(.*)",  # bullet points
        r"^(\s*\d+[.)]\s+)(.*)",  # numbered lists
        r"^(\s*[a-zA-Z][.)]\s+)(.*)",  # lettered lists
    ]
    for p in list_patterns:
        m = re.match(p, text)
        if m:
            return m.group(1), m.group(2)
    return "", text


def _join_comment_lines(lines: list[str]) -> str:
    # noinspection GrazieInspection
    """Join comment content lines, healing line-break artifacts.

    When a line ends with ``<letter>-`` and the next line starts with a letter, they are
    assumed to be fragments of a single hyphenated word and are joined without an
    intervening space.  When a line ends with an opening bracket (``(`` or ``[``) or the
    next line starts with a closing bracket (``)`` or ``]``), the lines are joined without
    a space to avoid introducing erroneous whitespace inside parenthesised text.  All
    other consecutive lines are joined with a single space, matching the behavior of
    ``" ".join()``.

    After joining, any remaining whitespace immediately inside brackets (``( x``, ``x )``,
    ``[ y``, ``y ]``) is stripped.  Such whitespace is typically an artifact of a prior
    wrap that placed the bracket at the end (or start) of a line; removing it prevents
    ``textwrap`` from breaking between the bracket and its contents on the next pass.
    """
    if not lines:
        return ""
    result = lines[0]
    for line in lines[1:]:
        if re.search(r"[a-zA-Z]-$", result) and line and line[0].isalpha():
            result += line
        elif result and result[-1] in ("(", "["):
            result += line
        elif line and line[0] in (")", "]"):
            result += line
        else:
            result += " " + line
    result = re.sub(r"([(\[])\s+", r"\1", result)
    result = re.sub(r"\s+([)\]])", r"\1", result)
    return result


def should_preserve_line(text: str) -> bool:
    """Determine if a comment line should be preserved as is."""
    if not text.strip():
        return True  # blank comment line
    if is_likely_code(text):
        return True
    if is_divider(text):
        return True
    if is_section_header(text):
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


def _split_paragraphs(
    contents: list[str],
    todo_patterns: list[str],
    todo_case_sensitive: bool,
    todo_multiline: bool,
    list_wrap: bool,
) -> list[dict]:
    """Split extracted comment *contents* into paragraph dicts.

    Each returned dict has ``type`` (``"wrap"``/``"blank"``/``"preserve"``/``"todo"``/
    ``"list"``), ``contents`` (the content lines feeding that paragraph), and
    ``raw_start``/``raw_end`` (indices into *contents*, usable as indices into the
    parent block's raw ``# ...`` lines since the two lists are 1:1).
    """
    paragraphs: list[dict] = []
    current_para: list[str] = []
    current_para_start: int | None = None
    i = 0

    def _flush_wrap(end: int) -> None:
        nonlocal current_para, current_para_start
        if current_para:
            assert current_para_start is not None
            paragraphs.append(
                {
                    "type": "wrap",
                    "contents": current_para,
                    "raw_start": current_para_start,
                    "raw_end": end,
                }
            )
            current_para = []
            current_para_start = None

    while i < len(contents):
        content = contents[i]
        if not content.strip():
            _flush_wrap(i)
            paragraphs.append(
                {
                    "type": "blank",
                    "contents": [""],
                    "raw_start": i,
                    "raw_end": i + 1,
                }
            )
        elif is_list_item(content) and list_wrap:
            _flush_wrap(i)
            marker_prefix, _ = extract_list_marker(content)
            cont_indent_len = len(marker_prefix)
            list_lines = [content]
            list_start = i
            while i + 1 < len(contents):
                next_content = contents[i + 1]
                if not next_content.strip():
                    break
                if is_list_item(next_content):
                    break  # sibling or nested item — its own paragraph
                if (
                    should_preserve_line(next_content)
                    or is_tool_directive(next_content)
                    or is_todo_marker(next_content, todo_patterns, todo_case_sensitive)
                ):
                    break
                actual_indent = len(next_content) - len(next_content.lstrip())
                if actual_indent >= cont_indent_len:
                    i += 1
                    list_lines.append(contents[i])
                else:
                    break
            paragraphs.append(
                {
                    "type": "list",
                    "contents": list_lines,
                    "raw_start": list_start,
                    "raw_end": i + 1,
                }
            )
        elif (
            should_preserve_line(content)
            or is_list_item(content)
            or is_tool_directive(content)
        ):
            _flush_wrap(i)
            paragraphs.append(
                {
                    "type": "preserve",
                    "contents": [content],
                    "raw_start": i,
                    "raw_end": i + 1,
                }
            )
        elif is_todo_marker(content, todo_patterns, todo_case_sensitive):
            _flush_wrap(i)
            todo_lines = [content]
            todo_start = i
            if todo_multiline:
                while i + 1 < len(contents) and is_todo_continuation(contents[i + 1]):
                    i += 1
                    todo_lines.append(contents[i])
            paragraphs.append(
                {
                    "type": "todo",
                    "contents": todo_lines,
                    "raw_start": todo_start,
                    "raw_end": i + 1,
                }
            )
        else:
            if current_para_start is None:
                current_para_start = i
            current_para.append(content)
        i += 1

    _flush_wrap(len(contents))
    return paragraphs


def _render_paragraph(
    para: dict,
    indent: str,
    prefix: str,
    max_line_length: int,
    text_width: int,
    todo_patterns: list[str],
    todo_case_sensitive: bool,
) -> list[str]:
    """Render a single paragraph dict to its rewrapped ``# ...`` output lines."""
    para_type = para["type"]
    para_contents = para["contents"]

    if para_type == "blank":
        return [indent + "#"]
    if para_type == "preserve":
        out: list[str] = []
        for content in para_contents:
            if content:
                out.append(prefix + content)
            else:
                # Defensive: preserved lines always have non-empty content since blank
                # lines are handled separately.
                out.append(indent + "#")  # pragma: no cover
        return out
    if para_type == "todo":
        marker_prefix, first_content = extract_todo_marker(
            para_contents[0], todo_patterns, todo_case_sensitive
        )
        parts = [first_content] + [c.strip() for c in para_contents[1:]]
        full_text = _join_comment_lines(parts).strip()
        if not full_text:
            return [prefix + c for c in para_contents]
        initial = prefix + marker_prefix
        subsequent = prefix + " "
        first_width = max_line_length - len(initial)
        cont_width = max_line_length - len(subsequent)
        if first_width < 10 or cont_width < 10:
            return [prefix + c for c in para_contents]
        wrapped = textwrap.fill(
            full_text,
            width=max_line_length,
            initial_indent=initial,
            subsequent_indent=subsequent,
            break_on_hyphens=False,
            break_long_words=False,
        )
        return wrapped.split("\n")
    if para_type == "list":
        marker_prefix, first_content = extract_list_marker(para_contents[0])
        parts = [first_content] + [c.strip() for c in para_contents[1:]]
        full_text = _join_comment_lines(parts).strip()
        if not full_text:
            return [prefix + c for c in para_contents]
        initial = prefix + marker_prefix
        subsequent = prefix + " " * len(marker_prefix)
        first_width = max_line_length - len(initial)
        cont_width = max_line_length - len(subsequent)
        if first_width < 10 or cont_width < 10:
            return [prefix + c for c in para_contents]
        wrapped = textwrap.fill(
            full_text,
            width=max_line_length,
            initial_indent=initial,
            subsequent_indent=subsequent,
            break_on_hyphens=False,
            break_long_words=False,
        )
        return wrapped.split("\n")
    # wrap
    text = _join_comment_lines(para_contents)
    wrapped = textwrap.fill(
        text, width=text_width, break_on_hyphens=False, break_long_words=False
    )
    return [prefix + line for line in wrapped.split("\n")]


def _block_prompt_units(
    block: dict,
    max_line_length: int = 88,
    comment_prefix: str = "# ",
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    list_wrap: bool = True,
) -> list[dict]:
    """Split *block* into per-prompt rewrap units.

    Each returned dict has ``raw_start`` (offset into ``block["lines"]``),
    ``original`` (the original raw lines for this unit), and ``rewrapped`` (the
    rewrapped output lines for this unit).  Consecutive list-item paragraphs are
    merged into a single unit so that a multi-item list is presented as one logical
    change rather than item by item.
    """
    indent = block["indent"]
    raw_lines = block["lines"]

    if todo_patterns is None:
        todo_patterns = DEFAULT_TODO_PATTERNS

    prefix = indent + comment_prefix
    text_width = max_line_length - len(prefix)

    if text_width < 20:
        return [
            {"raw_start": 0, "original": list(raw_lines), "rewrapped": list(raw_lines)}
        ]

    contents: list[str] = []
    for line in raw_lines:
        match = re.match(r"^\s*#\s?(.*)$", line)
        if match:
            contents.append(match.group(1))
        else:
            # Defensive: parse_comment_blocks only yields # lines, so the regex above
            # will always match.
            contents.append("")  # pragma: no cover

    paragraphs = _split_paragraphs(
        contents, todo_patterns, todo_case_sensitive, todo_multiline, list_wrap
    )

    # Group consecutive list paragraphs into a single prompt unit.
    groups: list[list[dict]] = []
    for para in paragraphs:
        if groups and para["type"] == "list" and groups[-1][-1]["type"] == "list":
            groups[-1].append(para)
        else:
            groups.append([para])

    units: list[dict] = []
    for group in groups:
        raw_start = group[0]["raw_start"]
        raw_end = group[-1]["raw_end"]
        original = list(raw_lines[raw_start:raw_end])
        rewrapped: list[str] = []
        for para in group:
            rewrapped.extend(
                _render_paragraph(
                    para,
                    indent,
                    prefix,
                    max_line_length,
                    text_width,
                    todo_patterns,
                    todo_case_sensitive,
                )
            )
        units.append(
            {"raw_start": raw_start, "original": original, "rewrapped": rewrapped}
        )

    return units


def rewrap_comment_block(
    block: dict,
    max_line_length: int = 88,
    comment_prefix: str = "# ",
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    list_wrap: bool = True,
) -> list[str]:
    """Rewrap a comment block to the specified line length.

    Returns the full flat list of rewrapped ``# ...`` output lines, concatenated
    across paragraph prompt units.
    """
    units = _block_prompt_units(
        block,
        max_line_length=max_line_length,
        comment_prefix=comment_prefix,
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
        list_wrap=list_wrap,
    )
    return [line for unit in units for line in unit["rewrapped"]]


def compute_comment_positions(content: str) -> set[tuple[int, int]] | None:
    """Return ``(lineno, col)`` positions of ``#`` characters that start real comments.

    *lineno* is 1-indexed and *col* is 0-indexed, matching ``tokenize`` semantics.
    Returns ``None`` when *content* is not valid Python — callers should fall back to
    string-scanning heuristics (which cannot distinguish a ``#`` inside a multi-line
    string from a real comment) in that case.
    """
    positions: set[tuple[int, int]] = set()
    try:
        readline = io.StringIO(content).readline
        for tok in tokenize.generate_tokens(readline):
            if tok.type == tokenize.COMMENT:
                positions.add(tok.start)
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return None
    return positions


def _should_extract_inline(
    line: str,
    max_line_length: int,
    line_no: int | None = None,
    valid_positions: set[tuple[int, int]] | None = None,
) -> bool:
    """Return ``True`` if *line* has an inline comment that should be extracted.

    When *valid_positions* is not ``None``, the ``#`` index found on *line* is
    cross-checked against tokenize-derived comment starts to avoid false positives
    such as a ``#`` inside a multi-line string literal.  *line_no* is the 1-indexed
    line number in the source file.
    """
    if len(line) <= max_line_length:
        return False
    result = extract_inline_comment(line)
    if result is None:
        return False
    if valid_positions is not None:
        idx = find_inline_comment(line)
        if (line_no, idx) not in valid_positions:
            return False
    _, comment_text = result
    return not is_tool_directive(comment_text)


def count_changed_blocks(
    content: str,
    max_line_length: int = 88,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    inline: bool = True,
    list_wrap: bool = True,
    changed_lines: set[int] | None = None,
) -> int:
    """Count comment blocks that will be interactively prompted.

    Only counts non-pragma blocks whose rewrapped output differs from the original.
    Pragma blocks are auto-applied in ``process_content()`` (never prompted), so they
    are traversed here solely to track the ``disabled`` state.  When *inline* is
    ``True``, overflowing inline comments also contribute to the count.

    When *changed_lines* is not ``None``, only blocks overlapping the given set of
    0-based line indices are considered.
    """
    lines_stripped = [line.rstrip("\n\r") for line in content.splitlines(keepends=True)]
    blocks = parse_comment_blocks(lines_stripped)
    comment_positions = compute_comment_positions(content)
    count = 0
    disabled = False

    for block in blocks:
        if block["type"] == "code":
            if not disabled and inline:
                for line_idx, line in enumerate(block["lines"]):
                    if changed_lines is not None:
                        if (block["start_idx"] + line_idx) not in changed_lines:
                            continue
                    if _should_extract_inline(
                        line,
                        max_line_length,
                        line_no=block["start_idx"] + line_idx + 1,
                        valid_positions=comment_positions,
                    ):
                        count += 1
            continue

        has_pragma = any(parse_pragma(bline) is not None for bline in block["lines"])

        if has_pragma:
            # Pragma blocks are auto-applied, not interactively prompted.  Walk the
            # lines only to update the disabled state.
            for bline in block["lines"]:
                p = parse_pragma(bline)
                if p is not None:
                    disabled = p == "off"
            continue

        if disabled:
            continue

        # Skip blocks that don't overlap with changed lines.
        if changed_lines is not None:
            block_range = range(
                block["start_idx"], block["start_idx"] + len(block["lines"])
            )
            if not any(i in changed_lines for i in block_range):
                continue

        units = _block_prompt_units(
            block,
            max_line_length,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            list_wrap=list_wrap,
        )
        for unit in units:
            if unit["original"] != unit["rewrapped"]:
                count += 1

    return count


def _record_a_extras(
    _state: dict | None,
    content: str,
    filepath: str,
    cursor: tuple,
    max_line_length: int,
    *,
    todo_patterns: list[str] | None,
    todo_case_sensitive: bool,
    todo_multiline: bool,
    inline: bool,
    list_wrap: bool,
    changed_lines: set[int] | None,
) -> None:
    """Record how many remaining changed paragraphs in *filepath* will be auto-accepted
    under this A decision, so the [X/Y] indicator reflects them.

    Idempotent: re-entry of a file (e.g. after undo of a later decision) replays
    the A and would otherwise overwrite or double-count. We compute the count once,
    on the first time A is pressed for this cursor, by subtracting the number of
    decisions already recorded for this file (which includes the just-appended A
    itself) from the total changed-paragraph count for the file.
    """
    if _state is None or "block_total" not in _state or "decisions" not in _state:
        return
    a_extras = _state.setdefault("a_extras", {})
    key = (filepath, cursor)
    if key in a_extras:
        # Defensive: re-traversal of the file containing A is only reached via undo, and
        # undo of A clears its a_extras entry before re-entry, so this branch is not
        # exercised in current flow.  Kept to make the helper safely idempotent for
        # future callers.
        return  # pragma: no cover
    total_in_file = count_changed_blocks(
        content,
        max_line_length,
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
        inline=inline,
        list_wrap=list_wrap,
        changed_lines=changed_lines,
    )
    decisions_for_file = sum(1 for d in _state["decisions"] if d.filepath == filepath)
    a_extras[key] = max(0, total_in_file - decisions_for_file)


_USE_COLOR: bool = True


def colorize(text: str, color: str) -> str:
    """Add ANSI color codes to text."""
    if not _USE_COLOR:
        return text
    colors = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "cyan": "\033[96m",
        "magenta": "\033[95m",
        "reset": "\033[0m",
        "bold": "\033[1m",
    }
    return f"{colors.get(color, '')}{text}{colors['reset']}"


def show_block_diff(
    original_lines: list[str],
    new_lines: list[str],
    start_line: int,
    filepath: str = "",
    progress: str = "",
    divider_width: int = 88,
) -> bool:
    """Display a diff for a single comment block.

    Returns True if there are changes, False otherwise.

    *divider_width* sets the character width of the top and bottom dividers.
    Callers typically pass ``max_line_length + 2`` so the rule extends past the
    two-character ``- `` / ``+ `` diff prefix and visually frames the wrap target.
    """
    if original_lines == new_lines:
        return False

    end = start_line + len(original_lines)
    if filepath:
        header = colorize(f"{filepath} Lines {start_line + 1}-{end}:", "bold")
    else:
        header = colorize(f"Lines {start_line + 1}-{end}:", "bold")
    if progress:
        header += " " + colorize(progress, "cyan")
    print(f"\n{header}")
    print(colorize("─" * divider_width, "cyan"))

    for line in original_lines:
        print(colorize(f"- {line}", "red"))
    for line in new_lines:
        print(colorize(f"+ {line}", "green"))

    print(colorize("─" * divider_width, "cyan"))
    return True


def _getch() -> str:
    """Read one logical keypress without waiting for Enter.

    Multi-byte input (arrow keys, function keys, Windows special keys, partial
    escape sequences left in the buffer by a paste) is consumed in full and
    reported as the empty string.  This prevents the trailing byte of an
    escape sequence (notably the ``A`` in ``\\x1b[A`` for up arrow) from being
    misread as a one-letter command, and prevents a paste's tail bytes from
    bleeding into the next prompt.

    Uses platform specific APIs (msvcrt on Windows, termios/tty/select on
    Unix), imported locally to avoid cross-platform resolution issues.

    On Unix, reads go through ``os.read`` on the raw stdin file descriptor
    rather than ``sys.stdin.read``.  ``sys.stdin`` is a buffered TextIOWrapper
    that may pre-fetch additional bytes from the kernel pipe on the first
    read; if it does, those bytes sit in Python's buffer where neither
    ``select.select`` nor ``termios.tcflush`` can see them, and the next
    ``read`` would surface them as bogus keypresses (e.g. the ``A`` in an up
    arrow's ``\\x1b[A`` being misread as ``accept all``).  Using ``os.read``
    keeps every byte at the OS layer where the drain logic can reach it.
    """
    if sys.platform == "win32":
        import msvcrt

        ch = msvcrt.getwch()
        # \x00 and \xe0 are scancode prefixes for arrows, F-keys, etc.; the next read
        # returns the actual scancode, which we discard.
        if ch in ("\x00", "\xe0"):
            msvcrt.getwch()
            ch = ""
        # Drain any further keys queued behind this one (paste tail, type-ahead).
        while msvcrt.kbhit():
            extra = msvcrt.getwch()
            if extra in ("\x00", "\xe0"):
                msvcrt.getwch()
        return ch

    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        try:
            data = os.read(fd, 1)
        except OSError:
            return ""
        if not data:
            return ""
        ch = data.decode("utf-8", errors="replace")
        if ch == "\x1b":
            # Drain the rest of the escape sequence.  A small timeout (rather than a
            # non-blocking peek) catches tails that arrive a few milliseconds late over
            # slow terminals or SSH; matches ncurses' ESCDELAY convention.
            while select.select([fd], [], [], 0.05)[0]:
                try:
                    if not os.read(fd, 64):
                        break
                except OSError:
                    break
            return ""
        # Drain anything else queued behind this keypress (paste tail, type-ahead) so it
        # doesn't bleed into the next prompt.  tcflush operates on the kernel queue,
        # which is where os.read leaves any unread bytes.
        termios.tcflush(fd, termios.TCIFLUSH)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def prompt_user(can_undo: bool = True) -> str:
    # noinspection GrazieInspection
    """Prompt user for action on a block.

    Returns: 'a' (accept), 'A' (accept all), 'e' (exclude), 'f' (flag),
    's' (skip), 'u' (undo, only when *can_undo* is True), or 'q' (quit).

    When *can_undo* is False, ``[u]ndo`` is omitted from the rendered prompt
    and ``u`` keypresses are silently rejected (the prompt re-displays).
    Callers should pass ``can_undo=False`` when there are no decisions to
    pop — typically the very first prompt of a session.
    """
    parts = [
        f"[{colorize('a', 'green')}]ccept",
        f"[{colorize('A', 'green')}]ccept all (current file)",
        f"[{colorize('e', 'cyan')}]xclude",
        f"[{colorize('f', 'magenta')}]lag",
        f"[{colorize('s', 'yellow')}]kip",
    ]
    if can_undo:
        parts.append(f"[{colorize('u', 'blue')}]ndo")
    parts.append(f"[{colorize('q', 'red')}]uit")
    prompt = " / ".join(parts) + "? "
    while True:
        try:
            sys.stdout.write(prompt)
            sys.stdout.flush()
            ch = _getch()
            if ch == "A":
                sys.stdout.write("A\n")
                sys.stdout.flush()
                return "A"
            lowered = ch.lower()
            if lowered in ("a", "e", "f", "s", "q"):
                sys.stdout.write(lowered + "\n")
                sys.stdout.flush()
                return lowered
            if lowered == "u" and can_undo:
                sys.stdout.write("u\n")
                sys.stdout.flush()
                return "u"
            sys.stdout.write("\n")
            sys.stdout.flush()
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
    inline: bool = True,
    list_wrap: bool = True,
    changed_lines: set[int] | None = None,
    *,
    decisions: list[Decision] | None = None,
    rewind_to_cursor: tuple | None = None,
    replay_only: bool = False,
) -> tuple[bool, str, str]:
    """Rewrap comment blocks in a string of Python source.

    Returns ``(changed, new_content, status)`` where ``status`` is one of
    ``"complete"``, ``"quit"``, or ``"rewind"``. When *_state* is a dict and the
    user presses quit in interactive mode, ``_state["quit"]`` is also set to
    ``True`` for backward compatibility with the pre-status callers.

    When *changed_lines* is not ``None``, only comment blocks whose line range overlaps
    the given set of 0-based line indices are processed.  Blocks with no overlap are
    preserved verbatim.

    When *decisions* is provided, each ``Decision``'s recorded action is replayed
    silently when its cursor is encountered during iteration — ``prompt_user()`` is
    skipped. The cursor at *rewind_to_cursor* (if any) is the exception: that
    position is always prompted, even if a decision exists for it. This is how
    Phase 4's undo feature re-enters mid-file at the popped position.

    When *replay_only* is True, the function never prompts: cursors with a
    matching decision replay it; cursors without a decision default to skip
    (preserve original). This is the mode used by ``_flush_dirty_at_quit`` to
    reconcile on-disk content with the final decision log at session end.
    """
    lines = content.splitlines(keepends=True)

    # Normalize line endings for processing
    lines_stripped = [line.rstrip("\n\r") for line in lines]

    blocks = parse_comment_blocks(lines_stripped)
    comment_positions = compute_comment_positions(content)

    decisions_by_cursor: dict[tuple, str] = (
        {d.cursor: d.action for d in decisions} if decisions else {}
    )

    # Recompute block_current so the progress indicator [X/Y] rolls back correctly after
    # undo. Each Decision contributes one bump (the prompt where it was made);
    # additionally, an "A" (accept-all) decision auto-accepts every subsequent changed
    # paragraph in its file without prompting, and those silent paragraphs also count
    # toward [X/Y]. Their per-A count is recorded in _state["a_extras"] at the time A is
    # pressed and re-summed here on every file entry so the indicator stays correct as
    # files come and go from the active set.
    if _state is not None and "block_total" in _state and "decisions" in _state:
        a_extras = _state.get("a_extras", {})
        extras_sum = sum(
            a_extras.get((d.filepath, d.cursor), 0)
            for d in _state["decisions"]
            if d.action == "A"
        )
        _state["block_current"] = len(_state["decisions"]) + extras_sum

    new_lines = []
    user_quit = False
    accept_all = False
    disabled = False

    for block in blocks:
        if block["type"] == "code":
            if not disabled and inline:
                line_idx = 0
                while line_idx < len(block["lines"]):
                    line = block["lines"][line_idx]
                    if user_quit:
                        new_lines.append(line)
                        line_idx += 1
                        continue

                    # Only consider lines that exceed the maximum length.
                    if len(line.rstrip("\n")) <= max_line_length:
                        new_lines.append(line)
                        line_idx += 1
                        continue

                    # Skip lines not in the changed set.
                    if changed_lines is not None:
                        if (block["start_idx"] + line_idx) not in changed_lines:
                            new_lines.append(line)
                            line_idx += 1
                            continue

                    # Extract the inline comment and build replacement lines.
                    extracted = extract_inline_comment(line)
                    if not extracted:
                        new_lines.append(line)
                        line_idx += 1
                        continue

                    # Guard against a ``#`` that lives inside a multi-line string
                    # literal: tokenize gives authoritative comment-start positions that
                    # the single-line scanner in find_inline_comment() cannot derive on
                    # its own.
                    if comment_positions is not None:
                        hash_col = find_inline_comment(line)
                        abs_line_no = block["start_idx"] + line_idx + 1
                        if (abs_line_no, hash_col) not in comment_positions:
                            new_lines.append(line)
                            line_idx += 1
                            continue

                    code_part, comment_text = extracted
                    if is_tool_directive(comment_text):
                        new_lines.append(line)
                        line_idx += 1
                        continue
                    indent = " " * (len(line) - len(line.lstrip()))
                    synthetic = {
                        "type": "comment_block",
                        "lines": [f"{indent}# {comment_text}"],
                        "indent": indent,
                        "start_idx": block["start_idx"] + line_idx,
                    }
                    wrapped_comment = rewrap_comment_block(
                        synthetic,
                        max_line_length,
                        todo_patterns=todo_patterns,
                        todo_case_sensitive=todo_case_sensitive,
                        todo_multiline=todo_multiline,
                        list_wrap=list_wrap,
                    )
                    replacement = wrapped_comment + [code_part]

                    if not interactive and not replay_only:
                        new_lines.extend(replacement)
                        line_idx += 1
                        continue
                    if accept_all:
                        new_lines.extend(replacement)
                        line_idx += 1
                        continue

                    cursor = (block["start_idx"], "inline", line_idx)
                    if cursor in decisions_by_cursor and cursor != rewind_to_cursor:
                        # Replay: silently apply the recorded action without prompting
                        # or showing a diff.
                        action = decisions_by_cursor[cursor]
                    elif replay_only:
                        # Un-decided cursor in replay_only mode → default to skip
                        # (preserve the original line).
                        new_lines.append(line)
                        line_idx += 1
                        continue
                    else:
                        progress = ""
                        if (
                            _state is not None
                            and "block_total" in _state
                            and _state["block_total"] > 0
                        ):
                            _state["block_current"] = _state.get("block_current", 0) + 1
                            progress = (
                                f"[{_state['block_current']}/{_state['block_total']}]"
                            )

                        has_changes = show_block_diff(
                            [line],
                            replacement,
                            block["start_idx"] + line_idx,
                            filepath=filepath,
                            progress=progress,
                            divider_width=max_line_length + 2,
                        )
                        if not has_changes:
                            # Defensive: inline extraction always changes the line count
                            # (1 -> 2+), so this branch is unreachable in practice.
                            new_lines.append(line)  # pragma: no cover
                            line_idx += 1  # pragma: no cover
                            continue  # pragma: no cover

                        can_undo = bool(_state is not None and _state.get("decisions"))
                        action = prompt_user(can_undo=can_undo)
                        if action == "u":
                            # Undo: pop the most recent decision, set the rewind target,
                            # and exit. The session driver will re-enter at the popped
                            # cursor.
                            assert _state is not None  # can_undo guarantees this
                            popped = _state["decisions"].pop()
                            if popped.action == "A":
                                _state.get("a_extras", {}).pop(
                                    (popped.filepath, popped.cursor), None
                                )
                            _state["rewind_target"] = popped
                            if popped.filepath in _state["last_written"]:
                                _state["dirty"].add(popped.filepath)
                            return False, "", "rewind"
                        if (
                            action != "q"
                            and _state is not None
                            and "decisions" in _state
                        ):
                            _state["decisions"].append(
                                Decision(filepath, cursor, action)
                            )

                    if action == "A":
                        accept_all = True
                        new_lines.extend(replacement)
                        _record_a_extras(
                            _state,
                            content,
                            filepath,
                            cursor,
                            max_line_length,
                            todo_patterns=todo_patterns,
                            todo_case_sensitive=todo_case_sensitive,
                            todo_multiline=todo_multiline,
                            inline=inline,
                            list_wrap=list_wrap,
                            changed_lines=changed_lines,
                        )
                    elif action == "a":
                        new_lines.extend(replacement)
                    elif action == "e":
                        new_lines.append(f"{indent}# octowrap: off")
                        new_lines.append(line)
                        new_lines.append(f"{indent}# octowrap: on")
                    elif action == "f":
                        initial = f"{indent}# FIXME: "
                        subsequent = f"{indent}#  "
                        flag_text = (
                            "Manually fix the below comment"
                            " (flagged using octowrap in"
                            " interactive mode)."
                        )
                        wrapped = textwrap.fill(
                            flag_text,
                            width=max_line_length,
                            initial_indent=initial,
                            subsequent_indent=subsequent,
                            break_on_hyphens=False,
                            break_long_words=False,
                        )
                        new_lines.append(f"{indent}# octowrap: off")
                        new_lines.extend(wrapped.split("\n"))
                        new_lines.append(line)
                        new_lines.append(f"{indent}# octowrap: on")
                    elif action == "q":
                        user_quit = True
                        if _state is not None:
                            _state["quit"] = True
                        new_lines.append(line)
                    else:  # skip
                        new_lines.append(line)
                    line_idx += 1
            else:
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
                                    list_wrap=list_wrap,
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
                            list_wrap=list_wrap,
                        )
                    )
            continue

        if disabled:
            # Rewrapping is suppressed, so preserve as is.
            new_lines.extend(block["lines"])
            continue

        # When diff-only filtering is active, skip blocks that don't overlap.
        if changed_lines is not None:
            block_range = range(
                block["start_idx"], block["start_idx"] + len(block["lines"])
            )
            if not any(i in changed_lines for i in block_range):
                new_lines.extend(block["lines"])
                continue

        # Split the block into per-prompt paragraph units (consecutive list items are
        # grouped into a single unit).
        units = _block_prompt_units(
            block,
            max_line_length,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            list_wrap=list_wrap,
        )

        unit_idx = 0
        while unit_idx < len(units):
            unit = units[unit_idx]
            original = unit["original"]
            rewrapped = unit["rewrapped"]

            if not interactive and not replay_only:
                new_lines.extend(rewrapped)
                unit_idx += 1
                continue
            if accept_all:
                new_lines.extend(rewrapped)
                unit_idx += 1
                continue
            if user_quit:
                new_lines.extend(original)
                unit_idx += 1
                continue
            if original == rewrapped:
                # Unchanged paragraph — pass through silently, no prompt.
                new_lines.extend(original)
                unit_idx += 1
                continue

            cursor = (block["start_idx"], unit["raw_start"])
            if cursor in decisions_by_cursor and cursor != rewind_to_cursor:
                # Replay: apply the recorded action without prompting or showing a diff.
                action = decisions_by_cursor[cursor]
            elif replay_only:
                # Un-decided paragraph in replay_only mode → default to skip (preserve
                # the original lines).
                new_lines.extend(original)
                unit_idx += 1
                continue
            else:
                progress = ""
                if (
                    _state is not None
                    and "block_total" in _state
                    and _state["block_total"] > 0
                ):
                    _state["block_current"] = _state.get("block_current", 0) + 1
                    progress = f"[{_state['block_current']}/{_state['block_total']}]"

                show_block_diff(
                    original,
                    rewrapped,
                    block["start_idx"] + unit["raw_start"],
                    filepath=filepath,
                    progress=progress,
                    divider_width=max_line_length + 2,
                )

                can_undo = bool(_state is not None and _state.get("decisions"))
                action = prompt_user(can_undo=can_undo)
                if action == "u":
                    # Undo: pop the most recent decision, set the rewind target, and
                    # exit. The session driver will re-enter at the popped cursor.
                    assert _state is not None  # can_undo guarantees this
                    popped = _state["decisions"].pop()
                    if popped.action == "A":
                        _state.get("a_extras", {}).pop(
                            (popped.filepath, popped.cursor), None
                        )
                    _state["rewind_target"] = popped
                    if popped.filepath in _state["last_written"]:
                        _state["dirty"].add(popped.filepath)
                    return False, "", "rewind"
                if action != "q" and _state is not None and "decisions" in _state:
                    _state["decisions"].append(Decision(filepath, cursor, action))

            if action == "A":
                accept_all = True
                new_lines.extend(rewrapped)
                _record_a_extras(
                    _state,
                    content,
                    filepath,
                    cursor,
                    max_line_length,
                    todo_patterns=todo_patterns,
                    todo_case_sensitive=todo_case_sensitive,
                    todo_multiline=todo_multiline,
                    inline=inline,
                    list_wrap=list_wrap,
                    changed_lines=changed_lines,
                )
            elif action == "a":
                new_lines.extend(rewrapped)
            elif action == "e":
                indent = block["indent"]
                new_lines.append(f"{indent}# octowrap: off")
                new_lines.extend(original)
                new_lines.append(f"{indent}# octowrap: on")
            elif action == "f":
                indent = block["indent"]
                initial = f"{indent}# FIXME: "
                subsequent = f"{indent}#  "
                flag_text = (
                    "Manually fix the below comment"
                    " (flagged using octowrap in interactive mode)."
                )
                wrapped = textwrap.fill(
                    flag_text,
                    width=max_line_length,
                    initial_indent=initial,
                    subsequent_indent=subsequent,
                    break_on_hyphens=False,
                    break_long_words=False,
                )
                new_lines.append(f"{indent}# octowrap: off")
                new_lines.extend(wrapped.split("\n"))
                new_lines.extend(original)
                new_lines.append(f"{indent}# octowrap: on")
            elif action == "q":
                user_quit = True
                if _state is not None:
                    _state["quit"] = True
                new_lines.extend(original)
            else:  # skip
                new_lines.extend(original)
            unit_idx += 1

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
    status = "quit" if user_quit else "complete"

    return changed, new_content, status


def _relative_path(filepath: Path) -> Path:
    """Return *filepath* relative to CWD when possible, otherwise unchanged."""
    try:
        return filepath.resolve().relative_to(Path.cwd())
    except ValueError:
        return filepath


def _atomic_write(filepath: Path, new_content: str) -> None:
    """Atomically replace *filepath* with *new_content*, preserving file mode."""
    original_mode = stat.S_IMODE(os.stat(filepath).st_mode)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with open(tmp_fd, "w", encoding="utf-8", newline="") as f:
            f.write(new_content)
        os.chmod(tmp_path, original_mode)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _drive_file(
    filepath: Path,
    max_line_length: int = 88,
    dry_run: bool = False,
    interactive: bool = False,
    _state: dict | None = None,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    inline: bool = True,
    list_wrap: bool = True,
    changed_lines: set[int] | None = None,
) -> tuple[bool, str]:
    """Read *filepath* and run ``process_content``; no file writes.

    Pure read + transform; the caller decides whether to persist. Returns
    ``(changed, new_content)`` — the third element of ``process_content``'s
    return (``status``) is dropped because the non-interactive path always
    completes normally.
    """
    with open(filepath, encoding="utf-8", newline="") as f:
        content = f.read()

    changed, new_content, _status = process_content(
        content,
        max_line_length,
        interactive=interactive and not dry_run,
        _state=_state,
        filepath=str(_relative_path(filepath)),
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
        inline=inline,
        list_wrap=list_wrap,
        changed_lines=changed_lines,
    )
    return changed, new_content


def _init_session_state(state: dict | None) -> dict:
    """Ensure *state* has every session-driver key initialized; return it.

    Idempotent — passing a partially-populated dict (e.g. one that already has
    ``decisions``) preserves existing values and only fills in the missing
    keys.
    """
    if state is None:
        state = {}
    state.setdefault("decisions", [])
    state.setdefault("originals", {})
    state.setdefault("last_written", {})
    state.setdefault("dirty", set())
    state.setdefault("rewind_target", None)
    state.setdefault("a_extras", {})
    return state


def _flush_dirty_at_quit(
    _state: dict,
    paths_by_key: dict[str, Path],
    *,
    max_line_length: int = 88,
    dry_run: bool = False,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    inline: bool = True,
    list_wrap: bool = True,
) -> None:
    """Reconcile on-disk content with the final decision log at session end.

    Walks each file in ``_state["dirty"]`` (the set of files that were
    atomic-written this session and whose decision log has since been
    mutated by undo), replays its decisions in ``replay_only`` mode
    (un-decided cursors default to skip), and atomically writes when the
    result differs from the last-written content.

    Dirty membership is the right scope: non-interactive runs never mark
    files dirty, so this is a no-op for them. For interactive runs, only
    files that have a meaningful pending reconciliation get rewritten —
    files that completed cleanly are already consistent with their log.
    """
    if dry_run:
        return
    for key in list(_state["dirty"]):
        if key not in _state["originals"]:  # pragma: no cover
            # Defensive: dirty membership is only ever set via undo, which always pops a
            # Decision whose filepath was already populated in originals upstream.
            _state["dirty"].discard(key)
            continue
        original = _state["originals"][key]
        decisions_for_file = [d for d in _state["decisions"] if d.filepath == key]
        _changed, new_content, _status = process_content(
            original,
            max_line_length,
            interactive=False,
            _state=None,  # No state mutation during flush replay.
            filepath=key,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            inline=inline,
            list_wrap=list_wrap,
            decisions=decisions_for_file,
            replay_only=True,
        )
        prior = _state["last_written"].get(key, original)
        if new_content != prior:
            fp = paths_by_key.get(key, Path(key))
            _atomic_write(fp, new_content)
            _state["last_written"][key] = new_content
        _state["dirty"].discard(key)


def _run_session(
    filepaths: list[Path],
    _state: dict,
    *,
    max_line_length: int = 88,
    dry_run: bool = False,
    interactive: bool = False,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    inline: bool = True,
    list_wrap: bool = True,
    changed_lines_for: Callable[[Path], set[int] | None] | None = None,
) -> Iterator[dict]:
    """Drive a sequence of files through ``process_content`` with replay and undo.

    Generator that yields one result dict per processed file as soon as that
    file completes (or errors). Yielding lets callers interleave per-file
    output (e.g. ``Reformatted: foo.py``) with subsequent files' interactive
    prompts, preserving the pre-refactor UX ordering.

    Each yielded dict has keys: ``filepath``, ``changed``, ``new_content``,
    ``original``, ``status`` (``"complete"``, ``"quit"``, or ``"error"``), and
    ``error`` (an exception or ``None``). On quit, the loop terminates after
    yielding the quitting file's result.

    The driver caches each file's original content in ``_state["originals"]``
    on first read, atomically writes when the new content differs from what
    was last written (or the original, for unwritten files), and tracks the
    last-written content in ``_state["last_written"]``. On undo, the loop
    jumps to the rewind target's file and re-enters; un-decided cursors are
    re-prompted, replayed cursors are silently applied. A final flush in the
    ``finally`` block ensures every file on disk matches the final decision
    log, even when the user quits or the consumer breaks out early.
    """
    paths_by_key: dict[str, Path] = {str(_relative_path(fp)): fp for fp in filepaths}
    try:
        i = 0
        while i < len(filepaths):
            fp = filepaths[i]
            key = str(_relative_path(fp))
            try:
                if key not in _state["originals"]:
                    with open(fp, encoding="utf-8", newline="") as f:
                        _state["originals"][key] = f.read()
                content = _state["originals"][key]
                decisions_for_file = [
                    d for d in _state["decisions"] if d.filepath == key
                ]
                rewind_target = _state.get("rewind_target")
                rewind_cursor = (
                    rewind_target.cursor
                    if rewind_target is not None and rewind_target.filepath == key
                    else None
                )
                changed, new_content, status = process_content(
                    content,
                    max_line_length,
                    interactive=interactive and not dry_run,
                    _state=_state,
                    filepath=key,
                    todo_patterns=todo_patterns,
                    todo_case_sensitive=todo_case_sensitive,
                    todo_multiline=todo_multiline,
                    inline=inline,
                    list_wrap=list_wrap,
                    changed_lines=(
                        changed_lines_for(fp) if changed_lines_for else None
                    ),
                    decisions=decisions_for_file,
                    rewind_to_cursor=rewind_cursor,
                )
            except Exception as e:
                yield {
                    "filepath": fp,
                    "changed": False,
                    "new_content": "",
                    "original": _state["originals"].get(key, ""),
                    "status": "error",
                    "error": e,
                }
                i += 1
                continue

            if status == "rewind":
                target = _state["rewind_target"]
                assert target is not None
                for j, fpj in enumerate(filepaths):
                    if str(_relative_path(fpj)) == target.filepath:
                        i = j
                        break
                continue

            # Atomic-write only when the new content differs from what we last wrote (or
            # the original, for unwritten files). This subsumes the dirty-set check: a
            # dirty file whose replay happens to match the prior write needs no I/O.
            prior = _state["last_written"].get(key, _state["originals"][key])
            if not dry_run and new_content != prior:
                _atomic_write(fp, new_content)
                _state["last_written"][key] = new_content
            _state["dirty"].discard(key)

            yield {
                "filepath": fp,
                "changed": changed,
                "new_content": new_content,
                "original": _state["originals"][key],
                "status": status,
                "error": None,
            }

            if status == "quit":
                return
            i += 1
    finally:
        _flush_dirty_at_quit(
            _state,
            paths_by_key,
            max_line_length=max_line_length,
            dry_run=dry_run,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            inline=inline,
            list_wrap=list_wrap,
        )


def process_file(
    filepath: Path,
    max_line_length: int = 88,
    dry_run: bool = False,
    interactive: bool = False,
    _state: dict | None = None,
    todo_patterns: list[str] | None = None,
    todo_case_sensitive: bool = False,
    todo_multiline: bool = True,
    inline: bool = True,
    list_wrap: bool = True,
    changed_lines: set[int] | None = None,
) -> tuple[bool, str]:
    """Process a single file, rewrapping comment blocks.

    Returns (changed, new_content). Interactive runs are routed through
    ``_run_session`` so single-file callers exercise the same replay-aware
    driver that ``main()`` uses.
    """
    if interactive and not dry_run:
        state = _init_session_state(_state)
        for _result in _run_session(
            [filepath],
            state,
            max_line_length=max_line_length,
            dry_run=dry_run,
            interactive=True,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            inline=inline,
            list_wrap=list_wrap,
            changed_lines_for=(
                (lambda _fp: changed_lines) if changed_lines is not None else None
            ),
        ):
            if _result["error"] is not None:
                raise _result["error"]
        key = str(_relative_path(filepath))
        original = state["originals"].get(key, "")
        new_content = state["last_written"].get(key, original)
        return new_content != original, new_content

    changed, new_content = _drive_file(
        filepath,
        max_line_length,
        dry_run=dry_run,
        interactive=interactive,
        _state=_state,
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
        inline=inline,
        list_wrap=list_wrap,
        changed_lines=changed_lines,
    )

    if changed and not dry_run:
        _atomic_write(filepath, new_content)

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
        "--no-inline",
        action="store_true",
        default=None,
        help="Disable extraction of overflowing inline comments",
    )
    parser.add_argument(
        "--diff-only",
        action="store_true",
        default=None,
        help="Only process comment blocks overlapping lines changed in git",
    )
    parser.add_argument(
        "--diff-base",
        type=str,
        default=None,
        help="Git ref to diff against (default: HEAD, implies --diff-only)",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to pyproject.toml config file (default: auto-discover)",
    )
    parser.add_argument(
        "--stdin-filename",
        type=Path,
        default=None,
        help="Filename for config discovery and diff display (only valid with '-')",
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
        if args.stdin_filename is not None and args.config is None:
            discovered = find_config_file(args.stdin_filename.parent)
            config = load_config(discovered)
        else:
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

    # Inline: default True, config can override, --no-inline wins
    if args.no_inline is None:
        args.inline = config.get("inline", True)
    else:
        args.inline = False

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
            # Explicit empty list disables TODO detection entirely; ignore
            # extend-todo-patterns.
            pass
        elif "extend-todo-patterns" in config:
            todo_patterns = todo_patterns + config["extend-todo-patterns"]
    elif "extend-todo-patterns" in config:
        todo_patterns = todo_patterns + config["extend-todo-patterns"]
    todo_case_sensitive = config.get("todo-case-sensitive", DEFAULT_TODO_CASE_SENSITIVE)
    todo_multiline = config.get("todo-multiline", DEFAULT_TODO_MULTILINE)
    list_wrap = config.get("list-wrap", DEFAULT_LIST_WRAP)

    # Diff-only: default False, config can override, --diff-only or --diff-base wins
    diff_only = False
    diff_base = "HEAD"
    if args.diff_only is not None:
        diff_only = True
    elif args.diff_base is not None:
        diff_only = True
    elif config.get("diff-only", False):
        diff_only = True
    if args.diff_base is not None:
        diff_base = args.diff_base
    elif "diff-base" in config:
        diff_base = config["diff-base"]

    if args.diff or args.check:
        args.dry_run = True

    # Handle stdin mode when '-' is passed as a path
    stdin_mode = any(str(p) == "-" for p in args.paths)

    if diff_only and stdin_mode:
        print(
            "octowrap: error: --diff-only cannot be used with stdin",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.stdin_filename is not None and not stdin_mode:
        print(
            "octowrap: error: --stdin-filename requires '-' (stdin mode)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if args.stdin_filename is not None and args.stdin_filename.suffix != ".py":
        print(
            f"octowrap: error: --stdin-filename {args.stdin_filename} is not a "
            "Python file",
            file=sys.stderr,
        )
        raise SystemExit(1)

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
        changed, new_content, _status = process_content(
            content,
            args.line_length,
            todo_patterns=todo_patterns,
            todo_case_sensitive=todo_case_sensitive,
            todo_multiline=todo_multiline,
            inline=args.inline,
            list_wrap=list_wrap,
        )

        if args.diff and changed:
            diff_label = str(args.stdin_filename) if args.stdin_filename else "<stdin>"
            diff = difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=diff_label,
                tofile=diff_label,
            )
            sys.stdout.write("".join(diff))
        elif not (args.diff or args.check):
            sys.stdout.write(new_content)

        if args.check:
            raise SystemExit(1 if changed else 0)

        raise SystemExit(0)

    if args.interactive and not sys.stdin.isatty():
        print(
            "octowrap: error: --interactive requires a TTY",
            file=sys.stderr,
        )
        raise SystemExit(1)

    files_to_process = []
    for path in args.paths:
        if path.is_file():
            if path.suffix != ".py":
                print(f"Warning: {path} is not a Python file, skipping")
            else:
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

    # When diff-only is active, compute the set of changed lines per file once.
    all_changed_lines: dict[str, set[int]] | None = None
    repo_root: Path | None = None
    if diff_only:
        if shutil.which("git") is None:
            print(
                "octowrap: error: --diff-only requires git (not found on PATH)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        repo_root = get_repo_root()
        if repo_root is None:
            print(
                "octowrap: error: --diff-only must be run inside a git repository",
                file=sys.stderr,
            )
            raise SystemExit(1)
        try:
            all_changed_lines = get_changed_lines(diff_base)
        except NotAGitRepoError as exc:
            print(
                f"octowrap: error: --diff-only failed: {exc}",
                file=sys.stderr,
            )
            raise SystemExit(1)

    def _file_changed_lines(filepath: Path) -> set[int] | None:
        """Look up the changed lines for *filepath*, or None if not filtering."""
        if all_changed_lines is None:
            return None
        assert repo_root is not None
        try:
            rel_path = filepath.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            rel_path = str(filepath)
        return all_changed_lines.get(rel_path, set())

    changed_count = 0
    error_count = 0
    interactive_state: dict = _init_session_state(None)

    # Pre-scan to count total changed blocks for interactive progress indicator.
    if args.interactive and not args.dry_run:
        total_blocks = 0
        for fp in files_to_process:
            try:
                file_content = fp.read_text(encoding="utf-8")
                total_blocks += count_changed_blocks(
                    file_content,
                    args.line_length,
                    todo_patterns=todo_patterns,
                    todo_case_sensitive=todo_case_sensitive,
                    todo_multiline=todo_multiline,
                    inline=args.inline,
                    list_wrap=list_wrap,
                    changed_lines=_file_changed_lines(fp),
                )
            except OSError:
                pass  # Errors will be reported during the actual processing pass.
        interactive_state["block_total"] = total_blocks
        interactive_state["block_current"] = 0

    for result in _run_session(
        files_to_process,
        interactive_state,
        max_line_length=args.line_length,
        dry_run=args.dry_run,
        interactive=args.interactive,
        todo_patterns=todo_patterns,
        todo_case_sensitive=todo_case_sensitive,
        todo_multiline=todo_multiline,
        inline=args.inline,
        list_wrap=list_wrap,
        changed_lines_for=_file_changed_lines,
    ):
        filepath = result["filepath"]
        if result["error"] is not None:
            print(
                f"error: Failed to process {filepath}: {result['error']}",
                file=sys.stderr,
            )
            error_count += 1
            continue
        if result["changed"]:
            changed_count += 1
            if args.diff:
                diff = difflib.unified_diff(
                    result["original"].splitlines(keepends=True),
                    result["new_content"].splitlines(keepends=True),
                    fromfile=str(filepath),
                    tofile=str(filepath),
                )
                print("".join(diff))
            elif args.dry_run:
                print(f"Would reformat: {filepath}")
            else:
                print(f"Reformatted: {filepath}")

    action = "would be reformatted" if args.dry_run else "reformatted"
    print(f"\n{changed_count} file(s) {action}.")

    if error_count > 0:
        raise SystemExit(2)
    if args.check and changed_count > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
