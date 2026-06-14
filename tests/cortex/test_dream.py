"""P4 dream orchestration tests: distill, queue, decay, and mode hint."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ari_os.tools.cortex import db, retrieve
from ari_os.tools.cortex import dream


class _StubLLM:
    def __init__(self) -> None:
        self.consolidate_calls: list[list[str]] = []
        self.distill_calls: list[tuple[str, int]] = []

    def consolidate(self, texts: list[str]) -> str:
        self.consolidate_calls.append(list(texts))
        return "Dream digest: " + " | ".join(texts)

    def distill(self, text: str, tier: int) -> str:
        self.distill_calls.append((text, tier))
        return f"Dream tier {tier + 1}: {text}"


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    path: str,
    tier: int = 0,
    region: str = "wernicke",
    importance: float = 0.5,
    last_retrieved_at: int | None = None,
    distilled_at: int | None = None,
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', 'test', 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute(
            "SELECT id FROM source WHERE path = ?", (path,)
        ).fetchone()[0]
        ordinal = con.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM chunk WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier, last_retrieved_at, distilled_at
               ) VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?)""",
            (
                source_id,
                ordinal,
                text,
                region,
                importance,
                tier,
                last_retrieved_at,
                distilled_at,
            ),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def _chunk_count(db_path: Path, tier: int | None = None) -> int:
    con = db.connect(db_path)
    try:
        if tier is None:
            return con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        return con.execute(
            "SELECT COUNT(*) FROM chunk WHERE distillation_tier = ?", (tier,)
        ).fetchone()[0]
    finally:
        con.close()


def test_run_dream_with_stub_llm_distills_queues_and_preserves_sources(
    brain_db: Path, tmp_path: Path
):
    first = _insert_chunk(brain_db, text="raw alpha", path="sessions/a.md")
    second = _insert_chunk(brain_db, text="raw bravo", path="sessions/a.md")
    tier3 = _insert_chunk(
        brain_db,
        text="weekly arc ready for dream queue",
        path="summaries/week.md",
        tier=3,
        region="parietal",
        distilled_at=1_748_505_600,
    )
    before_total = _chunk_count(brain_db)
    llm = _StubLLM()

    result = dream.run_dream(brain_db, llm=llm, output_dir=tmp_path)

    assert result.session_digests == 1
    assert result.dream_queue_items == 1
    assert result.mode == "default"
    assert llm.consolidate_calls == [["raw alpha", "raw bravo"]]
    assert _chunk_count(brain_db) == before_total + 1
    assert _chunk_count(brain_db, tier=1) == 1

    con = db.connect(brain_db)
    try:
        assert con.execute(
            "SELECT COUNT(*) FROM chunk WHERE id IN (?, ?, ?)",
            (first, second, tier3),
        ).fetchone()[0] == 3
        summary = con.execute(
            "SELECT text FROM chunk WHERE distillation_tier = 1"
        ).fetchone()[0]
    finally:
        con.close()
    assert summary == "Dream digest: raw alpha | raw bravo"

    queue_files = list((tmp_path / "dream" / "queue").glob("*.md"))
    assert len(queue_files) == 1
    assert "weekly arc ready for dream queue" in queue_files[0].read_text()


def test_run_dream_without_llm_noops_summarization_and_keeps_retrieve_working(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _insert_chunk(brain_db, text="postgres migration memory", path="sessions/a.md")
    _insert_chunk(brain_db, text="sqlite cortex memory", path="sessions/a.md")
    before_total = _chunk_count(brain_db)

    def fail_get_llm(spec=None):
        raise AssertionError("run_dream(llm=None) must not resolve a backend")

    monkeypatch.setattr("ari_os.tools.cortex.distill.get_llm", fail_get_llm)

    result = dream.run_dream(brain_db, llm=None, output_dir=tmp_path)

    assert result.session_digests == 0
    assert result.daily_syntheses == 0
    assert result.weekly_arcs == 0
    assert _chunk_count(brain_db) == before_total
    assert _chunk_count(brain_db, tier=1) == 0
    assert not (tmp_path / "consolidation").exists()
    hits = retrieve.fts_search(brain_db, "postgres", k=3)
    assert hits


def test_decay_pass_reduces_cold_importance_without_deleting_chunks(brain_db: Path):
    old = int(time.time()) - dream.COLD_THRESHOLD_SECS - 60
    cold = _insert_chunk(
        brain_db,
        text="cold retained memory",
        path="sessions/cold.md",
        importance=0.8,
        last_retrieved_at=old,
    )
    fresh = _insert_chunk(
        brain_db,
        text="fresh retained memory",
        path="sessions/fresh.md",
        importance=0.8,
        last_retrieved_at=int(time.time()),
    )

    dream.decay_pass(brain_db)

    con = db.connect(brain_db)
    try:
        rows = dict(
            con.execute(
                "SELECT id, importance FROM chunk WHERE id IN (?, ?)", (cold, fresh)
            ).fetchall()
        )
        total = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
    finally:
        con.close()
    assert rows[cold] == pytest.approx(0.8 * dream.IMPORTANCE_DECAY)
    assert rows[fresh] == pytest.approx(0.8)
    assert total == 2


def test_suggest_mode_writes_state_home_hint(brain_db: Path, tmp_path: Path):
    for i in range(dream.LOW_TIER_THRESHOLD):
        _insert_chunk(brain_db, text=f"raw {i}", path=f"sessions/{i}.md")

    mode = dream.suggest_mode(brain_db, mode_dir=tmp_path / "modes")

    assert mode == "synthesis"
    assert (tmp_path / "modes" / "suggested_mode").read_text() == "synthesis\n"
