from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DESC_RE = re.compile(
    r"<meta[^>]+name=['\"]description['\"][^>]+content=['\"](.*?)['\"]", re.I | re.S
)


@dataclass
class CaptureResult:
    body: str
    tags: list[str] = field(default_factory=list)
    kind_dir: str = "knowledge"
    region_hint: str | None = None


def handle(
    kind: str,
    payload: dict,
    *,
    fetch: Callable[[str], str] | None = None,
    blob_path: Path | None = None,
    engines: dict | None = None,
) -> CaptureResult:
    """Turn a local capture into text using pluggable local engines."""
    eng = engines or _default_engines()
    if kind == "note":
        result = CaptureResult(body=str(payload.get("text", "")).strip())
        result.region_hint = _safe_region(eng, result.body)
        return result
    if kind == "link":
        result = _handle_link(payload, fetch or _default_fetch)
        result.region_hint = _safe_region(eng, result.body)
        return result
    if kind == "youtube":
        return _handle_youtube(payload, eng)
    if kind == "image":
        return _handle_image(blob_path, eng)
    if kind == "audio":
        return _handle_audio(blob_path, eng)
    raise ValueError(f"unhandled capture kind: {kind!r}")


def _default_engines() -> dict:
    from . import media_engines
    from .vision_bridge import caption_for_image

    return {
        "youtube_text": media_engines.youtube_text,
        "describe_image": lambda path, prompt: caption_for_image(path),
        "transcribe_audio": media_engines.transcribe_audio,
        "distil": lambda text: text,
        "infer_region": lambda body: None,
    }


def _default_fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "ari-os-media/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return resp.read(1_000_000).decode("utf-8", "replace")


def _handle_link(payload: dict, fetch: Callable[[str], str]) -> CaptureResult:
    url = str(payload.get("url", "")).strip()
    title, desc = "", ""
    try:
        html = fetch(url)
        mt = _TITLE_RE.search(html)
        md = _DESC_RE.search(html)
        title = mt.group(1).strip() if mt else ""
        desc = md.group(1).strip() if md else ""
    except Exception:
        pass
    lines = [f"# {title}" if title else "# Link", "", url]
    if desc:
        lines += ["", desc]
    return CaptureResult(body="\n".join(lines))


def _handle_youtube(payload: dict, eng: dict) -> CaptureResult:
    raw = eng["youtube_text"](str(payload.get("url", "")).strip())
    body = eng["distil"](raw)
    return CaptureResult(body=body, region_hint=_safe_region(eng, body))


def _handle_image(blob_path: Path | None, eng: dict) -> CaptureResult:
    if blob_path is None:
        raise ValueError("image capture requires blob_path")
    desc = eng["describe_image"](blob_path, _IMAGE_PROMPT)
    return CaptureResult(body=desc, kind_dir="visual")


def _handle_audio(blob_path: Path | None, eng: dict) -> CaptureResult:
    if blob_path is None:
        raise ValueError("audio capture requires blob_path")
    transcript = eng["transcribe_audio"](blob_path)
    body = eng["distil"](transcript)
    return CaptureResult(body=body, region_hint=_safe_region(eng, body))


def _safe_region(eng: dict, body: str) -> str | None:
    try:
        return eng["infer_region"](body)
    except Exception:
        return None


_IMAGE_PROMPT = (
    "Describe this image for a creative reference library: subject, mood, "
    "lighting, palette, and composition."
)
