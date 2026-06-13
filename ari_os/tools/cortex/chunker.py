"""ARI-OS Cortex — markdown chunker.

Splits a markdown document on H2 boundaries, then size-caps within each
section. The hard character ceiling per chunk is the reliable guard
against embedding models that reject oversized inputs.
character ceiling per chunk is the reliable guard against embedding models
that reject oversized inputs (nomic-embed-text: HTTP 500 over 2048 tokens).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

H2_PATTERN = re.compile(r"^##\s", re.MULTILINE)

# Hard character ceiling per chunk. Embedding backends (e.g. nomic-embed-text)
# reject inputs over their context length with HTTP 500 ("the input length
# exceeds the context length"). The word-count token estimate below undercounts
# dense / structureless content (YAML, JSON, tables, long no-whitespace runs)
# by 2.5-5x, so chunks that look small by token estimate can blow the real
# limit. Character length is a reliable upper bound on what the embedder
# will accept.
MAX_CHUNK_CHARS = 4000


@dataclass
class Chunk:
    text: str
    line_start: int  # 1-based
    line_end: int    # 1-based, inclusive


def _approx_tokens(s: str) -> int:
    """Cheap token estimate: word count * 1.3. Good enough for chunking budgets."""
    return int(len(s.split()) * 1.3)


def _split_by_words(text: str, line_no: int, max_tokens: int, overlap: int) -> list[Chunk]:
    """Word-boundary fallback for single-line text that exceeds max_tokens."""
    words = text.split()
    # approximate words per chunk (undo the 1.3 multiplier)
    cap = int(max_tokens / 1.3)
    ovl = int(overlap / 1.3)
    out: list[Chunk] = []
    i = 0
    while i < len(words):
        window = words[i: i + cap]
        out.append(Chunk(text=" ".join(window), line_start=line_no, line_end=line_no))
        if i + cap >= len(words):
            break
        i += cap - ovl
        if i <= 0:
            i = cap
    return out


def _split_long_block(text: str, base_line: int, max_tokens: int, overlap: int) -> list[Chunk]:
    """Sliding window over lines, capping each window at max_tokens."""
    lines = text.split("\n")
    out: list[Chunk] = []
    i = 0
    while i < len(lines):
        window: list[str] = []
        start = i
        while i < len(lines) and _approx_tokens("\n".join(window + [lines[i]])) <= max_tokens:
            window.append(lines[i])
            i += 1
        if not window:
            # Single line exceeds cap — split by words
            line = lines[i]
            out.extend(_split_by_words(line, base_line + i, max_tokens, overlap))
            i += 1
            continue
        out.append(Chunk(
            text="\n".join(window).strip(),
            line_start=base_line + start,
            line_end=base_line + start + len(window) - 1,
        ))
        # back off for overlap
        if overlap > 0 and i < len(lines):
            back = 0
            while back < len(window) and _approx_tokens(
                "\n".join(window[-(back + 1):])
            ) < overlap:
                back += 1
            i = max(start + 1, i - back)
    return out


def _slice_on_char_budget(text: str, max_chars: int) -> list[str]:
    """Split text into pieces <= max_chars, preferring newline then space seams.

    Falls back to a hard slice only when a window contains no usable break (e.g.
    a single huge no-whitespace run), in which case content is preserved across
    pieces rather than lost.
    """
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    i, n = 0, len(text)
    while i < n:
        end = min(i + max_chars, n)
        if end < n:
            window = text[i:end]
            brk = window.rfind("\n")
            if brk < max_chars // 2:
                brk = window.rfind(" ")
            if brk >= max_chars // 2:
                end = i + brk + 1
        piece = text[i:end].strip()
        if piece:
            pieces.append(piece)
        i = end
    return pieces


def _finalize_chunks(chunks: list[Chunk], max_chars: int) -> list[Chunk]:
    """Final guard over all chunks regardless of how they were produced
    (oversized H2 section, line window, or word window):

    1. Drop empty / whitespace-only chunks. The overlap back-off in
       _split_long_block can land a window on blank lines that strips to "";
       an empty prompt embeds to dim-0 and fails.
    2. Re-split any chunk over the char ceiling. The word-count token estimate
       cannot be trusted on dense content, but character length is a reliable
       upper bound on what the embedder will accept.
    """
    out: list[Chunk] = []
    for c in chunks:
        if not c.text.strip():
            continue
        if len(c.text) <= max_chars:
            out.append(c)
            continue
        for piece in _slice_on_char_budget(c.text, max_chars):
            out.append(Chunk(text=piece, line_start=c.line_start, line_end=c.line_end))
    return out


def chunk_markdown(
    md: str,
    max_tokens: int = 800,
    overlap_tokens: int = 100,
) -> list[Chunk]:
    """Split a markdown document on H2 boundaries, then size-cap within each section."""
    if not md.strip():
        return []

    lines = md.split("\n")
    # find H2 line indices
    h2_positions = [i for i, ln in enumerate(lines) if H2_PATTERN.match(ln + "\n")]
    if not h2_positions or h2_positions[0] > 0:
        h2_positions = [0] + h2_positions
    h2_positions.append(len(lines))

    out: list[Chunk] = []
    for start, end in zip(h2_positions[:-1], h2_positions[1:]):
        section_text = "\n".join(lines[start:end]).strip()
        if not section_text:
            continue
        if _approx_tokens(section_text) <= max_tokens:
            out.append(Chunk(
                text=section_text,
                line_start=start + 1,
                line_end=end,
            ))
        else:
            out.extend(
                _split_long_block(section_text, start + 1, max_tokens, overlap_tokens)
            )
    return _finalize_chunks(out, MAX_CHUNK_CHARS)
