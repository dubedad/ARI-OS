"""Transcript entropy monitor for detecting repeated or low-variety prompts."""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import state_home

TOKEN_RE = re.compile(r"\w+")


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(part for part in parts if part)
    return ""


def read_recent_messages(transcript_path: Path, n: int = 5) -> list[str]:
    """Return the last N user-message strings from a JSONL transcript."""
    if not transcript_path.exists() or not transcript_path.is_file():
        return []
    user_texts: list[str] = []
    try:
        lines = transcript_path.read_text().splitlines()
    except OSError:
        return []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") != "user":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        text = _extract_text(msg.get("content", ""))
        if text:
            user_texts.append(text)
    return user_texts[-n:]


def detect_repetition_stall(messages: list[str], n_repeats: int = 3) -> bool:
    """Detect byte-identical repeated prompts after whitespace normalization."""
    if len(messages) < n_repeats:
        return False
    tail = [message.strip() for message in messages[-n_repeats:]]
    return all(tail) and len(set(tail)) == 1


def lexical_entropy(messages: list[str]) -> float:
    """Shannon entropy, base 2, over lowercased word-token frequencies."""
    tokens: list[str] = []
    for message in messages:
        tokens.extend(token.lower() for token in TOKEN_RE.findall(message))
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


@dataclass
class StallSignal:
    ts: int
    transcript_path: str
    reason: str
    n_messages_analyzed: int
    lexical_entropy: float
    suggestion: str


def analyze(
    transcript_path: Path,
    n_messages: int = 5,
    n_repeats: int = 3,
    entropy_floor: float = 2.0,
) -> StallSignal | None:
    """Return a stall signal if a transcript appears repetitive or low-entropy."""
    messages = read_recent_messages(transcript_path, n=n_messages)
    if not messages:
        return None
    repetition = detect_repetition_stall(messages, n_repeats=n_repeats)
    entropy = lexical_entropy(messages)
    low_entropy = entropy < entropy_floor and len(messages) >= n_repeats
    if not (repetition or low_entropy):
        return None

    if repetition and low_entropy:
        reason = "both"
        suggestion = (
            "Conversation may be looping: recent prompts repeat and lexical "
            "variety is low. Name the blocker or switch modes."
        )
    elif repetition:
        reason = "repetition"
        suggestion = "Recent prompts repeat. Name the blocker explicitly."
    else:
        reason = "low_entropy"
        suggestion = "Recent prompts have low lexical variety. Try a structural break."

    return StallSignal(
        ts=int(time.time()),
        transcript_path=str(transcript_path),
        reason=reason,
        n_messages_analyzed=len(messages),
        lexical_entropy=entropy,
        suggestion=suggestion,
    )


def default_stall_signal_path() -> Path:
    return state_home() / "stall_signal.md"


def render_stall_md(signal: StallSignal) -> str:
    return (
        "## Brain - stall signal\n\n"
        f"- Reason: **{signal.reason}**\n"
        f"- Lexical entropy: {signal.lexical_entropy:.2f}\n"
        f"- Messages analyzed: {signal.n_messages_analyzed}\n"
        f"- Suggestion: {signal.suggestion}\n"
    )


def write_stall_signal(signal: StallSignal, path: Path | None = None) -> Path:
    resolved = Path(path) if path is not None else default_stall_signal_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(render_stall_md(signal))
    return resolved


def clear_stall_signal(path: Path | None = None) -> None:
    resolved = Path(path) if path is not None else default_stall_signal_path()
    if resolved.exists():
        resolved.unlink()


def discover_active_transcript(
    cwd: str,
    projects_dir: Path = Path.home() / ".claude" / "projects",
) -> Path | None:
    """Return the newest transcript in the encoded project directory for cwd."""
    if not cwd:
        return None
    project_dir = projects_dir / cwd.replace("/", "-")
    if not project_dir.exists():
        return None
    jsonls = sorted(
        project_dir.glob("*.jsonl"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return jsonls[0] if jsonls else None


# P7: optional launch-agent install.
