"""Strips <think>/<thinking> reasoning blocks that some OpenCode GO models
(e.g. minimax-m3) emit as raw chain-of-thought inline with their answer.

This must NEVER reach the user — not in ``ChatResponse.answer`` and not in
any live-streamed "token" events. Two surfaces are provided:

- ``strip_think_tags``: whole-string stripping. This is the surface
  ``stream_llm_response`` currently uses — it runs ``agent.run()`` (not
  ``run_stream()``), which already only exposes the model's FINAL text via
  ``AgentRunResult.output``, so one whole-string pass over that text is
  enough.
- ``ThinkStripper``: incremental, chunk-by-chunk stripping for a live
  delta token stream (e.g. ``result.stream_text(delta=True)``), which can
  split a ``<think>...</think>`` block — or even the tag markup itself —
  across multiple chunks. Not currently wired into ``llm_agent.py`` (see
  above), but kept here, fully tested, for any future caller that streams
  raw model deltas instead of a single final string.

A model that never emits think tags is completely unaffected by either path
(no tags found -> input returned/forwarded unchanged).
"""

from __future__ import annotations

import re

# Matches a complete <think>...</think> or <thinking>...</thinking> block.
# DOTALL so reasoning spanning multiple lines is captured; non-greedy so
# "<think>a</think>x<think>b</think>" yields two blocks, not one spanning both.
_THINK_BLOCK_RE = re.compile(r"<think(?:ing)?>.*?</think(?:ing)?>", re.DOTALL | re.IGNORECASE)

# Matches a dangling, never-closed opening tag through the end of the string
# (model got cut off mid-reasoning) — everything from the tag onward is
# reasoning, so it's dropped rather than leaking the raw tag or partial
# chain-of-thought text.
_DANGLING_OPEN_TAG_RE = re.compile(r"<think(?:ing)?>.*\Z", re.DOTALL | re.IGNORECASE)

# The longest opening tag this module recognizes ("<thinking>") — used by
# ThinkStripper to size how much trailing text it must hold back in case a
# chunk boundary falls in the middle of a tag.
_MAX_TAG_LEN = len("<thinking>")


def strip_think_tags(text: str) -> str:
    """Remove all <think>/<thinking> reasoning blocks from ``text``.

    Handles complete blocks (possibly several) and a single dangling
    unclosed opening tag at the end of the text. Text with no think tags at
    all is returned unchanged.
    """
    without_blocks = _THINK_BLOCK_RE.sub("", text)
    return _DANGLING_OPEN_TAG_RE.sub("", without_blocks)


