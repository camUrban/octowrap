import pytest

from octowrap.rewrap import (
    _join_comment_lines,
    extract_todo_marker,
    is_divider,
    is_likely_code,
    is_list_item,
    is_todo_continuation,
    is_todo_marker,
    is_tool_directive,
    should_preserve_line,
)


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
        ],
        ids=[
            "dash",
            "star",
            "bullet",
            "num_dot",
            "num_paren",
            "letter_dot",
            "letter_paren",
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
            "TODO: fix this",
            "FIXME: broken",
            "NOTE: important",
            "XXX: needs work",
            "HACK: temporary",
        ],
    )
    def test_rejects_non_list(self, text):
        assert not is_list_item(text)


class TestIsToolDirective:
    @pytest.mark.parametrize(
        "text",
        [
            "type: ignore",
            "type: ignore[assignment]",
            "type: int",
            "noqa",
            "noqa: E501",
            "noqa: E501,W503",
            "pragma: no cover",
            "pragma: no branch",
            "fmt: off",
            "fmt: on",
            "fmt: skip",
            "isort: skip",
            "isort: skip_file",
            "isort: split",
            "pylint: disable=C0114",
            "pylint: enable=C0114",
            "mypy: ignore-errors",
            "mypy: disable-error-code",
            "pyright: reportGeneralTypeIssues=false",
            "ruff: noqa: F401",
        ],
        ids=[
            "type_ignore",
            "type_ignore_code",
            "type_int",
            "noqa",
            "noqa_code",
            "noqa_multi",
            "pragma_no_cover",
            "pragma_no_branch",
            "fmt_off",
            "fmt_on",
            "fmt_skip",
            "isort_skip",
            "isort_skip_file",
            "isort_split",
            "pylint_disable",
            "pylint_enable",
            "mypy_ignore",
            "mypy_disable",
            "pyright_report",
            "ruff_noqa",
        ],
    )
    def test_detects_directives(self, text):
        assert is_tool_directive(text)

    # fmt: off
    @pytest.mark.parametrize(
        "text",
        [
            "This is a regular comment.",
            "The type is important here.",
            "Use fmt to format the code.",
            "",
        ],
        ids=["prose", "contains_type", "contains_fmt", "empty"],
    )
    # fmt: on
    def test_rejects_non_directives(self, text):
        assert not is_tool_directive(text)


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

    def test_tool_directive_not_preserved(self):
        """should_preserve_line does NOT check is_tool_directive; that's handled
        separately in rewrap_comment_block."""
        assert not should_preserve_line("type: ignore")


class TestIsTodoMarker:
    """Tests for is_todo_marker()."""

    @pytest.mark.parametrize(
        "text",
        [
            "TODO fix this",
            "TODO: fix this",
            "todo fix this",
            "Todo: fix this",
            "FIXME broken",
            "FIXME: broken",
            "fixme broken",
        ],
        ids=[
            "TODO_no_colon",
            "TODO_colon",
            "todo_lower",
            "Todo_mixed",
            "FIXME_no_colon",
            "FIXME_colon",
            "fixme_lower",
        ],
    )
    def test_detects_default_patterns(self, text):
        assert is_todo_marker(text)

    def test_word_boundary(self):
        """'TODOLIST' should not match 'todo' pattern."""
        assert not is_todo_marker("TODOLIST something")

    def test_rejects_non_starters(self):
        """Text that doesn't start with a pattern should not match."""
        assert not is_todo_marker("This is a TODO item")

    def test_rejects_continuation_line(self):
        """A line with leading space is not a marker (it's a continuation)."""
        assert not is_todo_marker(" continue the todo")

    def test_rejects_non_default_markers(self):
        """NOTE/XXX/HACK are not in the default patterns."""
        assert not is_todo_marker("NOTE: important")
        assert not is_todo_marker("XXX: needs work")
        assert not is_todo_marker("HACK: temporary")

    def test_custom_patterns(self):
        assert is_todo_marker("NOTE important", patterns=["note"])
        assert is_todo_marker("WARN: something", patterns=["warn", "note"])

    def test_custom_patterns_replaces_defaults(self):
        """Custom patterns completely replace defaults."""
        assert not is_todo_marker("TODO fix this", patterns=["note"])

    def test_case_sensitive(self):
        assert is_todo_marker("TODO fix", patterns=["TODO"], case_sensitive=True)
        assert not is_todo_marker("todo fix", patterns=["TODO"], case_sensitive=True)
        assert not is_todo_marker("Todo fix", patterns=["TODO"], case_sensitive=True)
        # Default lowercase patterns only match lowercase in case-sensitive mode
        assert is_todo_marker("todo fix", case_sensitive=True)
        assert not is_todo_marker("TODO fix", case_sensitive=True)

    def test_empty_patterns_disables(self):
        """Empty pattern list disables detection entirely."""
        assert not is_todo_marker("TODO fix this", patterns=[])

    def test_leading_whitespace_stripped(self):
        """Leading whitespace on the content is okay for markers."""
        assert is_todo_marker("  TODO fix", patterns=["todo"])


