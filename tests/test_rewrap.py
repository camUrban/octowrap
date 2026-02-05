from octowrap.rewrap import (
    is_divider,
    is_likely_code,
    is_list_item,
    parse_comment_blocks,
    rewrap_comment_block,
)


def test_is_likely_code():
    assert is_likely_code("x = 5")
    assert is_likely_code("def foo():")
    assert not is_likely_code("This is a plain comment.")


def test_is_divider():
    assert is_divider("----------")
    assert is_divider("==========")
    assert not is_divider("Hello world")


def test_is_list_item():
    assert is_list_item("- item one")
    assert is_list_item("TODO: fix this")
    assert not is_list_item("Just a sentence.")


def test_parse_comment_blocks():
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


def test_rewrap_short_lines():
    block = {
        "indent": "",
        "lines": ["# Short."],
    }
    result = rewrap_comment_block(block, max_line_length=88)
    assert result == ["# Short."]
