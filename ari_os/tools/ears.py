"""EARS — optional audio ingest for Cortex. Off by default.

Turns an audio file into text and stores it as a memory. Uses a local
transcription tool (whisper) when present, or an injected transcriber. If no
backend produces text, ingest() returns None rather than failing loudly. The
core never imports this; enable it with `arios cortex ears on`. Stdlib only.
"""
from __future__ import annotations
import shutil, subprocess, tempfile
from pathlib import Path
from . import cortex

def available() -> bool:
    return shutil.which("whisper") is not None

def _whisper_transcribe(path):
    if shutil.which("whisper") is None:
        return None
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["whisper", str(path), "--output_format", "txt",
                        "--output_dir", d], capture_output=True, check=False)
        txt = Path(d) / (Path(path).stem + ".txt")
        return txt.read_text().strip() if txt.exists() else None

def ingest(path, *, context="", transcriber=None, conn=None):
    transcribe = transcriber or _whisper_transcribe
    text = transcribe(path)
    if not text:
        return None
    conn = conn or cortex.connect()
    return cortex.remember(conn, text, context=context, source=str(path), tags="audio")
