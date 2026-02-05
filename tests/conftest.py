def make_block(lines, indent=""):
    """Build a comment block dict for use with rewrap_comment_block."""
    return {
        "indent": indent,
        "lines": lines,
    }
