"""P6 workspace blackboard and entropy monitor tests."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ari_os.tools.cortex.workspace.blackboard import (
    BlackboardEntry,
    append_finding,
    list_recent,
    read_blackboard,
    render_recent_md,
)
from ari_os.tools.cortex.workspace.entropy_monitor import (
    analyze,
    detect_repetition_stall,
    discover_active_transcript,
    lexical_entropy,
    write_stall_signal,
)


def write_user_message(path: Path, content: str) -> None:
    rec = {"type": "user", "message": {"content": content}}
    with path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def test_blackboard_roundtrips_under_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    now = 1_700_000_000
    old = BlackboardEntry(
        ts=now - (15 * 86400),
        kind="observation",
        source="test",
        cwd="/tmp/old",
        summary="too old",
    )
    first = BlackboardEntry(
        ts=now - 10,
        kind="observation",
        source="test",
        cwd="/tmp/demo",
        summary="first finding",
        body={"chunk_id": 1},
    )
    second = BlackboardEntry(
        ts=now,
        kind="session_summary",
        source="worker",
        cwd="/tmp/demo",
        summary="second finding",
        body={"chunk_id": 2},
    )

    append_finding(old)
    append_finding(first)
    append_finding(second)

    path = tmp_path / "state" / "workspace_state.json"
    assert path.exists()
    entries = read_blackboard()
    assert [e.summary for e in entries] == ["first finding", "second finding"]
    assert entries[0].body == {"chunk_id": 1}
    assert [e.summary for e in list_recent(limit=1)] == ["second finding"]

    rendered = render_recent_md(limit=2)
    assert rendered.startswith("## Brain - recent workspace findings")
    assert "**session_summary**" in rendered
    assert "second finding" in rendered


def test_repetition_stall_and_entropy():
    assert detect_repetition_stall(["again", " again ", "again"], n_repeats=3)
    assert not detect_repetition_stall(["one", "two", "one"], n_repeats=3)

    assert lexical_entropy(["alpha beta beta"]) == pytest.approx(
        -((1 / 3) * math.log2(1 / 3) + (2 / 3) * math.log2(2 / 3))
    )
    assert lexical_entropy([]) == 0.0


def test_analyze_detects_stalled_transcript_and_writes_signal(tmp_path, monkeypatch):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path / "state"))
    transcript = tmp_path / "session.jsonl"
    for _ in range(3):
        write_user_message(transcript, "same same")

    signal = analyze(transcript, n_messages=5, n_repeats=3, entropy_floor=2.0)

    assert signal is not None
    assert signal.reason == "both"
    assert signal.n_messages_analyzed == 3
    assert signal.lexical_entropy < 2.0
    assert signal.transcript_path == str(transcript)

    out = write_stall_signal(signal)
    assert out == tmp_path / "state" / "stall_signal.md"
    assert out.exists()
    assert "## Brain - stall signal" in out.read_text()


def test_discover_active_transcript_finds_newest_jsonl(tmp_path):
    cwd = "/tmp/ari-os/workspaces/demo"
    project_dir = tmp_path / cwd.replace("/", "-")
    project_dir.mkdir(parents=True)
    older = project_dir / "older.jsonl"
    newer = project_dir / "newer.jsonl"
    older.write_text("{}\n")
    newer.write_text("{}\n")

    assert discover_active_transcript(cwd, projects_dir=tmp_path) == newer
    assert discover_active_transcript("/tmp/missing", projects_dir=tmp_path) is None
