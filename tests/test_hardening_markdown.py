"""Pins markdown render, chat bubble replace, inbound notice, and CLI consent."""
from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.orchestrator import _as_code_block
from arelis.ui.markdown import render_markdown

# The offscreen qt_app fixture now lives in tests/conftest.py, shared with the
# voice tests rather than defined twice.

# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def test_markdown_renders_the_marks_models_actually_emit() -> None:
    html = render_markdown("**Sources:**\n\n1. Example (https://example.com)")
    assert "<b>Sources:</b>" in html
    assert "**" not in html
    # Renderer may emit styled <ol style="..."> — bare '<ol>' is too strict.
    assert "<ol" in html
    assert 'href="https://example.com"' in html


def test_code_fence_becomes_preformatted_text() -> None:
    html = render_markdown("Try this:\n\n```python\nx = [1, 2]\n```")
    assert "<pre" in html
    assert "x = [1, 2]" in html
    assert "```" not in html


def test_html_in_model_output_is_escaped_not_executed() -> None:
    """Answers can quote a scraped page verbatim. An <img> surviving into the
    document would turn displaying an answer into a network request."""
    html = render_markdown('Look: <img src="http://tracker.example/p.gif"> and <b>raw</b>')
    assert "<img" not in html
    assert "&lt;img" in html
    assert "<b>raw</b>" not in html


def test_identifiers_with_underscores_are_not_italicised() -> None:
    """A coding assistant writes snake_case constantly. Treating the underscores
    as emphasis mangles every one of them."""
    html = render_markdown("Call tool_output_chars before max_rounds is reached.")
    assert "<i>" not in html
    assert "tool_output_chars" in html


def test_link_schemes_other_than_web_are_not_linkified() -> None:
    html = render_markdown("[click](javascript:alert(1))")
    assert "href" not in html
    assert "click" in html


def test_nested_lists_close_in_the_right_order() -> None:
    html = render_markdown("- outer\n  - inner\n- outer again")
    assert html.count("<ul") == 2
    assert "padding-left:16px" in html
    assert html.count("</ul>") == 2
    assert html.index("<li>inner</li>") < html.index("</ul>")


def test_tables_render_with_their_columns_aligned() -> None:
    html = render_markdown("| a | b |\n| --- | ---: |\n| 1 | 2 |")
    assert "<table" in html
    assert "<th" in html and "<td" in html
    assert "text-align:right" in html


def test_ragged_table_rows_do_not_shift_columns() -> None:
    html = render_markdown("| a | b | c |\n| --- | --- | --- |\n| 1 |")
    assert html.count("<td") == 3


def test_font_stack_does_not_break_the_style_attribute() -> None:
    """The theme's mono stack quotes each family with double quotes. Dropped
    straight into style="..." it closes the attribute and the rest of the
    declaration becomes stray tag junk."""
    html = render_markdown("```\nx = 1\n```")
    opening_tag = html[: html.index(">") + 1]
    assert opening_tag.count('"') == 2
    assert "font-family" in opening_tag


def test_inline_code_is_not_reinterpreted() -> None:
    html = render_markdown("Use `**not bold**` here.")
    assert "<b>" not in html
    assert "**not bold**" in html


def test_tex_math_flattens_in_the_bubble() -> None:
    html = render_markdown(r"$$\frac{x^{3}}{6} + 25x\log(x-3)$$")
    assert r"\frac" not in html
    assert r"\log" not in html
    assert "log" in html
    assert "x³" in html
    assert "text-align:center" in html


# --------------------------------------------------------------------------
# Chat panel: streaming draft, then the rendered answer
# --------------------------------------------------------------------------


def test_chat_replaces_the_streamed_draft_with_rendered_markdown(qt_app) -> None:
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("**bold** and ")
    panel.append_delta("`code`")
    panel.finish_assistant("**bold** and `code`")
    text = panel.view.toPlainText()
    assert "**bold**" not in text
    assert "bold" in text and "code" in text


