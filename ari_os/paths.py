"""Env-aware filesystem locations shared by the installer + control panel."""
from __future__ import annotations
import os
from pathlib import Path


def state_home() -> Path:
    return Path(os.environ.get("ARI_OS_HOME") or os.path.expanduser("~/.ari-os"))


def claude_dir() -> Path:
    return Path(os.environ.get("ARI_OS_CLAUDE_DIR") or os.path.expanduser("~/.claude"))


def agent_config_dir(target: str, custom_dir: str | os.PathLike | None = None) -> Path:
    """Resolve the config root for a supported agent harness."""
    if target == "claude":
        return claude_dir()
    if target == "codex":
        return Path(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"))
    if target == "gemini":
        return Path(os.environ.get("GEMINI_DIR") or os.path.expanduser("~/.gemini"))
    if target == "kimi":
        return Path(os.environ.get("KIMI_CODE_HOME") or os.path.expanduser("~/.kimi-code"))
    if target == "custom":
        if custom_dir is None:
            raise ValueError("--dir is required when --target custom")
        return Path(custom_dir).expanduser()
    raise ValueError(f"unsupported agent target: {target}")


def backups_dir() -> Path:
    return state_home() / "backups"


def installed_manifest() -> Path:
    return state_home() / "installed.json"


def safe_segment(value: str) -> str:
    """Collapse an untrusted string to a single filesystem segment."""
    seg = Path(str(value)).name
    if seg in ("", ".", ".."):
        raise ValueError(f"unsafe path segment: {value!r}")
    return seg


def resolve_within(base, candidate) -> Path:
    """Resolve candidate and guarantee it stays inside base."""
    base_r = Path(base).resolve()
    cand = Path(candidate)
    target = (cand if cand.is_absolute() else base_r / cand).resolve()
    if target != base_r and not target.is_relative_to(base_r):
        raise ValueError(f"path escapes {base_r}: {candidate!r}")
    return target


def ensure_private_dir(path) -> Path:
    """mkdir -p with 0o700, independent of the process umask."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def write_private(path, text: str) -> None:
    """Write text to path with mode 0o600, independent of the process umask."""
    path = Path(path)
    ensure_private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    try:
        path.chmod(0o600)
    except OSError:
        pass
