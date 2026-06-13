"""ARI-OS Cortex — Claude Code transcript (.jsonl) noise filter.

Reads Claude Code session transcripts and yields clean user/assistant text
segments — dropping tool_use/tool_result blocks, eliding oversized code
fences, and skipping empty / non-message records.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

CODE_BLOCK = re.compile(r"```[\s\S]*?```")
MAX_CODE_LINES = 60


@dataclass
class TranscriptSegment:
    kind: str  # "user" | "assistant"
    text: str
    session_id: str
    timestamp_iso: str
    cwd: str | None


def _extract_text_blocks(content: list[dict]) -> list[str]:
    out: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            out.append(block.get("text", ""))
        # tool_use / tool_result intentionally dropped
    return out


def _strip_long_code(text: str) -> str:
    def repl(match: re.Match) -> str:
        block = match.group(0)
        if block.count("\n") > MAX_CODE_LINES:
            return "[code block elided — too long]"
        return block

    return CODE_BLOCK.sub(repl, text)


def filter_jsonl(path: Path) -> list[TranscriptSegment]:
    out: list[TranscriptSegment] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            if kind not in ("user", "assistant"):
                continue
            msg = rec.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, str):
                texts = [content]
            else:
                texts = _extract_text_blocks(content if isinstance(content, list) else [])
            if not texts:
                continue
            text = "\n\n".join(_strip_long_code(t) for t in texts if t and t.strip())
            if not text.strip():
                continue
            out.append(TranscriptSegment(
                kind=kind,
                text=text,
                session_id=rec.get("sessionId", ""),
                timestamp_iso=rec.get("timestamp", ""),
                cwd=rec.get("cwd"),
            ))
    return out