def test_discarded_stream_leaves_the_document_untouched(qt_app) -> None:
    """The retract path. If the anchor is off by a character the previous
    message loses its last letter, which is how this would show up."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.add_user("what is in this folder?")
    before = panel.view.toPlainText()
    panel.begin_assistant()
    panel.append_delta("Let me open that folder for you")
    panel.discard_stream()
    assert panel.view.toPlainText() == before


def test_inbound_notice_waits_until_the_assistant_bubble_closes(qt_app) -> None:
    """Inbound SMS must not concatenate into an unrelated streaming answer."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("Let's sketch the visualization interface.")
    panel.add_system("Text from Robin Hale: Bro that man is SSG")
    assert "Bro that man is SSG" not in panel.view.toPlainText()
    panel.finish_assistant("Let's sketch the visualization interface.")
    text = panel.view.toPlainText()
    assert "visualization interface" in text
    assert "Bro that man is SSG" in text
    assert text.index("visualization") < text.index("Bro that man is SSG")


def test_answer_delivered_without_streaming_is_still_rendered(qt_app) -> None:
    """Slash commands and /help arrive as one ASSISTANT_DONE with no deltas."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.finish_assistant("# Heading\n\n- one\n- two")
    text = panel.view.toPlainText()
    assert "#" not in text
    assert "Heading" in text and "one" in text


def test_user_text_is_shown_exactly_as_typed(qt_app) -> None:
    """Rendering the user's own message hides what they sent, which matters most
    for slash commands where the literal characters are the point."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.add_user("/workspace action=read path=**notes**.md")
    assert "**notes**.md" in panel.view.toPlainText()


def test_long_transcript_load_keeps_markdown_stable(qt_app) -> None:
    """L2 soak: History reload of a long mixed thread must not leave raw marks."""
    from arelis.ui.panels.chat import ChatPanel

    messages: list[dict[str, str]] = []
    for i in range(40):
        messages.append({"role": "user", "content": f"turn {i} ask about **item {i}**"})
        messages.append(
            {
                "role": "assistant",
                "content": (
                    f"## Answer {i}\n\n"
                    f"- point one for {i}\n"
                    f"- point two\n\n"
                    f"Use `code_{i}` and a fence:\n\n"
                    f"```python\nprint({i})\n```\n\n"
                    f"**Sources:**\n\n"
                    f"1. Example (https://example.com/{i})"
                ),
            }
        )
    panel = ChatPanel()
    panel.load_messages(messages)
    text = panel.view.toPlainText()
    assert text.count("you") >= 40
    assert text.count("arelis") >= 40
    assert "Answer 0" in text and "Answer 39" in text
    assert "print(39)" in text
    # Rendered: markdown markers should not litter the surface.
    assert "**Sources:**" not in text
    assert "```" not in text
    assert "## Answer" not in text
    html = panel.view.toHtml()
    assert "https://example.com/39" in html
    # Live stream + finish on top of a long loaded thread still paints cleanly.
    panel.add_user("one more")
    panel.begin_assistant()
    panel.append_delta("partial **bold**")
    panel.finish_assistant("final **bold** and `x`\n\n- ok")
    live = panel.view.toPlainText()
    assert "one more" in live
    assert "**bold**" not in live
    assert "final" in live and "bold" in live


# --------------------------------------------------------------------------
# Slash command output and the CLI confirm gate
# --------------------------------------------------------------------------


def test_tool_output_is_fenced_past_its_own_backticks() -> None:
    """Reading a markdown file that contains a fence would otherwise close the
    block early and spill the rest of the file into the chat as prose."""
    block = _as_code_block("text\n```\ninner\n```\ndone")
    assert block.startswith("````")
    assert block.endswith("````")


def test_plain_tool_output_uses_a_normal_fence() -> None:
    assert _as_code_block("[dir] arelis").startswith("```\n")


@pytest.mark.asyncio
async def test_cli_asks_before_writing_on_a_terminal(monkeypatch) -> None:
    """The CLI used to auto-allow every write with only a printed notice."""
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert await printer._decide("write data/x.txt") == ("skip", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert await printer._decide("write data/x.txt") == ("allow", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "a")
    assert await printer._decide("write data/x.txt") == ("allow_turn", True)


@pytest.mark.asyncio
async def test_cli_lost_stdin_is_not_consent(monkeypatch) -> None:
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=True)

    def closed(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert await printer._decide("write data/x.txt") == ("skip", False)


@pytest.mark.asyncio
async def test_cli_piped_denies_by_default() -> None:
    """Absence of a human is not consent — piped stdin skips confirms."""
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=False)
    assert await printer._decide("write data/x.txt") == ("skip", False)


@pytest.mark.asyncio
async def test_cli_piped_allow_write_opt_in() -> None:
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=False, allow_write=True)
    assert await printer._decide("write data/x.txt") == ("allow", False)
