"""Parse unified diffs to extract changed line numbers per file."""

import re
import subprocess
from pathlib import Path

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


class NotAGitRepoError(Exception):
    """Raised when a git operation is attempted outside a git repository."""


def get_repo_root() -> Path | None:
    """Return the root of the current git repository, or ``None``."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_changed_lines(base: str = "HEAD") -> dict[str, set[int]]:
    """Run ``git diff -U0`` against *base* and return per-file changed line numbers.

    Returns a dict mapping file paths (relative to the repo root) to sets of 0-based
    line indices.  Raises :class:`NotAGitRepoError` if not inside a git repository or
    if git is not installed.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "-U0", base],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise NotAGitRepoError(
            "Not inside a git repository or git ref not found"
        ) from exc
    except FileNotFoundError as exc:
        raise NotAGitRepoError("git is not installed") from exc

    return parse_diff_line_numbers(result.stdout)
