import octowrap.rewrap as mod
from octowrap.rewrap import colorize, prompt_user, show_block_diff


class TestColorize:
    def test_known_color(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("hello", "red")
        assert result == "\033[91mhello\033[0m"

    def test_bold(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("title", "bold")
        assert result == "\033[1mtitle\033[0m"

    def test_unknown_color_still_resets(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("text", "nonexistent")
        assert result == "text\033[0m"

    def test_empty_string(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", True)
        result = colorize("", "green")
        assert result == "\033[92m\033[0m"

    def test_disabled_returns_plain_text(self, monkeypatch):
        monkeypatch.setattr(mod, "_USE_COLOR", False)
        assert colorize("hello", "red") == "hello"
        assert colorize("title", "bold") == "title"
        assert colorize("", "green") == ""


class TestShowBlockDiff:
    def test_no_changes_returns_false(self, capsys):
        lines = ["# hello world"]
        assert show_block_diff(lines, lines, 0) is False
        assert capsys.readouterr().out == ""

    def test_changes_returns_true(self, capsys):
        original = ["# hello", "# world"]
        new = ["# hello world"]
        assert show_block_diff(original, new, 0) is True

    def test_output_contains_original_and_new(self, capsys):
        original = ["# old line"]
        new = ["# new line"]
        show_block_diff(original, new, 5)
        out = capsys.readouterr().out
        assert "- # old line" in out
        assert "+ # new line" in out

    def test_output_contains_line_numbers(self, capsys):
        original = ["# a"]
        new = ["# b"]
        show_block_diff(original, new, 9)
        out = capsys.readouterr().out
        # start_line is 0-indexed, display is 1-indexed
        assert "Lines 10-10:" in out


class TestPromptUser:
    def test_accept(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "a")
        assert prompt_user() == "a"

    def test_skip(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "s")
        assert prompt_user() == "s"

    def test_quit(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "q")
        assert prompt_user() == "q"

    def test_empty_defaults_to_skip(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert prompt_user() == "s"

    def test_uppercase_accepted(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "A")
        assert prompt_user() == "a"

    def test_invalid_then_valid(self, monkeypatch):
        responses = iter(["x", "z", "a"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        assert prompt_user() == "a"

    def test_eof_returns_quit(self, monkeypatch):
        def raise_eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        assert prompt_user() == "q"

    def test_keyboard_interrupt_returns_quit(self, monkeypatch):
        def raise_interrupt(_):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        assert prompt_user() == "q"
