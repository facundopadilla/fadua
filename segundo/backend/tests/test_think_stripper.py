"""Tests for the <think>/<thinking> reasoning stripper (app.agent.think_strip).

Some OpenCode GO models (e.g. minimax-m3) emit chain-of-thought wrapped in
<think>...</think> — sometimes with no closing tag at all if the model gets
cut off mid-thought. This must never reach the user: not in the final
ChatResponse.answer, and not in the live-streamed "token" events (the user
must never see reasoning appear on screen even transiently).

Two surfaces under test:
- strip_think_tags(text): whole-string stripping for the final answer.
- ThinkStripper: incremental token-by-token stripping for the live stream,
  since a <think>...</think> block (or even the tag itself) can be split
  across multiple chunks from result.stream_text(delta=True).

Mirrors this repo's existing test conventions (see test_llm_agent.py):
plain assert-based functions, no pytest fixtures.
"""

from __future__ import annotations

from app.agent.think_strip import ThinkStripper, strip_think_tags

# --- strip_think_tags (final-answer / whole-string case) -------------------


def test_strip_think_tags_no_tags_passthrough() -> None:
    """Models that never emit think tags must be completely unaffected."""
    text = "Hubo 6.748 ventas en total durante el período consultado."
    assert strip_think_tags(text) == text


def test_strip_think_tags_removes_full_block() -> None:
    text = "<think>voy a sumar cantidad_ventas</think>Hubo 6.748 ventas en total."
    assert strip_think_tags(text) == "Hubo 6.748 ventas en total."


def test_strip_think_tags_removes_block_with_surrounding_text() -> None:
    text = "Antes. <think>razonamiento interno\ncon varias líneas</think> Después."
    assert strip_think_tags(text) == "Antes.  Después."


def test_strip_think_tags_removes_multiple_blocks() -> None:
    text = "<think>uno</think>Parte 1. <think>dos</think>Parte 2."
    assert strip_think_tags(text) == "Parte 1. Parte 2."


def test_strip_think_tags_handles_dangling_unclosed_tag() -> None:
    """A model cut off mid-reasoning may never emit the closing tag — drop
    from the opening tag to the end of the text rather than leaking raw
    reasoning (or the literal tag) into the answer."""
    text = "Respuesta parcial. <think>razonamiento que nunca cierra porque el modelo se cortó"
    assert strip_think_tags(text) == "Respuesta parcial. "


def test_strip_think_tags_handles_thinking_variant() -> None:
    text = "<thinking>otro formato de razonamiento</thinking>Respuesta real."
    assert strip_think_tags(text) == "Respuesta real."


def test_strip_think_tags_dangling_thinking_variant() -> None:
    text = "Antes <thinking>nunca cierra"
    assert strip_think_tags(text) == "Antes "


def test_strip_think_tags_empty_string() -> None:
    assert strip_think_tags("") == ""


def test_strip_think_tags_only_a_think_block_returns_empty() -> None:
    assert strip_think_tags("<think>todo es razonamiento</think>") == ""


# --- ThinkStripper (incremental streaming case) -----------------------------


def _feed(chunks: list[str]) -> str:
    """Drive a ThinkStripper across chunks + flush, concatenating whatever
    text it yields — mirrors how stream_llm_response would consume it."""
    stripper = ThinkStripper()
    out: list[str] = []
    for chunk in chunks:
        out.append(stripper.feed(chunk))
    out.append(stripper.flush())
    return "".join(out)


def test_think_stripper_passthrough_when_no_tags() -> None:
    chunks = ["Hola ", "hubo ", "6.748 ", "ventas."]
    assert _feed(chunks) == "Hola hubo 6.748 ventas."


def test_think_stripper_suppresses_full_block_split_across_chunks() -> None:
    """The core live-stream guarantee: reasoning tokens must never be
    yielded, not even transiently, regardless of how chunk boundaries land."""
    chunks = ["Antes. ", "<think>", "razonamiento ", "interno", "</think>", " Después."]
    assert _feed(chunks) == "Antes.  Después."


def test_think_stripper_suppresses_block_when_tag_itself_split_across_chunks() -> None:
    """Chunk boundary falls INSIDE the tag markup itself (e.g. "<th" + "ink>")
    — the stripper must still recognize the tag and not leak the partial
    literal "<th" into the output while waiting for more input."""
    chunks = ["Antes. ", "<th", "ink>", "secreto", "</th", "ink>", " Después."]
    assert _feed(chunks) == "Antes.  Después."


def test_think_stripper_dangling_unclosed_tag_at_end_of_stream() -> None:
    """If the stream ends while still inside a think block (model cut off),
    flush() must discard the buffered reasoning rather than leak it."""
    chunks = ["Respuesta parcial. ", "<think>", "nunca ", "cierra"]
    assert _feed(chunks) == "Respuesta parcial. "


def test_think_stripper_handles_thinking_variant() -> None:
    chunks = ["<thinking>", "razonamiento", "</thinking>", "Respuesta real."]
    assert _feed(chunks) == "Respuesta real."


def test_think_stripper_multiple_blocks_in_stream() -> None:
    chunks = ["<think>uno</think>", "Parte 1. ", "<think>dos</think>", "Parte 2."]
    assert _feed(chunks) == "Parte 1. Parte 2."


def test_think_stripper_empty_chunks_do_not_break_state() -> None:
    chunks = ["Antes. ", "", "<think>", "", "razon", "</think>", "", " Después."]
    assert _feed(chunks) == "Antes.  Después."
