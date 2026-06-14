"""P4 distill tests: LLM-gated, sqlite-only, non-destructive consolidation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ari_os.tools.cortex import db, mcp_tools
from ari_os.tools.cortex import distill


DAY1 = 1_748_505_600
DAY2 = DAY1 + 86_400


class _StubLLM:
    def __init__(self) -> None:
        self.consolidate_calls: list[list[str]] = []
        self.distill_calls: list[tuple[str, int]] = []

    def consolidate(self, texts: list[str]) -> str:
        self.consolidate_calls.append(list(texts))
        return "Digest: " + " | ".join(texts)

    def distill(self, text: str, tier: int) -> str:
        self.distill_calls.append((text, tier))
        return f"Tier {tier + 1}: {text}"


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
               ) VALUES (?, ?, ?, 1, 1, ?, 0.5, ?, ?, ?)""",
            (source_id, ordinal, text, region, tier, last_retrieved_at, distilled_at),
        )
        return cur.lastrowid
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


def test_region_for_tier_routes_digest_and_synthesis_regions():
    assert distill.region_for_tier(1) == "hippocampus"
    assert distill.region_for_tier(2) == "parietal"
    assert distill.region_for_tier(3) == "parietal"


def test_session_digest_off_gate_noops_without_llm_calls(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _insert_chunk(brain_db, text="alpha memory", path="sessions/a.md")
    _insert_chunk(brain_db, text="bravo memory", path="sessions/a.md")
    before_total = _chunk_count(brain_db)

    monkeypatch.setenv("ARI_OS_CONSOLIDATION_LLM", "off")
    created = distill.distill_session_to_digest(brain_db, output_dir=tmp_path)

    assert created == 0
    assert _chunk_count(brain_db) == before_total
    assert _chunk_count(brain_db, tier=1) == 0
    assert not (tmp_path / "consolidation").exists()


def test_explicit_none_llm_noops_without_resolving_backend(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _insert_chunk(brain_db, text="alpha memory", path="sessions/a.md")
    _insert_chunk(brain_db, text="bravo memory", path="sessions/a.md")
    before_total = _chunk_count(brain_db)

    def fail_get_llm(spec=None):
        raise AssertionError("explicit llm=None must not resolve a backend")

    monkeypatch.setattr(distill, "get_llm", fail_get_llm)

    created = distill.distill_session_to_digest(brain_db, output_dir=tmp_path, llm=None)

    assert created == 0
    assert _chunk_count(brain_db) == before_total
    assert _chunk_count(brain_db, tier=1) == 0


def test_daily_and_weekly_explicit_none_llm_noop(
    brain_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _insert_chunk(
        brain_db, text="day alpha", path="workspaces/alpha/a.md", tier=1, distilled_at=DAY1
    )
    _insert_chunk(
        brain_db, text="day bravo", path="workspaces/alpha/b.md", tier=1, distilled_at=DAY1
    )
    _insert_chunk(
        brain_db, text="week alpha", path="workspaces/alpha/c.md", tier=2, distilled_at=DAY1
    )
    _insert_chunk(
        brain_db, text="week bravo", path="workspaces/alpha/d.md", tier=2, distilled_at=DAY2
    )
    before_total = _chunk_count(brain_db)

    def fail_get_llm(spec=None):
        raise AssertionError("explicit llm=None must not resolve a backend")

    monkeypatch.setattr(distill, "get_llm", fail_get_llm)

    assert distill.distill_daily_synthesis(brain_db, output_dir=tmp_path, llm=None) == 0
    assert distill.distill_weekly_arc(brain_db, output_dir=tmp_path, llm=None) == 0
    assert _chunk_count(brain_db) == before_total


def test_session_digest_creates_summary_lineage_edges_and_artifact(
    brain_db: Path, tmp_path: Path
):
    first = _insert_chunk(brain_db, text="alpha memory", path="sessions/a.md")
    second = _insert_chunk(brain_db, text="bravo memory", path="sessions/a.md")
    llm = _StubLLM()

    created = distill.distill_session_to_digest(brain_db, output_dir=tmp_path, llm=llm)

    assert created == 1
    assert llm.consolidate_calls == [["alpha memory", "bravo memory"]]
    con = db.connect(brain_db)
    try:
        row = con.execute(
            """SELECT id, text, parent_chunks, region, distillation_tier
                 FROM chunk WHERE distillation_tier = 1"""
        ).fetchone()
        assert row is not None
        summary_id, text, parent_json, region, tier = row
        assert text == "Digest: alpha memory | bravo memory"
        assert json.loads(parent_json) == [first, second]
        assert region == "hippocampus"
        assert tier == 1
        assert con.execute(
            "SELECT COUNT(*) FROM chunk WHERE id IN (?, ?)", (first, second)
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT COUNT(*) FROM tract_edge WHERE tract = 'uncinate'"
        ).fetchone()[0] == 4
    finally:
        con.close()

    lineage = mcp_tools.lineage(brain_db, summary_id)
    assert [parent["chunk_id"] for parent in lineage["parents"]] == [first, second]
    artifacts = list((tmp_path / "consolidation").glob("tier0to1_*.md"))
    assert len(artifacts) == 1
    assert "Digest: alpha memory | bravo memory" in artifacts[0].read_text()


def test_session_digest_is_idempotent_and_skips_hot_or_small_groups(
    brain_db: Path, tmp_path: Path
):
    _insert_chunk(brain_db, text="alpha memory", path="sessions/a.md")
    _insert_chunk(brain_db, text="bravo memory", path="sessions/a.md")
    _insert_chunk(brain_db, text="solo memory", path="sessions/solo.md")
    _insert_chunk(
        brain_db,
        text="hot alpha",
        path="sessions/hot.md",
        last_retrieved_at=int(time.time()),
    )
    _insert_chunk(
        brain_db,
        text="hot bravo",
        path="sessions/hot.md",
        last_retrieved_at=int(time.time()),
    )

    assert distill.distill_session_to_digest(brain_db, output_dir=tmp_path, llm=_StubLLM()) == 1
    assert distill.distill_session_to_digest(brain_db, output_dir=tmp_path, llm=_StubLLM()) == 0
    assert _chunk_count(brain_db, tier=0) == 5
    assert _chunk_count(brain_db, tier=1) == 1


def test_daily_and_weekly_synthesis_promote_tiers_without_deleting_sources(
    brain_db: Path, tmp_path: Path
):
    first = _insert_chunk(
        brain_db, text="day alpha", path="workspaces/alpha/a.md", tier=1, distilled_at=DAY1
    )
    second = _insert_chunk(
        brain_db, text="day bravo", path="workspaces/alpha/b.md", tier=1, distilled_at=DAY1
    )
    other_day_a = _insert_chunk(
        brain_db, text="week alpha", path="workspaces/alpha/c.md", tier=2, distilled_at=DAY1
    )
    other_day_b = _insert_chunk(
        brain_db, text="week bravo", path="workspaces/alpha/d.md", tier=2, distilled_at=DAY2
    )
    before_total = _chunk_count(brain_db)
    llm = _StubLLM()

    assert distill.distill_daily_synthesis(brain_db, output_dir=tmp_path, llm=llm) == 1
    assert distill.distill_weekly_arc(brain_db, output_dir=tmp_path, llm=llm) == 1

    con = db.connect(brain_db)
    try:
        daily = con.execute(
            "SELECT id, region, parent_chunks FROM chunk WHERE distillation_tier = 2 "
            "AND text LIKE 'Tier 2:%'"
        ).fetchone()
        weekly = con.execute(
            "SELECT id, region, parent_chunks FROM chunk WHERE distillation_tier = 3"
        ).fetchone()
        assert daily is not None
        assert weekly is not None
        assert daily[1] == "parietal"
        assert json.loads(daily[2]) == [first, second]
        assert weekly[1] == "parietal"
        assert json.loads(weekly[2]) == [other_day_a, other_day_b]
        assert con.execute(
            "SELECT COUNT(*) FROM chunk WHERE id IN (?, ?, ?, ?)",
            (first, second, other_day_a, other_day_b),
        ).fetchone()[0] == 4
    finally:
        con.close()

    assert _chunk_count(brain_db) == before_total + 2
    assert distill.distill_daily_synthesis(brain_db, output_dir=tmp_path, llm=_StubLLM()) == 0
    assert distill.distill_weekly_arc(brain_db, output_dir=tmp_path, llm=_StubLLM()) == 0
