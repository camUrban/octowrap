from octowrap.rewrap import (
    _should_extract_inline,
    count_changed_blocks,
    extract_inline_comment,
    find_inline_comment,
    process_content,
    process_file,
)


class TestFindInlineComment:
    """Tests for find_inline_comment()."""

    def test_simple_inline(self):
        assert find_inline_comment("x = 1  # comment") == 7

    def test_no_hash(self):
        assert find_inline_comment("x = 1") is None

    def test_full_line_comment(self):
        assert find_inline_comment("# full line comment") is None

    def test_indented_full_line_comment(self):
        assert find_inline_comment("    # indented full line") is None

    def test_hash_in_single_quoted_string(self):
        assert find_inline_comment("x = 'has # hash'") is None

    def test_hash_in_double_quoted_string(self):
        assert find_inline_comment('x = "has # hash"') is None

    def test_hash_in_triple_single_quoted_string(self):
        assert find_inline_comment("x = '''has # hash'''") is None

    def test_hash_in_triple_double_quoted_string(self):
        assert find_inline_comment('x = """has # hash"""') is None

    def test_hash_after_string_with_hash(self):
        result = find_inline_comment("x = 'has # hash'  # real comment")
        assert result == 18

    def test_escaped_quote_in_string(self):
        assert find_inline_comment(r"x = 'it\'s # here'") is None

    def test_escaped_quote_then_inline(self):
        result = find_inline_comment(r"x = 'it\'s fine'  # comment")
        assert result is not None

    def test_multiple_hashes_returns_first_outside_string(self):
        result = find_inline_comment("x = 1  # first # second")
        assert result == 7

    def test_empty_line(self):
        assert find_inline_comment("") is None

    def test_whitespace_only(self):
        assert find_inline_comment("   ") is None

    def test_code_with_no_comment(self):
        assert find_inline_comment("def foo(bar):") is None


class TestExtractInlineComment:
    """Tests for extract_inline_comment()."""

    def test_basic_extraction(self):
        result = extract_inline_comment("x = 1  # a comment")
        assert result is not None
        code, text = result
        assert code == "x = 1"
        assert text == "a comment"

    def test_no_inline_comment(self):
        assert extract_inline_comment("x = 1") is None

    def test_full_line_comment(self):
        assert extract_inline_comment("# full line") is None

    def test_strips_trailing_whitespace_from_code(self):
        result = extract_inline_comment("x = 1    # comment")
        assert result is not None
        code, _ = result
        assert code == "x = 1"
        assert not code.endswith(" ")

    def test_no_space_after_hash(self):
        result = extract_inline_comment("x = 1  #comment")
        assert result is not None
        _, text = result
        assert text == "comment"

    def test_preserves_comment_content(self):
        result = extract_inline_comment("x = 1  # type: ignore[assignment]")
        assert result is not None
        _, text = result
        assert text == "type: ignore[assignment]"

    def test_string_with_hash(self):
        assert extract_inline_comment("x = 'foo # bar'") is None

    def test_indented_code(self):
        result = extract_inline_comment("    x = 1  # indented")
        assert result is not None
        code, text = result
        assert code == "    x = 1"
        assert text == "indented"


