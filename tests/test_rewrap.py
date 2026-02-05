from conftest import make_block

from octowrap.rewrap import rewrap_comment_block


def test_short_line_unchanged():
    block = make_block(["# Short."])
    result = rewrap_comment_block(block, max_line_length=88)
    assert result == ["# Short."]


def test_text_width_too_narrow_returns_original():
    """When indent + prefix eats most of the line length, the block's returned as is."""
    block = make_block(
        [
            "                        # This should not be rewrapped",
            "                        # because the text width is too narrow.",
        ],
        indent="                        ",
    )
    # indent (24) + "# " (2) = 26, leaving only 4 chars of text width (< 20)
    result = rewrap_comment_block(block, max_line_length=30)
    assert result == block["lines"]


def test_list_items_preserved():
    """List items should not be merged into surrounding prose."""
    block = make_block(
        [
            "# This function does several things:",
            "# - Validates the input",
            "# - Processes the data",
            "# - Returns the result",
        ]
    )
    result = rewrap_comment_block(block, max_line_length=88)
    assert "# - Validates the input" in result
    assert "# - Processes the data" in result
    assert "# - Returns the result" in result


def test_divider_preserved():
    """Divider lines should not be merged into prose."""
    block = make_block(
        [
            "# Section header",
            "# ----------------------------------------",
            "# Section body that is a normal comment.",
        ]
    )
    result = rewrap_comment_block(block, max_line_length=88)
    assert "# ----------------------------------------" in result


def test_blank_comment_line_separates_paragraphs():
    """A blank '#' line should act as a paragraph separator."""
    block = make_block(
        [
            "# First paragraph.",
            "#",
            "# Second paragraph.",
        ]
    )
    result = rewrap_comment_block(block, max_line_length=88)
    assert result == ["# First paragraph.", "#", "# Second paragraph."]


class TestRewrapToWiderLength:
    """Comments previously wrapped at a shorter line length should be reflowed to fill
    the wider target length."""

    def test_72_to_88(self):
        """A paragraph wrapped at 72 chars should be rewrapped to 88."""
        block = make_block(
            [
                "# This is a comment block that was previously wrapped to a",
                "# shorter line length and should be rewrapped to the wider",
                "# target.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert len(result) < len(block["lines"])
        for line in result:
            assert len(line) <= 88

    def test_60_to_88(self):
        """A paragraph wrapped at ~60 chars should be rewrapped to 88."""
        block = make_block(
            [
                "# This function calculates the total",
                "# revenue for a given quarter by summing",
                "# all individual transaction amounts and",
                "# applying the appropriate tax rate.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert len(result) < len(block["lines"])
        for line in result:
            assert len(line) <= 88

    def test_indented_block_rewraps_wider(self):
        """An indented block wrapped short should also reflow wider."""
        block = make_block(
            [
                "    # This helper validates the input",
                "    # parameters before passing them to",
                "    # the main processing function.",
            ],
            indent="    ",
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert len(result) < len(block["lines"])
        for line in result:
            assert len(line) <= 88
            assert line.startswith("    # ")

    def test_exact_content_preserved(self):
        """All words from the original block must appear in the result."""
        block = make_block(
            [
                "# The quick brown fox jumps over the",
                "# lazy dog while the cat watches from",
                "# the warm windowsill above.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)

        original_text = " ".join(line.lstrip("# ") for line in block["lines"])
        result_text = " ".join(line.lstrip("# ") for line in result)
        assert original_text.split() == result_text.split()

    def test_already_at_target_width_unchanged(self):
        """A block already wrapped at the target width should not change."""
        block = make_block(
            [
                "# This is a comment that has already been wrapped to eighty-eight columns and it",
                "# should remain completely unchanged when rewrapped at the same width.",
            ]
        )
        stable = rewrap_comment_block(block, max_line_length=88)
        result = rewrap_comment_block(make_block(stable), max_line_length=88)
        assert result == stable

    def test_multiple_paragraphs_both_rewrap(self):
        """Multiple paragraphs separated by a blank comment should both reflow."""
        block = make_block(
            [
                "# First paragraph that was wrapped",
                "# at a narrow width previously.",
                "#",
                "# Second paragraph also wrapped at",
                "# the same narrow width as above.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert (
            result[0]
            == "# First paragraph that was wrapped at a narrow width previously."
        )
        assert result[1] == "#"
        assert (
            result[2]
            == "# Second paragraph also wrapped at the same narrow width as above."
        )

    def test_preserved_lines_not_merged(self):
        """Commented out code within a block must not be merged during rewrap."""
        block = make_block(
            [
                "# This comment was wrapped at a short",
                "# width and should be rewrapped wider.",
                "# x = 5",
                "# But this part should also be rewrapped",
                "# to the wider target length now.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# x = 5" in result
        assert (
            "# This comment was wrapped at a short width and should be rewrapped wider."
            in result
        )
        assert (
            "# But this part should also be rewrapped to the wider target length now."
            in result
        )
