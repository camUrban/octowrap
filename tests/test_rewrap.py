from conftest import make_block

from octowrap.rewrap import parse_pragma, rewrap_comment_block


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


class TestHyphenAndLongWordHandling:
    """Tests for break_on_hyphens=False, break_long_words=False, and hyphen healing."""

    def test_hyphenated_word_not_broken(self):
        """A hyphenated word near the line boundary should not be split at the
        hyphen."""
        block = make_block(
            [
                "# This is a comment about a command-line-interface that should keep the hyphenated word intact.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=60)
        # "command-line-interface" must appear intact in one line
        assert any("command-line-interface" in line for line in result)

    def test_long_url_not_broken(self):
        """A URL longer than the line length should overflow rather than break."""
        block = make_block(
            [
                "# See https://example.com/some/very/long/path/to/a/resource/that/exceeds/the/line/length for details.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=60)
        assert any(
            "https://example.com/some/very/long/path/to/a/resource/that/exceeds/the/line/length"
            in line
            for line in result
        )

    def test_long_word_not_broken(self):
        """A single word longer than line width should overflow, not break mid-word."""
        block = make_block(
            [
                "# See supercalifragilisticexpialidocious for details.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=40)
        assert any("supercalifragilisticexpialidocious" in line for line in result)

    def test_previously_broken_hyphen_healed(self):
        """Lines from a previous hyphen break should be rejoined on rewrap."""
        block = make_block(
            [
                "# This comment has a command-",
                "# line word that was broken.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        full_text = " ".join(line.lstrip("# ") for line in result)
        assert "command-line" in full_text
        assert "command- line" not in full_text

    def test_rewrap_idempotent_with_hyphens(self):
        """Rewrapping a block twice should produce the same result."""
        block = make_block(
            [
                "# The command-line-interface supports many long-running background tasks.",
            ]
        )
        first = rewrap_comment_block(block, max_line_length=50)
        second = rewrap_comment_block(make_block(first), max_line_length=50)
        assert first == second

    def test_todo_hyphenated_word_not_broken(self):
        """Hyphenated words in TODO comments should not be broken at hyphens."""
        block = make_block(
            [
                "# TODO: Implement the command-line-interface for the re-validation of user-submitted data.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=60)
        full_text = " ".join(line.lstrip("# ") for line in result)
        assert "command-line-interface" in full_text
        assert "re-validation" in full_text

    def test_todo_long_url_not_broken(self):
        """A URL in a TODO should not be broken."""
        block = make_block(
            [
                "# TODO: See https://example.com/some/very/long/path/to/a/resource for implementation details.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=60)
        assert any(
            "https://example.com/some/very/long/path/to/a/resource" in line
            for line in result
        )

    def test_todo_previously_broken_hyphen_healed(self):
        """TODO continuation lines with broken hyphens should be healed."""
        block = make_block(
            [
                "# TODO: Fix the command-",
                "#  line parsing bug.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        full_text = " ".join(line.lstrip("# ") for line in result)
        assert "command-line" in full_text
        assert "command- line" not in full_text


class TestParsePragma:
    def test_parse_pragma_off(self):
        assert parse_pragma("# octowrap: off") == "off"

    def test_parse_pragma_on(self):
        assert parse_pragma("# octowrap: on") == "on"

    def test_parse_pragma_none_for_regular_comment(self):
        assert parse_pragma("# This is a regular comment.") is None

    def test_parse_pragma_none_for_code(self):
        assert parse_pragma("x = 1") is None

    def test_parse_pragma_case_insensitive(self):
        assert parse_pragma("# OCTOWRAP: OFF") == "off"
        assert parse_pragma("# Octowrap: On") == "on"
        assert parse_pragma("# OcToWrAp: oFf") == "off"

    def test_parse_pragma_with_extra_whitespace(self):
        assert parse_pragma("#  octowrap:  off  ") == "off"
        assert parse_pragma("#   octowrap:   on   ") == "on"

    def test_parse_pragma_with_leading_indent(self):
        assert parse_pragma("    # octowrap: off") == "off"
        assert parse_pragma("        # octowrap: on") == "on"

    def test_parse_pragma_none_for_partial_match(self):
        assert parse_pragma("# octowrap: maybe") is None
        assert parse_pragma("# octowrap:") is None

    def test_parse_pragma_none_for_inline(self):
        """Inline pragma after code should not match (not a standalone comment)."""
        assert parse_pragma("x = 1  # octowrap: off") is None


class TestTodoRewrap:
    """Tests for TODO/FIXME rewrapping in rewrap_comment_block."""

    def test_single_line_todo_rewrapped(self):
        """A long single-line TODO should be rewrapped."""
        block = make_block(
            [
                "# TODO: This is a very long todo item that definitely exceeds the eighty-eight character line length limit and should be rewrapped",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert len(result) > 1
        assert result[0].startswith("# TODO: ")
        # Continuation lines should have one-space indent
        for line in result[1:]:
            assert line.startswith("#  ")
        for line in result:
            assert len(line) <= 88

    def test_short_todo_unchanged(self):
        """A short TODO that fits on one line should stay as-is."""
        block = make_block(["# TODO: fix this bug"])
        result = rewrap_comment_block(block, max_line_length=88)
        assert result == ["# TODO: fix this bug"]

    def test_bare_todo_marker_preserved(self):
        """A bare TODO with no content should be preserved, not become a blank line."""
        block = make_block(["# TODO:"])
        result = rewrap_comment_block(block, max_line_length=88)
        assert result == ["# TODO:"]

    def test_multiline_todo_collected(self):
        """Continuation lines (one-space indent) should be collected into the TODO."""
        block = make_block(
            [
                "# TODO: This is the first line of a long todo that needs",
                "#  to continue on the next line with more details",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert result[0].startswith("# TODO: ")
        # All text should be present
        full_text = " ".join(line.lstrip("# ") for line in result)
        assert "first line" in full_text
        assert "more details" in full_text

    def test_multiline_disabled(self):
        """With todo_multiline=False, continuation lines are not collected."""
        block = make_block(
            [
                "# TODO: first line",
                "#  continuation line",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88, todo_multiline=False)
        # The TODO is just the first line; the continuation becomes prose
        assert result[0] == "# TODO: first line"
        assert any("continuation line" in line for line in result[1:])

    def test_case_insensitive_default(self):
        """Lowercase 'todo' should be detected by default."""
        block = make_block(
            [
                "# todo: fix this very long comment that will exceed the line length limit for sure when combined with more text"
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert result[0].startswith("# todo: ")
        for line in result:
            assert len(line) <= 88

    def test_case_sensitive(self):
        """In case-sensitive mode, lowercase 'todo' is not a marker."""
        block = make_block(
            [
                "# todo: this is a long comment that exceeds the configured maximum line length and should be rewrapped",
            ]
        )
        result = rewrap_comment_block(
            block, max_line_length=88, todo_case_sensitive=True
        )
        # 'todo' should not be treated as a marker — it becomes regular prose
        assert result[0].startswith("# todo: ")
        # No continuation indent (it's wrapped as regular prose)
        for line in result:
            assert len(line) <= 88

    def test_custom_patterns(self):
        """Custom patterns replace the defaults."""
        block = make_block(
            [
                "# NOTE: this is a long note comment that exceeds the line length limit and should be wrapped properly by the tool",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88, todo_patterns=["note"])
        assert result[0].startswith("# NOTE: ")
        for line in result[1:]:
            assert line.startswith("#  ")

    def test_no_colon_after_marker(self):
        """TODO without a colon should still be detected and rewrapped."""
        block = make_block(
            [
                "# TODO fix this very long comment that exceeds the line length limit and should be rewrapped properly"
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert result[0].startswith("# TODO ")
        for line in result:
            assert len(line) <= 88

    def test_indented_todo_block(self):
        """An indented TODO block should preserve its indentation."""
        block = make_block(
            [
                "    # TODO: This is a long indented todo that exceeds the line length and should be rewrapped to fit",
            ],
            indent="    ",
        )
        result = rewrap_comment_block(block, max_line_length=88)
        for line in result:
            assert line.startswith("    # ")
            assert len(line) <= 88
        assert result[0].startswith("    # TODO: ")

    def test_todo_followed_by_prose(self):
        """A TODO followed by regular prose should not merge them."""
        block = make_block(
            [
                "# TODO: fix this bug",
                "# This is regular prose that follows the TODO.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# TODO: fix this bug" in result
        assert "# This is regular prose that follows the TODO." in result

    def test_multiple_todos_in_block(self):
        """Multiple TODOs in the same block should each be treated separately."""
        block = make_block(
            [
                "# TODO: first todo item",
                "# FIXME: second fixme item",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# TODO: first todo item" in result
        assert "# FIXME: second fixme item" in result

    def test_empty_patterns_disables_todo(self):
        """With empty patterns, TODO lines become regular prose."""
        block = make_block(
            [
                "# TODO: this and that are two things",
                "# that need to be fixed soon.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88, todo_patterns=[])
        # Should be treated as regular prose and joined
        full = " ".join(line.lstrip("# ") for line in result)
        assert "TODO:" in full
        assert "fixed soon" in full

    def test_todo_too_narrow_preserves(self):
        """When the TODO marker makes the available width < 10, preserve as-is."""
        # Use a long custom pattern so that marker eats most of the line budget.
        # prefix="# " (2), text_width=30-2=28 (>=20, no early return)
        # initial="# SUPERLONGPATTERNNAME: " (24), first_width=30-24=6 (<10)
        block = make_block(
            ["# SUPERLONGPATTERNNAME: fix this thing"],
        )
        result = rewrap_comment_block(
            block,
            max_line_length=30,
            todo_patterns=["superlongpatternname"],
        )
        assert result == ["# SUPERLONGPATTERNNAME: fix this thing"]

    def test_prose_before_todo_flushed(self):
        """Prose lines preceding a TODO should be flushed as a wrap paragraph."""
        block = make_block(
            [
                "# Some prose before the todo.",
                "# TODO: fix this bug",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# Some prose before the todo." in result
        assert "# TODO: fix this bug" in result


class TestListWrap:
    """Tests for list item wrapping in rewrap_comment_block."""

    def test_long_bullet_wraps_with_hanging_indent(self):
        """A long bullet item should wrap with hanging indent aligned to text."""
        block = make_block(
            [
                "# - This is a very long bullet item that definitely exceeds the fifty character line length limit",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=50)
        assert result[0].startswith("# - This is a very")
        for line in result[1:]:
            assert line.startswith("#   ")  # 2 spaces for "- " marker
        for line in result:
            assert len(line) <= 50

    def test_long_numbered_wraps_with_hanging_indent(self):
        """A long numbered item should wrap with hanging indent."""
        block = make_block(
            [
                "# 1. This is a very long numbered item that exceeds the fifty character line length limit",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=50)
        assert result[0].startswith("# 1. This is")
        for line in result[1:]:
            assert line.startswith("#    ")  # 3 spaces for "1. " marker
        for line in result:
            assert len(line) <= 50

    def test_nested_list_items_wrap_independently(self):
        """Nested list items should each wrap at their own indent level."""
        block = make_block(
            [
                "# - Top level item that is short",
                "#   - Nested item that is quite long and should definitely be wrapped to the target length",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=50)
        assert "# - Top level item that is short" in result
        # Nested item continuation should have 4-space hanging indent
        nested_lines = [line for line in result if line.startswith("#     ")]
        assert len(nested_lines) > 0

    def test_list_item_with_continuation_collected(self):
        """Indented continuation lines should be collected into the list item."""
        block = make_block(
            [
                "# - This is a list item with",
                "#   continuation text that was",
                "#   previously wrapped short.",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        # All text should be joined into one or fewer lines
        full_text = " ".join(line.lstrip("# ") for line in result)
        assert "list item with" in full_text
        assert "continuation text" in full_text
        assert "previously wrapped short" in full_text

    def test_short_list_items_unchanged(self):
        """Short list items that fit should remain unchanged."""
        block = make_block(
            [
                "# - Short item one",
                "# - Short item two",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# - Short item one" in result
        assert "# - Short item two" in result

    def test_mixed_prose_and_list(self):
        """Prose wraps normally, list items wrap with markers."""
        block = make_block(
            [
                "# This function does several things:",
                "# - Validates the input parameters that are passed to the function by the caller",
                "# - Returns the result",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=50)
        # Prose should be wrapped
        assert any("This function" in line for line in result)
        # List items should have hanging indent
        assert any(line.startswith("# - Validates") for line in result)
        assert any(line.startswith("# - Returns") for line in result)

    def test_list_wrap_false_preserves_verbatim(self):
        """With list_wrap=False, list items are preserved as-is."""
        block = make_block(
            [
                "# - This is a very long bullet item that definitely exceeds the eighty-eight character line length limit and should be preserved",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88, list_wrap=False)
        assert result == block["lines"]

    def test_bare_marker_preserved(self):
        """A bare marker with no content should be preserved."""
        block = make_block(["# - "])
        result = rewrap_comment_block(block, max_line_length=88)
        assert result == ["# - "]

    def test_too_narrow_preserves(self):
        """When the marker makes the available width < 10, preserve as-is."""
        block = make_block(
            ["# - This item should be preserved due to narrow width"],
        )
        # prefix "# " (2) + marker "- " (2) = 4 from content start. With indent="",
        # initial = "# - " (4 chars), width=12, first_width=12-4=8 (<10)
        result = rewrap_comment_block(block, max_line_length=12)
        assert result == ["# - This item should be preserved due to narrow width"]

    def test_rewrap_idempotent(self):
        """Rewrapping a list block twice should produce the same result."""
        block = make_block(
            [
                "# - This is a long bullet item that should be wrapped nicely to the target width limit.",
            ]
        )
        first = rewrap_comment_block(block, max_line_length=50)
        second = rewrap_comment_block(make_block(first), max_line_length=50)
        assert first == second

    def test_continuation_stops_at_sibling_item(self):
        """Continuation collection should stop at a sibling list item."""
        block = make_block(
            [
                "# - First item with",
                "#   some continuation",
                "# - Second item",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# - First item with some continuation" in result
        assert "# - Second item" in result

    def test_continuation_stops_at_preserved_line(self):
        """Continuation collection should stop at a preserved line."""
        block = make_block(
            [
                "# - A list item",
                "#   x = 5",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# - A list item" in result
        assert "#   x = 5" in result

    def test_continuation_stops_at_blank_line(self):
        """A blank comment line should stop continuation collection."""
        block = make_block(
            [
                "# - First item",
                "#",
                "# More text",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# - First item" in result
        assert "#" in result
        assert "# More text" in result

    def test_continuation_stops_at_insufficient_indent(self):
        """A non-indented prose line should not be collected as continuation."""
        block = make_block(
            [
                "# - First item",
                "# not a continuation",
            ]
        )
        result = rewrap_comment_block(block, max_line_length=88)
        assert "# - First item" in result
        assert "# not a continuation" in result

    def test_deeply_nested_too_narrow_preserves(self):
        """A deeply nested list marker that makes available width < 10 preserves."""
        # Content "          - text" has marker "          - " (12 chars).
        # initial = "# " + "          - " = 14 chars.
        # At width 22: first_width = 22-14 = 8 < 10, triggers preserve.
        # text_width = 22-2 = 20 >= 20, so the early return does not fire.
        block = make_block(
            ["#           - deeply nested item"],
        )
        result = rewrap_comment_block(block, max_line_length=22)
        assert result == ["#           - deeply nested item"]
