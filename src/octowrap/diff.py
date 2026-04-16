"""Parse unified diffs to extract changed line numbers per file."""

import re

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$")


def parse_diff_line_numbers(diff_text: str) -> dict[str, set[int]]:
    """Parse ``git diff -U0`` output into per-file changed line numbers.

    Returns a dict mapping file paths (relative to the repo root) to sets of 0-based
    line indices that were added or modified.
    """
    result: dict[str, set[int]] = {}
    current_file: str | None = None

    for line in diff_text.splitlines():
        file_match = _FILE_RE.match(line)
        if file_match:
            current_file = file_match.group(1)
            if current_file not in result:
                result[current_file] = set()
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match and current_file is not None:
            start = int(hunk_match.group(1))
            count = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            # Convert from 1-based diff line numbers to 0-based indices.
            for i in range(count):
                result[current_file].add(start - 1 + i)

    return result
