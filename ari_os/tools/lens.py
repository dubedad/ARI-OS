"""LENS — optional video ingest for Cortex. Off by default.

Turns a video into text (frame captions / on-screen text) and stores each as a
memory. ffmpeg samples frames; a captioner (injected, or a vision tool the user
configures) turns them into text. With no captioner it does nothing. The core
never imports this; enable it with `arios cortex lens on`. Stdlib only.
"""
from __future__ import annotations
import shutil, subprocess, tempfile
from pathlib import Path
from . import cortex

def available() -> bool:
    return shutil.which("ffmpeg") is not None

def _sample_frames(path, n=3):
    if shutil.which("ffmpeg") is None:
        return []
    d = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-i", str(path), "-vf", "fps=1", "-frames:v", str(n),
                    f"{d}/frame_%03d.png"], capture_output=True, check=False)
    return sorted(str(p) for p in Path(d).glob("frame_*.png"))

def ingest(path, *, context="", captioner=None, conn=None):
    if captioner is None:
        return []
    captions = [c for c in captioner(path) if c]
    conn = conn or cortex.connect()
    return [cortex.remember(conn, c, context=context, source=str(path), tags="video")
            for c in captions]
