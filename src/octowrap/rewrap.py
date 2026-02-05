"""Rewrap # comments to a specified line width.

This script identifies contiguous blocks of # comments at the same indentation
level and rewraps them using textwrap. It preserves:
- Commented out code (heuristic detection)
- Section dividers (lines of repeated characters like # ---- or # ====)
- Inline comments (# after code on the same line)
- Intentional short lines and blank comment lines
- Lists and bullet points
"""

import argparse
import re
import textwrap
from pathlib import Path


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
        r"^\s*TODO\s*:",  # TODO items
        r"^\s*FIXME\s*:",  # FIXME items
        r"^\s*NOTE\s*:",  # NOTE items
        r"^\s*XXX\s*:",  # XXX items
        r"^\s*HACK\s*:",  # HACK items
    ]
    return any(re.match(p, text) for p in list_patterns)


def should_preserve_line(text: str) -> bool:
    """Determine if a comment line should be preserved as is."""
    if not text.strip():
        return True  # blank comment line
    if is_likely_code(text):
        return True
    if is_divider(text):
        return True
    return False


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
    block: dict, max_line_length: int = 88, comment_prefix: str = "# "
) -> list[str]:
    """Rewrap a comment block to the specified line length."""
    indent = block["indent"]
    lines = block["lines"]

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
            contents.append("")

    # Group into paragraphs (separated by blank comment lines or preserved lines)
    paragraphs = []
    current_para = []

    for content in contents:
        if not content.strip():
            # Blank line: end current paragraph
            if current_para:
                paragraphs.append(("wrap", current_para))
                current_para = []
            paragraphs.append(("blank", [""]))
        elif should_preserve_line(content) or is_list_item(content):
            # Preserve this line as is
            if current_para:
                paragraphs.append(("wrap", current_para))
                current_para = []
            paragraphs.append(("preserve", [content]))
        else:
            current_para.append(content)

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
                    result.append(indent + "#")
        else:  # wrap
            text = " ".join(para_contents)
            wrapped = textwrap.fill(text, width=text_width)
            for wrapped_line in wrapped.split("\n"):
                result.append(prefix + wrapped_line)

    return result


def colorize(text: str, color: str) -> str:
    """Add ANSI color codes to text."""
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
    original_lines: list[str], new_lines: list[str], start_line: int
) -> bool:
    """Display a diff for a single comment block.

    Returns True if there are changes, False otherwise.
    """
    if original_lines == new_lines:
        return False

    print(
        f"\n{colorize(f'Lines {start_line + 1}-{start_line + len(original_lines)}:', 'bold')}"
    )
    print(colorize("─" * 60, "cyan"))

    for line in original_lines:
        print(colorize(f"- {line}", "red"))
    for line in new_lines:
        print(colorize(f"+ {line}", "green"))

    print(colorize("─" * 60, "cyan"))
    return True


def prompt_user() -> str:
    """Prompt user for action on a block.

    Returns: 'a' (accept), 's' (skip), or 'q' (quit)
    """
    while True:
        try:
            response = (
                input(
                    f"[{colorize('a', 'green')}]ccept / [{colorize('s', 'yellow')}]kip / [{colorize('q', 'red')}]uit? "
                )
                .strip()
                .lower()
            )
            if response in ("a", "s", "q", ""):
                return response if response else "s"  # default to skip on empty
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"


def process_file(
    filepath: Path,
    max_line_length: int = 88,
    dry_run: bool = False,
    accept_all: bool = False,
) -> tuple[bool, str]:
    """Process a single file, rewrapping comment blocks.

    Returns (changed, new_content).
    """
    content = filepath.read_text()
    lines = content.splitlines(keepends=True)

    # Normalize line endings for processing
    lines_stripped = [line.rstrip("\n\r") for line in lines]

    blocks = parse_comment_blocks(lines_stripped)

    new_lines = []
    user_quit = False

    for block in blocks:
        if block["type"] == "code":
            new_lines.extend(block["lines"])
        else:
            rewrapped = rewrap_comment_block(block, max_line_length)

            if accept_all or dry_run:
                # Non interactive: just apply all changes
                new_lines.extend(rewrapped)
            else:
                # Interactive mode
                has_changes = show_block_diff(
                    block["lines"], rewrapped, block["start_idx"]
                )

                if has_changes and not user_quit:
                    action = prompt_user()

                    if action == "a":
                        new_lines.extend(rewrapped)
                    elif action == "q":
                        user_quit = True
                        new_lines.extend(block["lines"])  # keep original
                    else:  # skip
                        new_lines.extend(block["lines"])  # keep original
                else:
                    new_lines.extend(block["lines"])

    # Restore original line ending style
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

    if changed and not dry_run:
        filepath.write_text(new_content)

    return changed, new_content


def main():
    parser = argparse.ArgumentParser(
        description="Rewrap # block comments to a specified line width."
    )
    parser.add_argument(
        "paths", nargs="+", type=Path, help="Files or directories to process"
    )
    parser.add_argument(
        "-l",
        "--line-length",
        type=int,
        default=88,
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
        "-r", "--recursive", action="store_true", help="Process directories recursively"
    )
    parser.add_argument(
        "-a",
        "--accept-all",
        action="store_true",
        help="Accept all changes without prompting (non-interactive)",
    )

    args = parser.parse_args()

    if args.diff:
        args.dry_run = True
        args.accept_all = True  # --diff implies non interactive

    files_to_process = []
    for path in args.paths:
        if path.is_file():
            files_to_process.append(path)
        elif path.is_dir():
            if args.recursive:
                files_to_process.extend(path.rglob("*.py"))
            else:
                files_to_process.extend(path.glob("*.py"))
        else:
            print(f"Warning: {path} not found, skipping")

    changed_count = 0
    for filepath in files_to_process:
        try:
            original: str | None = filepath.read_text() if args.diff else None
            changed, new_content = process_file(
                filepath,
                args.line_length,
                dry_run=args.dry_run,
                accept_all=args.accept_all,
            )

            if changed:
                changed_count += 1
                if args.diff:
                    assert type(original) is str

                    import difflib

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

    action = "would be reformatted" if args.dry_run else "reformatted"
    print(f"\n{changed_count} file(s) {action}.")


if __name__ == "__main__":
    main()
