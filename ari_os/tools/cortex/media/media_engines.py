from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ari_os.tools.cortex import config

WHISPER_BIN = os.environ.get("WHISPER_BIN", "whisper-cli")
WHISPER_MODEL = Path(
    os.environ.get("WHISPER_MODEL")
    or Path.home() / ".whisper-cpp" / "models" / "ggml-large-v3-turbo.bin"
)


class MediaUnavailable(RuntimeError):
    """Raised when an optional local media backend cannot produce text."""


Runner = Callable[..., Any]


def transcribe_audio(
    path: Path | str,
    *,
    runner: Runner | None = None,
    whisper_bin: str | None = None,
    model: Path | str | None = None,
    timeout: int = 1800,
) -> str:
    """Transcribe audio with local whisper.cpp when EARS and LLM are enabled."""
    if not _media_enabled():
        return ""

    audio = Path(path)
    cmd = [
        whisper_bin or WHISPER_BIN,
        "-m",
        str(model or WHISPER_MODEL),
        "-f",
        str(audio),
        "-oj",
        "--output-file",
        "-",
    ]
    run = runner or subprocess.run
    try:
        result = run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaUnavailable("local whisper.cpp binary is unavailable") from exc
    except subprocess.SubprocessError as exc:
        raise MediaUnavailable("local whisper.cpp failed") from exc

    stdout = _stdout(result)
    stderr = _stderr(result)
    returncode = _returncode(result)
    if returncode not in (None, 0):
        detail = stderr[:300] if stderr else "no stderr"
        raise MediaUnavailable(f"local whisper.cpp failed: {detail}")
    return _parse_whisper_text(stdout)


def youtube_text(
    url: str,
    *,
    fetcher: Callable[[str], Any] | None = None,
    languages: list[str] | None = None,
) -> str:
    """Fetch a YouTube transcript via optional local dependency.

    The import is lazy so the base package works without media extras.
    """
    if not _media_enabled():
        return ""

    video_id = _youtube_id(url)
    fetch = fetcher or _fetch_youtube_transcript
    transcript = fetch(video_id)
    return _transcript_text(transcript)


def _media_enabled() -> bool:
    return config.ears_enabled() and _cortex_llm_enabled()


def _cortex_llm_enabled() -> bool:
    env = os.environ.get("ARI_OS_LLM")
    if env is not None:
        return _llm_spec_enabled(env)

    data = config.runtime_config()
    value = data.get("cortex.llm")
    if value is None:
        cortex = data.get("cortex")
        if isinstance(cortex, dict):
            value = cortex.get("llm")
    if value is None:
        value = config.DEFAULT_LLM
    return _llm_spec_enabled(value)


def _llm_spec_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    spec = str(value or "").strip().lower()
    if not spec:
        return False
    provider = spec.split(":", 1)[0]
    return provider not in {"0", "false", "off", "none", "unavailable"}


def _fetch_youtube_transcript(video_id: str) -> Any:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError as exc:
        raise MediaUnavailable(
            "youtube-transcript-api is not installed; install ari-os[media]"
        ) from exc

    try:
        return YouTubeTranscriptApi.get_transcript(video_id)
    except Exception as exc:
        raise MediaUnavailable("YouTube transcript fetch failed") from exc


def _youtube_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/", 1)[0]
    else:
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    if not video_id:
        raise ValueError(f"could not determine YouTube video id from {url!r}")
    return video_id


def _parse_whisper_text(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text

    segments = data.get("transcription") or data.get("segments") or []
    return " ".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if isinstance(segment, dict) and str(segment.get("text", "")).strip()
    ).strip()


def _transcript_text(transcript: Any) -> str:
    if isinstance(transcript, str):
        return transcript.strip()
    if isinstance(transcript, dict):
        transcript = transcript.get("segments") or transcript.get("transcript") or []
    return " ".join(
        str(item.get("text", "")).strip()
        for item in transcript
        if isinstance(item, dict) and str(item.get("text", "")).strip()
    ).strip()


def _stdout(result: Any) -> str:
    if isinstance(result, str):
        return result
    return str(getattr(result, "stdout", ""))


def _stderr(result: Any) -> str:
    return str(getattr(result, "stderr", ""))


def _returncode(result: Any) -> int | None:
    return getattr(result, "returncode", None)
