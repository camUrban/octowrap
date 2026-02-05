import pytest

from octowrap.rewrap import (is_divider, is_likely_code, is_list_item,
                             should_preserve_line)


class TestIsLikelyCode:
    @pytest.mark.parametrize(
        "text",
        [
            "x = 5",
            "my_var = 'hello'",
            "def foo():",
            "class MyClass:",
            "import os",
            "from pathlib import Path",
            "if x > 0:",
            "for item in items:",
            "while True:",
            "return result",
            "raise ValueError('bad')",
            "try:",
            "except Exception:",
            "with open('f') as fh:",
            "assert x == 5",
            "yield value",
            "lambda x: x + 1",
            "@decorator",
            "print('hello')",
            "self.value = 10",
            "obj.method(arg)",
            "foo(bar)",
        ],
        ids=[
            "assignment",
            "assignment_str",
            "def",
            "class",
            "import",
            "from_import",
            "if",
            "for",
            "while",
            "return",
            "raise",
            "try",
            "except",
            "with",
            "assert",
            "yield",
            "lambda",
            "decorator",
            "print",
            "self",
            "method_call",
            "function_call",
        ],
    )
    def test_detects_code(self, text):
        assert is_likely_code(text)

    @pytest.mark.parametrize(
        "text",
        [
            "This is a plain English comment.",
            "Fix the bug in the parser.",
            "See also: the docs for more info.",
            "",
        ],
    )
    def test_rejects_prose(self, text):
        assert not is_likely_code(text)


class TestIsDivider:
    @pytest.mark.parametrize(
        "text",
        [
            "----------",
            "==========",
            "~~~~~~~~~~",
            "##########",
            "**********",
        ],
    )
    def test_detects_dividers(self, text):
        assert is_divider(text)

    def test_rejects_short_divider(self):
        """Length < 4 should not count as a divider."""
        assert not is_divider("---")

    def test_minimum_length_divider(self):
        """Exactly 4 repeated chars should be detected."""
        assert is_divider("----")

    def test_rejects_prose(self):
        assert not is_divider("Hello world")

    def test_rejects_empty(self):
        assert not is_divider("")

    def test_mostly_repeated_with_some_variation(self):
        """70% threshold: '----x' is 4/5 = 80% dashes, should pass."""
        assert is_divider("----x")

    def test_below_repetition_threshold(self):
        """'--xx' is 2/4 = 50% for each char, below 70%."""
        assert not is_divider("--xx")


class TestIsListItem:
    @pytest.mark.parametrize(
        "text",
        [
            "- item one",
            "* starred item",
            "\u2022 bullet item",
            "1. numbered",
            "1) numbered paren",
            "a. lettered",
            "a) lettered paren",
            "TODO: fix this",
            "FIXME: broken",
            "NOTE: important",
            "XXX: needs work",
            "HACK: temporary",
        ],
        ids=[
            "dash",
            "star",
            "bullet",
            "num_dot",
            "num_paren",
            "letter_dot",
            "letter_paren",
            "TODO",
            "FIXME",
            "NOTE",
            "XXX",
            "HACK",
        ],
    )
    def test_detects_list_items(self, text):
        assert is_list_item(text)

    @pytest.mark.parametrize(
        "text",
        [
            "Just a sentence.",
            "This contains a - dash but is not a list.",
            "",
        ],
    )
    def test_rejects_non_list(self, text):
        assert not is_list_item(text)


class TestShouldPreserveLine:
    def test_blank_line(self):
        assert should_preserve_line("")
        assert should_preserve_line("   ")

    def test_code_line(self):
        assert should_preserve_line("x = 5")

    def test_divider_line(self):
        assert should_preserve_line("----------")

    def test_normal_prose(self):
        assert not should_preserve_line("This is a regular comment.")

    def test_list_item_not_preserved(self):
        """should_preserve_line does NOT check is_list_item; that's handled
        separately in rewrap_comment_block."""
        assert not should_preserve_line("- item one")
