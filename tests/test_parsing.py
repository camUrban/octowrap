from octowrap.rewrap import parse_comment_blocks


class TestParseCommentBlocks:
    def test_basic_code_comment_code(self):
        lines = [
            "x = 1",
            "# This is a comment",
            "# that spans two lines",
            "y = 2",
        ]
        blocks = parse_comment_blocks(lines)
        assert len(blocks) == 3
        assert blocks[0]["type"] == "code"
        assert blocks[1]["type"] == "comment_block"
        assert blocks[1]["lines"] == ["# This is a comment", "# that spans two lines"]
        assert blocks[2]["type"] == "code"

    def test_different_indent_levels_split(self):
        """Adjacent comments at different indents become separate blocks."""
        lines = [
            "# top-level comment",
            "    # indented comment",
        ]
        blocks = parse_comment_blocks(lines)
        assert len(blocks) == 2
        assert blocks[0]["type"] == "comment_block"
        assert blocks[0]["indent"] == ""
        assert blocks[1]["type"] == "comment_block"
        assert blocks[1]["indent"] == "    "

    def test_shebang_skipped(self):
        """Shebang lines should not be treated as comment blocks."""
        lines = [
            "#!/usr/bin/env python",
            "# Normal comment",
        ]
        blocks = parse_comment_blocks(lines)
        assert blocks[0]["type"] == "code"
        assert blocks[0]["lines"] == ["#!/usr/bin/env python"]
        assert blocks[1]["type"] == "comment_block"
        assert blocks[1]["lines"] == ["# Normal comment"]

    def test_inline_comment_stays_as_code(self):
        """A line with code followed by a comment is code, not a comment block."""
        lines = [
            "x = 1  # inline comment",
            "y = 2",
        ]
        blocks = parse_comment_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert blocks[0]["lines"] == ["x = 1  # inline comment", "y = 2"]

    def test_all_comments(self):
        """A file that is entirely comments produces a single comment block."""
        lines = [
            "# Line one",
            "# Line two",
            "# Line three",
        ]
        blocks = parse_comment_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "comment_block"
        assert len(blocks[0]["lines"]) == 3

    def test_empty_file(self):
        blocks = parse_comment_blocks([])
        assert blocks == []

    def test_consecutive_code_lines_merge(self):
        """Multiple code lines in a row should merge into one code block."""
        lines = [
            "x = 1",
            "y = 2",
            "z = 3",
        ]
        blocks = parse_comment_blocks(lines)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "code"
        assert len(blocks[0]["lines"]) == 3

    def test_start_idx_tracking(self):
        """Each block should record its starting line index."""
        lines = [
            "x = 1",
            "# comment",
            "y = 2",
        ]
        blocks = parse_comment_blocks(lines)
        assert blocks[0]["start_idx"] == 0
        assert blocks[1]["start_idx"] == 1
        assert blocks[2]["start_idx"] == 2

    def test_blank_line_separates_comment_blocks(self):
        """A blank line between comments creates separate blocks."""
        lines = [
            "# First block",
            "",
            "# Second block",
        ]
        blocks = parse_comment_blocks(lines)
        # blank line is code, so: comment, code, comment
        assert len(blocks) == 3
        assert blocks[0]["type"] == "comment_block"
        assert blocks[1]["type"] == "code"
        assert blocks[2]["type"] == "comment_block"
