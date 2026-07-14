from io import StringIO

from ui.terminal_prompt import render_terminal_prompt


def test_unicode_prompt_uses_real_model_and_local_state() -> None:
    prompt = render_terminal_prompt(
        "qwen2.5-coder:14b",
        "LOCAL",
        stream=StringIO(),
        unicode=True,
    )

    assert prompt.startswith("╭─ VEGA ─ qwen2.5-coder:14b ─ LOCAL")
    assert "╰─› Напишите задачу…" in prompt


def test_ascii_prompt_is_plain_and_encodable() -> None:
    prompt = render_terminal_prompt(
        "qwen2.5-coder:7b",
        "LOCAL",
        stream=StringIO(),
        unicode=False,
    )

    assert prompt == "VEGA [qwen2.5-coder:7b] [LOCAL]\n> Enter task... "
    assert prompt.isascii()


def test_color_disabled_never_emits_ansi() -> None:
    prompt = render_terminal_prompt(
        "model",
        stream=StringIO(),
        unicode=True,
        color=False,
    )

    assert "\x1b[" not in prompt


def test_prompt_strips_control_characters_from_state() -> None:
    prompt = render_terminal_prompt(
        "safe\nmodel\x00",
        "LO\rCAL",
        stream=StringIO(),
        unicode=False,
    )

    assert "safe" in prompt
    assert prompt.count("\n") == 1
    assert "\x00" not in prompt