class ThinkStripper:
    """Incremental <think>/<thinking> stripper for a live token stream.

    Feed it chunks in arrival order via ``feed()``; it returns only the
    portion of clean (non-reasoning) text safe to forward immediately. It
    withholds a small tail of text internally whenever that tail could be
    the start of a "<think" tag that hasn't fully arrived yet, so a tag
    split across chunk boundaries (e.g. "<th" then "ink>") is never
    mistaken for plain text and forwarded.

    Call ``flush()`` once the stream ends to release any safe trailing text
    still held back — or, if the stream ended while inside an unclosed
    think block, to discard the buffered reasoning instead of leaking it.

    One instance per run (mirrors ``LlmToolDeps``: never share or reuse
    across requests).
    """

    def __init__(self) -> None:
        self._pending: str = ""  # raw text not yet decided/emitted
        self._in_think: bool = False  # True while inside an open <think(ing)> block

    def feed(self, chunk: str) -> str:
        """Consume one chunk of raw model output; return the clean text
        (if any) that is now safe to forward to the user."""
        self._pending += chunk
        return self._drain()

    def flush(self) -> str:
        """Signal end of stream. Returns any remaining safe text; discards
        anything still buffered inside an unclosed think block."""
        if self._in_think:
            # Stream ended mid-reasoning (model cut off) — this is the
            # streaming equivalent of _DANGLING_OPEN_TAG_RE: drop it all.
            self._pending = ""
            return ""
        remainder = self._pending
        self._pending = ""
        return remainder

    def _drain(self) -> str:
        """Repeatedly resolve as much of ``self._pending`` as can be safely
        decided given what has arrived so far, leaving only an ambiguous
        tail (a prefix that might still grow into a recognized tag) in
        ``self._pending``."""
        output_parts: list[str] = []
        while True:
            if self._in_think:
                close = _find_close_tag(self._pending)
                if close is None:
                    # Still inside reasoning and no close tag yet — hold
                    # everything (it's all suppressed either way) and wait
                    # for more input rather than scanning it again.
                    return "".join(output_parts)
                self._pending = self._pending[close:]
                self._in_think = False
                continue

            open_at = _find_open_tag_start(self._pending)
            if open_at is None:
                # No "<think"/"<thinking" prefix anywhere pending — but the
                # very end of the buffer might be the start of "<" that
                # hasn't grown enough to confirm/reject yet. Hold back only
                # that ambiguous tail.
                safe_len = _safe_emit_length(self._pending)
                output_parts.append(self._pending[:safe_len])
                self._pending = self._pending[safe_len:]
                return "".join(output_parts)

            confirmed_open = _confirmed_open_tag_end(self._pending, open_at)
            if confirmed_open is None:
                # A "<think"-ish prefix is present but not yet long enough
                # to confirm it's "<think>" / "<thinking>" (or to rule that
                # out) — emit everything before it and wait for more input.
                output_parts.append(self._pending[:open_at])
                self._pending = self._pending[open_at:]
                return "".join(output_parts)

            # Confirmed real opening tag: emit text before it, drop the tag
            # itself, and switch into suppression mode.
            output_parts.append(self._pending[:open_at])
            self._pending = self._pending[confirmed_open:]
            self._in_think = True


_OPEN_TAG_PREFIXES = ("<think>", "<thinking>")


def _find_open_tag_start(text: str) -> int | None:
    """Index of the first "<" that begins a (possibly still-arriving)
    "<think" prefix, or None if no such "<" exists in ``text`` at all."""
    lowered = text.lower()
    idx = lowered.find("<think")
    return idx if idx != -1 else None


def _confirmed_open_tag_end(text: str, start: int) -> int | None:
    """If ``text[start:]`` begins with a complete, recognized opening tag
    ("<think>" or "<thinking>", case-insensitive), return the index just
    past it. Otherwise None — either it's confirmed to be something else, or
    there isn't enough text yet to tell (caller must wait for more input in
    the latter case, but both return None here; distinguishing them isn't
    needed because _drain only calls this once the text has already been
    checked to start with the "<think" prefix, and the tail bound below
    covers the "not enough text yet" case via _safe_emit_length upstream)."""
    lowered = text[start:].lower()
    for prefix in _OPEN_TAG_PREFIXES:
        if lowered.startswith(prefix):
            return start + len(prefix)
    return None


def _find_close_tag(text: str) -> int | None:
    """Index just past the first "</think>" or "</thinking>" in ``text``
    (case-insensitive), or None if no complete closing tag is present yet."""
    lowered = text.lower()
    best: int | None = None
    for prefix in ("</think>", "</thinking>"):
        idx = lowered.find(prefix)
        if idx != -1:
            end = idx + len(prefix)
            if best is None or end < best:
                best = end
    return best


def _safe_emit_length(text: str) -> int:
    """How many leading characters of ``text`` are safe to emit immediately
    when no "<think" prefix was found anywhere in it.

    Held back: a trailing suffix that is itself a strict prefix of "<think"
    (e.g. text ending in "<", "<t", "<th", ...) — the next chunk could
    complete it into a real opening tag. Anything before that suffix cannot
    possibly be part of a tag that starts later, so it's always safe.
    """
    max_hold = min(len(text), _MAX_TAG_LEN - 1)
    for hold in range(max_hold, 0, -1):
        suffix = text[-hold:]
        if "<think".startswith(suffix.lower()):
            return len(text) - hold
    return len(text)
