import sys

import pytest


def make_block(lines, indent=""):
    """Build a comment block dict for use with rewrap_comment_block."""
    return {
        "indent": indent,
        "lines": lines,
    }


@pytest.fixture(autouse=True)
def _stdin_isatty_default(monkeypatch):
    """Pretend stdin is a TTY by default.

    main() refuses --interactive when stdin isn't a TTY, but pytest's captured stdin
    reports isatty()==False, which would block the many CLI tests that drive interactive
    mode by mocking prompt_user.  Tests that need the opposite (e.g. exercising the TTY
    guard) override this with their own monkeypatch.setattr call.
    """
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