class TestProcessContentInline:
    """Integration tests for inline comment extraction through process_content()."""

    def test_short_line_unchanged(self):
        """Lines within the limit are not touched."""
        content = "x = 1  # short\n"
        changed, result = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_long_line_extracted(self):
        """An overflowing inline comment is extracted above the code."""
        content = "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit and needs to be extracted\n"
        changed, result = process_content(content, max_line_length=88)
        assert changed
        lines = result.splitlines()
        # Comment should be above the code
        assert lines[0].startswith("# This comment pushes")
        # Code line should be last, without the comment
        assert lines[-1] == "x = some_really_long_function_call(arg1, arg2)"

    def test_tool_directive_preserved(self):
        """type: ignore and other directives are never extracted."""
        # Build a line that overflows but has a tool directive
        code = "x" * 80
        content = f"{code}  # type: ignore[assignment]\n"
        changed, result = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_noqa_preserved(self):
        """noqa directives are never extracted."""
        code = "x" * 80
        content = f"{code}  # noqa: E501\n"
        changed, result = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_pragma_off_region_preserved(self):
        """Inline comments in pragma-off regions are not extracted."""
        content = (
            "# octowrap: off\n"
            "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        )
        changed, result = process_content(content, max_line_length=88)
        assert not changed
        assert result == content

    def test_indented_code(self):
        """Indented code gets the comment extracted at the correct indent."""
        content = "    x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit and needs extraction\n"
        changed, result = process_content(content, max_line_length=88)
        assert changed
        lines = result.splitlines()
        # The comment should use the same indentation
        assert lines[0].startswith("    # This comment pushes")
        # Code line should be indented too
        assert lines[-1].startswith("    x = ")

    def test_idempotency(self):
        """Running twice produces the same output."""
        content = "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit and needs to be extracted\n"
        _, result1 = process_content(content, max_line_length=88)
        changed, result2 = process_content(result1, max_line_length=88)
        assert not changed
        assert result2 == result1

    def test_inline_disabled(self):
        """When inline=False, overflowing inline comments are left alone."""
        content = "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        changed, result = process_content(content, max_line_length=88, inline=False)
        assert not changed
        assert result == content

    def test_extracted_todo_wrapped_with_marker(self):
        """An extracted TODO comment uses TODO marker wrapping."""
        content = "x = some_really_long_function_call(arg1, arg2)  # TODO: This is a very long todo that exceeds the eighty-eight character line length limit and needs extraction\n"
        changed, result = process_content(content, max_line_length=88)
        assert changed
        lines = result.splitlines()
        assert lines[0].startswith("# TODO: ")
        # Continuation uses one-space indent
        if len(lines) > 2:
            assert lines[1].startswith("#  ")

    def test_multiple_inline_comments(self):
        """Multiple overflowing lines are each extracted independently."""
        content = (
            "x = some_really_long_function_call(arg1, arg2)  # First comment pushes the line way past the limit\n"
            "y = another_really_long_function(arg3, arg4)  # Second comment also pushes the line way past the limit\n"
        )
        changed, result = process_content(content, max_line_length=88)
        assert changed
        assert "# First comment" in result
        assert "# Second comment" in result

    def test_code_without_inline_untouched(self):
        """Long code lines without inline comments are not modified."""
        content = "x = some_really_long_function_call(arg1, arg2, arg3, arg4, arg5, arg6, arg7, arg8, arg9)\n"
        changed, result = process_content(content, max_line_length=88)
        assert not changed

    def test_extracted_comment_wraps_to_line_length(self):
        """The extracted comment block respects max_line_length."""
        content = "x = func()  # This is a really long inline comment that definitely exceeds the forty character limit when extracted\n"
        changed, result = process_content(content, max_line_length=40)
        assert changed
        lines = result.splitlines()
        comment_lines = [ln for ln in lines if ln.startswith("#")]
        assert all(len(ln) <= 40 for ln in comment_lines)


class TestCountChangedBlocksInline:
    """Tests for count_changed_blocks() with inline comment counting."""

    def test_counts_extractable_inline(self):
        content = "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 1

    def test_does_not_count_short_inline(self):
        content = "x = 1  # short\n"
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 0

    def test_does_not_count_tool_directive(self):
        code = "x" * 80
        content = f"{code}  # type: ignore\n"
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 0

    def test_inline_disabled(self):
        content = "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        count = count_changed_blocks(content, max_line_length=88, inline=False)
        assert count == 0

    def test_pragma_off_not_counted(self):
        content = (
            "# octowrap: off\n"
            "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        )
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 0

    def test_counts_both_blocks_and_inline(self):
        """Both comment blocks and inline comments contribute to the count."""
        content = (
            "# This is a comment that was wrapped\n"
            "# at a short width previously.\n"
            "x = some_really_long_function_call(arg1, arg2)  # This comment pushes the line way past the limit\n"
        )
        count = count_changed_blocks(content, max_line_length=88)
        assert count == 2


class TestShouldExtractInline:
    """Direct tests for _should_extract_inline()."""

    def test_long_line_no_comment(self):
        """A long code line with no '#' at all returns False."""
        line = "x = " + "a" * 90
        assert len(line) > 88
        assert _should_extract_inline(line, 88) is False

    def test_long_line_hash_only_in_string(self):
        """A long line where '#' is only inside a string returns False."""
        line = "x = '" + "#" * 90 + "'"
        assert len(line) > 88
        assert _should_extract_inline(line, 88) is False


# fmt: off
INLINE_CONTENT = (
    b"x = some_really_long_function_call(arg1, arg2)"
    b"  # This comment pushes the line way past the limit\n"
)
TWO_INLINE_CONTENT = (
    b"x = some_really_long_function_call(arg1, arg2)"
    b"  # First comment pushes the line way past the limit\n"
    b"y = another_really_long_function_call(arg3, arg4)"
    b"  # Second comment pushes the line way past the limit\n"
)
# fmt: on


class TestInlineInteractive:
    """Tests for the interactive mode branches of inline comment extraction."""

    def test_accept(self, tmp_path, monkeypatch):
        """Accepting an inline extraction applies the change."""
        f = tmp_path / "t.py"
        f.write_bytes(INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "a")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# This comment pushes" in content
        assert content.rstrip().endswith(
            "x = some_really_long_function_call(arg1, arg2)"
        )

    def test_accept_all(self, tmp_path, monkeypatch):
        """Accept-all applies extraction to current and all remaining inline comments."""
        f = tmp_path / "t.py"
        f.write_bytes(TWO_INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "A")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# First comment" in content
        assert "# Second comment" in content

    def test_accept_all_skips_prompting(self, tmp_path, monkeypatch):
        """After accept-all, prompt_user is not called for subsequent inline comments."""
        f = tmp_path / "t.py"
        f.write_bytes(TWO_INLINE_CONTENT)
        call_count = 0

        def counting_prompt():
            nonlocal call_count
            call_count += 1
            return "A"

        monkeypatch.setattr("octowrap.rewrap.prompt_user", counting_prompt)
        process_file(f, max_line_length=88, interactive=True)
        assert call_count == 1

    def test_skip(self, tmp_path, monkeypatch):
        """Skipping keeps the original inline comment in place."""
        f = tmp_path / "t.py"
        f.write_bytes(INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "s")
        changed, _ = process_file(f, max_line_length=88, interactive=True)
        assert not changed

    def test_exclude(self, tmp_path, monkeypatch):
        """Excluding wraps the line with octowrap: off/on pragmas."""
        f = tmp_path / "t.py"
        f.write_bytes(INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "e")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# octowrap: off" in content
        assert "# octowrap: on" in content

    def test_flag(self, tmp_path, monkeypatch):
        """Flagging inserts a FIXME comment and preserves the original line."""
        f = tmp_path / "t.py"
        f.write_bytes(INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "f")
        changed, content = process_file(f, max_line_length=88, interactive=True)
        assert changed
        assert "# FIXME: Manually fix the below comment" in content
        # Original line should be preserved below the FIXME
        assert "# This comment pushes the line way past the limit" in content

    def test_quit(self, tmp_path, monkeypatch):
        """Quitting preserves the original line and sets quit state."""
        f = tmp_path / "t.py"
        f.write_bytes(TWO_INLINE_CONTENT)
        state: dict = {}
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
        changed, _ = process_file(f, max_line_length=88, interactive=True, _state=state)
        assert not changed
        assert state.get("quit") is True

    def test_quit_stops_remaining(self, tmp_path, monkeypatch, capsys):
        """After quitting, no further diffs are shown for remaining inline comments."""
        f = tmp_path / "t.py"
        f.write_bytes(TWO_INLINE_CONTENT)
        monkeypatch.setattr("octowrap.rewrap.prompt_user", lambda: "q")
        monkeypatch.setattr("octowrap.rewrap._USE_COLOR", False)
        process_file(f, max_line_length=88, interactive=True)
        out = capsys.readouterr().out
        assert "First comment" in out
        assert "Second comment" not in out