class TestIsTodoContinuation:
    """Tests for is_todo_continuation()."""

    def test_one_space_with_content(self):
        assert is_todo_continuation(" continue this")

    def test_one_space_with_word(self):
        assert is_todo_continuation(" x")

    def test_no_leading_space(self):
        assert not is_todo_continuation("no leading space")

    def test_two_spaces(self):
        assert not is_todo_continuation("  two spaces")

    def test_only_space(self):
        """A single space with no content is not a continuation."""
        assert not is_todo_continuation(" ")

    def test_empty_string(self):
        assert not is_todo_continuation("")

    def test_tab_not_space(self):
        assert not is_todo_continuation("\tcontent")


class TestExtractTodoMarker:
    """Tests for extract_todo_marker()."""

    def test_todo_with_colon(self):
        marker, content = extract_todo_marker("TODO: fix the bug")
        assert marker == "TODO: "
        assert content == "fix the bug"

    def test_todo_without_colon(self):
        marker, content = extract_todo_marker("TODO fix the bug")
        assert marker == "TODO "
        assert content == "fix the bug"

    def test_fixme_with_colon(self):
        marker, content = extract_todo_marker("FIXME: broken thing")
        assert marker == "FIXME: "
        assert content == "broken thing"

    def test_case_insensitive_default(self):
        marker, content = extract_todo_marker("todo: something")
        assert marker == "todo: "
        assert content == "something"

    def test_case_sensitive(self):
        marker, content = extract_todo_marker(
            "TODO: fix", patterns=["TODO"], case_sensitive=True
        )
        assert marker == "TODO: "
        assert content == "fix"

    def test_case_sensitive_no_match(self):
        """Lowercase 'todo' should not match uppercase pattern in case-sensitive mode."""
        marker, content = extract_todo_marker(
            "todo: fix", patterns=["TODO"], case_sensitive=True
        )
        assert marker == ""
        assert content == "todo: fix"

    def test_no_match(self):
        marker, content = extract_todo_marker("Regular comment text")
        assert marker == ""
        assert content == "Regular comment text"

    def test_custom_patterns(self):
        marker, content = extract_todo_marker("NOTE: important", patterns=["note"])
        assert marker == "NOTE: "
        assert content == "important"

    def test_extra_whitespace_after_colon(self):
        marker, content = extract_todo_marker("TODO:  extra spaces")
        assert marker == "TODO:  "
        assert content == "extra spaces"

    def test_no_content_after_marker(self):
        marker, content = extract_todo_marker("TODO:")
        assert marker == "TODO:"
        assert content == ""

    def test_preserves_leading_whitespace(self):
        marker, content = extract_todo_marker("  TODO: fix")
        assert marker == "  TODO: "
        assert content == "fix"


class TestJoinCommentLines:
    """Tests for _join_comment_lines hyphen-aware joining."""

    def test_empty_list(self):
        assert _join_comment_lines([]) == ""

    def test_single_line(self):
        assert _join_comment_lines(["hello world"]) == "hello world"

    def test_normal_join(self):
        assert _join_comment_lines(["hello", "world"]) == "hello world"

    def test_heals_broken_hyphenated_word(self):
        assert _join_comment_lines(["re-", "validate"]) == "re-validate"

    def test_heals_midsentence_hyphen_break(self):
        result = _join_comment_lines(["some text re-", "validate the input"])
        assert result == "some text re-validate the input"

    def test_standalone_hyphen_not_healed(self):
        """A line ending with ' -' (standalone hyphen) should not heal."""
        assert _join_comment_lines(["use the -", "v flag"]) == "use the - v flag"

    def test_double_hyphen_not_healed(self):
        """A line ending with '--' should not heal (not letter-hyphen)."""
        assert _join_comment_lines(["use --", "verbose"]) == "use -- verbose"

    def test_hyphen_before_non_alpha(self):
        """A line ending with letter-hyphen before a digit should not heal."""
        assert _join_comment_lines(["phase-", "2 begins"]) == "phase- 2 begins"

    def test_multiple_lines_mixed(self):
        result = _join_comment_lines(["command-", "line-", "interface is great"])
        assert result == "command-line-interface is great"

    def test_no_heal_when_next_line_starts_with_space(self):
        """Next line starting with space should not trigger healing."""
        assert _join_comment_lines(["re-", " validate"]) == "re-  validate"
