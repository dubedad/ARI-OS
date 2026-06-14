"""P5 gate - knowledge graph plus council DoD audit.

This module bundles DoD-P5-a..h into one proof surface so
``pytest -q tests/cortex/test_p5_gate.py`` validates the KG extraction/query,
retrieval expansion, council allocation, salience, marker, dream report, and
scrub gates end to end on real sqlite state.
"""
from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from ari_os.tools.cortex import db
from ari_os.tools.cortex.kg.extractor import ExtractedEntity, ExtractedRelation
from ari_os.tools.cortex.kg.query import find_entity_by_name, related_entities, traverse
from ari_os.tools.cortex.kg.state import select_unextracted
from ari_os.tools.cortex.kg.store import link_entity_to_chunk, upsert_entity, upsert_relation
from ari_os.tools.cortex.kg.sweep import LLMUnavailable, populate_kg, populate_kg_incremental


REPO_ROOT = Path(__file__).resolve().parents[2]
PROD_ROOT = REPO_ROOT / "ari_os"

AUDIT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    ".pytest_cache",
    "__pycache__",
    ".worktrees",
    ".eggs",
    "node_modules",
    "tests",
}
AUDITABLE_SUFFIXES = {
    ".py",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".sh",
}
_BANNED_B64 = (
    "U0hBRE9X",
    "L1ZvbHVtZXM=",
    "Y3JlYXRpb2V4bmloaWxv",
    "c2hhZG93X2Rpc3BhdGNo",
    "c2hhZG93X2JyYWlu",
    "TUVNT1JZX0JBTks=",
    "TmVvbg==",
    "U0hBRE9XX0NPVU5DSUw=",
    "TklNXw==",
    "QlJBSU5fTExN",
)
BANNED_TOKENS = tuple(base64.b64decode(raw).decode("ascii") for raw in _BANNED_B64)


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _vec(dim: int = 768, *, hot_index: int = 0, value: float = 1.0) -> list[float]:
    out = [0.0] * dim
    out[hot_index] = value
    return out


class _StubEmbed:
    def __init__(self, table: dict[str, list[float]] | None = None, dim: int = 768):
        self.table = table or {}
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            self.calls.append(text)
            out.append(self.table.get(text, [0.0] * self.dim))
        return out


class _StubKGLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def extract_entities(self, prompt: str) -> list[str]:
        self.prompts.append(prompt)
        if "subject | predicate | object | confidence" in prompt:
            return ["ARI OS | uses | Cortex | 0.9"]
        return ["ARI OS | project | 0.95", "Cortex | tool | 0.8"]


class _DownLLM:
    def extract_entities(self, prompt: str) -> list[str]:
        raise RuntimeError("offline")


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    path = tmp_path / "brain.db"
    db.init_db(path)
    return path


def _new_db(path: Path) -> Path:
    db.init_db(path)
    return path


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    path: str,
    region: str = "hippocampus",
    tier: int = 0,
    importance: float = 0.5,
    workspace: str | None = "test",
    vec: list[float] | None = None,
    layer: str = "semantic",
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, ?, ?, 0, 'x', 0)",
            (path, layer, workspace),
        )
        source_id = con.execute("SELECT id FROM source WHERE path = ?", (path,)).fetchone()[0]
        ordinal = con.execute(
            "SELECT COALESCE(MAX(ordinal), -1) + 1 FROM chunk WHERE source_id = ?",
            (source_id,),
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier
               ) VALUES (?, ?, ?, 1, 2, ?, ?, ?)""",
            (source_id, ordinal, text, region, importance, tier),
        )
        chunk_id = int(cur.lastrowid)
        if vec is not None:
            con.execute(
                "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                (chunk_id, _pack(vec)),
            )
        return chunk_id
    finally:
        con.close()


def _entity(name: str, kind: str = "concept", confidence: float = 0.8):
    return SimpleNamespace(name=name, kind=kind, confidence=confidence)


def _relation(predicate: str, confidence: float = 0.8):
    return SimpleNamespace(predicate=predicate, confidence=confidence)


def _mk_ranked(i: int, region: str, words: int = 18):
    from ari_os.tools.cortex import retrieve

    text = " ".join(f"{region}{i}_{n}" for n in range(words))
    return retrieve.RankedChunk(
        chunk_id=i,
        distance=0.1,
        region=region,
        tier=0,
        importance=0.5,
        retrieved_count=0,
        text=text,
        path=f"{region}-{i}.md",
        line_start=1,
        line_end=2,
        workspace=None,
        source="vec",
    )


def _snapshot(result) -> list[tuple[int, str, str, str]]:
    return [(c.chunk_id, c.path, c.text, c.source) for c in result.chunks]


def _iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in AUDIT_EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in AUDITABLE_SUFFIXES:
            continue
        yield path


def _scan_for_tokens(root: Path, tokens: tuple[str, ...]) -> dict[str, list[str]]:
    offenders: dict[str, list[str]] = {token: [] for token in tokens}
    for path in _iter_files(root):
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for token in tokens:
            if token in text:
                offenders[token].append(str(path.relative_to(REPO_ROOT)))
    return offenders


def _seed_surprising_graph(db_path: Path) -> list[int]:
    hippo = _insert_chunk(
        db_path,
        text="hippocampus chunk text long enough here",
        region="hippocampus",
        path="hippo.md",
    )
    wernicke = _insert_chunk(
        db_path,
        text="wernicke chunk text long enough here",
        region="wernicke",
        path="wernicke.md",
    )
    frontal = _insert_chunk(
        db_path,
        text="frontoparietal chunk text long enough here",
        region="frontoparietal",
        path="frontal.md",
    )
    hippo2 = _insert_chunk(
        db_path,
        text="second hippocampus chunk text long enough here",
        region="hippocampus",
        path="hippo2.md",
    )

    alpha = upsert_entity(db_path, ExtractedEntity("Alpha Tool", "tool", 0.9), now=100)
    beta = upsert_entity(db_path, ExtractedEntity("Beta Concept", "concept", 0.9), now=100)
    delta = upsert_entity(db_path, ExtractedEntity("Delta System", "project", 0.9), now=100)
    gamma = upsert_entity(db_path, ExtractedEntity("Gamma Tool", "tool", 0.9), now=100)

    link_entity_to_chunk(db_path, entity_id=alpha, chunk_id=hippo, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=beta, chunk_id=wernicke, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=delta, chunk_id=frontal, confidence=0.9)
    link_entity_to_chunk(db_path, entity_id=gamma, chunk_id=hippo2, confidence=0.9)

    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "uses", "Beta Concept", 0.9),
        subject_id=alpha,
        object_id=beta,
        source_chunk_id=hippo,
        now=100,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "uses", "Beta Concept", 0.9),
        subject_id=alpha,
        object_id=beta,
        source_chunk_id=hippo,
        now=110,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "mentions", "Delta System", 0.6),
        subject_id=alpha,
        object_id=delta,
        source_chunk_id=hippo,
        now=100,
    )
    upsert_relation(
        db_path,
        ExtractedRelation("Alpha Tool", "blocks", "Gamma Tool", 0.9),
        subject_id=alpha,
        object_id=gamma,
        source_chunk_id=hippo,
        now=100,
    )
    return [hippo, wernicke, frontal, hippo2]


def test_dod_p5_a_kg_extraction_populates_tables_and_is_idempotent(brain_db: Path):
    chunk_id = _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        path="kg.md",
        tier=2,
    )
    llm = _StubKGLLM()

    first = populate_kg(brain_db, llm=llm)
    second = populate_kg(brain_db, llm=llm)

    assert first.chunks_processed == 1
    assert first.entities_upserted == 2
    assert first.relations_upserted == 1
    assert second.chunks_processed == 1

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 1
        assert con.execute(
            "SELECT COUNT(*) FROM kg_entity_chunk WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()[0] == 2
        assert con.execute(
            "SELECT mention_count FROM kg_entity WHERE name = 'ari os'"
        ).fetchone()[0] == 2
        assert con.execute("SELECT evidence_count FROM kg_relation").fetchone()[0] == 2
    finally:
        con.close()


def test_dod_p5_b_kg_is_llm_gated_and_failure_backstop_is_clean(
    brain_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ari_os.tools.cortex import retrieve

    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        path="gated.md",
    )

    stats = populate_kg_incremental(brain_db, llm=None)
    assert stats == stats.__class__()
    assert len(select_unextracted(brain_db)) == 1

    config_home = tmp_path / "config-home"
    config_home.mkdir()
    (config_home / "config.json").write_text(json.dumps({"cortex": {"kg": False}}))
    monkeypatch.setenv("ARI_OS_HOME", str(config_home))
    llm = _StubKGLLM()

    stats = populate_kg_incremental(brain_db, llm=llm)
    assert stats == stats.__class__()
    assert llm.prompts == []
    assert retrieve.kg_expand(brain_db, [], per_seed=4) == []

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 0
    finally:
        con.close()

    monkeypatch.setenv("ARI_OS_KG", "1")
    monkeypatch.setenv("ARI_OS_KG_CONCURRENCY", "1")
    for i in range(3):
        _insert_chunk(
            brain_db,
            text=f"failure chunk {i} has enough text to require extraction cleanly",
            path=f"fail-{i}.md",
        )

    with pytest.raises(LLMUnavailable):
        populate_kg_incremental(brain_db, llm=_DownLLM())

    con = db.connect(brain_db)
    try:
        assert con.execute("SELECT COUNT(*) FROM kg_entity").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kg_relation").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM kg_extract_state").fetchone()[0] == 0
    finally:
        con.close()


def test_dod_p5_c_kg_query_and_retrieval_expand_surface_shared_entity(
    brain_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ari_os.tools.cortex import retrieve

    qvec = _vec(hot_index=3)
    seed = _insert_chunk(
        brain_db,
        text="Graph Engine seed memory",
        path="seed.md",
        region="frontoparietal",
        vec=qvec,
    )
    shared = _insert_chunk(
        brain_db,
        text="Shared graph implementation note",
        path="shared.md",
        region="wernicke",
    )
    decoy = _insert_chunk(brain_db, text="Unlinked note", path="decoy.md", region="vmpfc")

    graph = upsert_entity(brain_db, _entity("Graph Engine", "system"), now=100)
    sqlite = upsert_entity(brain_db, _entity("SQLite", "tool"), now=100)
    notes = upsert_entity(brain_db, _entity("Notes"), now=100)
    link_entity_to_chunk(brain_db, entity_id=graph, chunk_id=seed, confidence=0.9)
    link_entity_to_chunk(brain_db, entity_id=graph, chunk_id=shared, confidence=0.8)
    upsert_relation(
        brain_db,
        _relation("uses", confidence=0.8),
        subject_id=graph,
        object_id=sqlite,
        source_chunk_id=seed,
        now=100,
    )
    upsert_relation(
        brain_db,
        _relation("feeds", confidence=0.6),
        subject_id=notes,
        object_id=graph,
        source_chunk_id=shared,
        now=100,
    )

    assert find_entity_by_name(brain_db, "  GRAPH   ENGINE  ", kind="system")["id"] == graph
    assert [hit["id"] for hit in related_entities(brain_db, graph)] == [sqlite, notes]
    assert [hit["id"] for hit in traverse(brain_db, graph, max_depth=1)] == [sqlite, notes]

    monkeypatch.setenv("ARI_OS_KG", "1")
    result = retrieve.retrieve(
        brain_db,
        "graph query",
        embed_client=_StubEmbed({"graph query": qvec}),
        k_vector=1,
        k_sparse=0,
        k_adjacent=0,
        k_kg=4,
        kg_expand=True,
        fsrs_enabled=False,
    )

    kg_ids = {chunk.chunk_id for chunk in result.chunks if chunk.source == "kg"}
    assert shared in kg_ids
    assert seed not in kg_ids
    assert decoy not in kg_ids


def test_dod_p5_d_council_allocates_and_off_retrieval_is_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ari_os.tools.cortex import council
    from ari_os.tools.cortex import retrieve
    from ari_os.tools.cortex.council_marker import council_serving

    ranked = [_mk_ranked(i, "broca") for i in range(6)]
    ranked += [_mk_ranked(100 + i, "wernicke") for i in range(4)]
    packed, telemetry = council.allocate(
        ranked,
        240,
        salience={"broca": 1.0, "wernicke": 2.0},
    )
    assert packed
    assert telemetry["regions"]["wernicke"]["seats"] > 0
    assert telemetry["tokens_used"] <= 240 + max(len(c.text.split()) * 2 for c in packed)

    config_home = tmp_path / "home"
    config_home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(config_home))
    monkeypatch.delenv("ARI_OS_COUNCIL", raising=False)
    assert council.enabled() is False
    (config_home / "config.json").write_text(json.dumps({"cortex": {"council": True}}))
    assert council.enabled() is True

    monkeypatch.setenv("ARI_OS_COUNCIL", "0")
    db_a = _new_db(tmp_path / "p4.db")
    db_b = _new_db(tmp_path / "off.db")
    qvec = _vec(hot_index=6)
    for db_path in (db_a, db_b):
        _insert_chunk(db_path, text="hello council off path", path="hello.md", vec=qvec)

    base = retrieve.retrieve(
        db_a,
        "hello",
        embed_client=_StubEmbed({"hello": qvec}),
        k_vector=1,
        k_sparse=0,
        k_adjacent=0,
        kg_expand=False,
        fsrs_enabled=False,
    )
    off = retrieve.retrieve(
        db_b,
        "hello",
        embed_client=_StubEmbed({"hello": qvec}),
        k_vector=1,
        k_sparse=0,
        k_adjacent=0,
        kg_expand=False,
        fsrs_enabled=False,
        session_id="S-P5",
    )

    assert _snapshot(off) == _snapshot(base)
    assert council_serving("S-P5", home_dir=config_home) is False


def test_dod_p5_e_neutral_salience_contains_no_user_derived_values(tmp_path: Path):
    from ari_os.tools.cortex import council_salience, task_region_weights

    artifact = council_salience.load_artifact()

    assert artifact is not None
    assert artifact["neutral"] is True
    assert artifact["provenance"]["kind"] == "neutral-public-seed"
    assert artifact["row_mean_w"] == {"__all__": 1.0}
    assert artifact["table"] == {}
    assert set(artifact["aggregate"].values()) == {1.0}
    assert artifact.get("built_from") == {"artifact": "neutral-defaults"}

    raw = council_salience.DEFAULT_ARTIFACT_PATH.read_text()
    assert "220" not in raw
    assert "ari leavesley" not in raw.lower()
    assert "calibrated_rows\": 0" in raw
    assert council_salience.load_artifact(tmp_path / "missing.json") is None
    assert task_region_weights.compose_region_weights(
        "build",
        {"broca": 2.0},
        path=tmp_path / "missing.json",
    ) is None


def test_dod_p5_f_council_marker_round_trips_and_wander_yields(
    brain_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ari_os.tools.cortex import council_marker, wander

    home = tmp_path / "home"
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_WANDER_YIELD", "1")

    assert council_marker.council_serving("S-P5", home_dir=home) is False
    council_marker.record_tier("S-P5", "normal", home_dir=home, now=10)
    assert council_marker.council_serving("S-P5", home_dir=home) is True
    council_marker.record_tier("S-P5", "static", home_dir=home, now=20)
    assert council_marker.council_serving("S-P5", home_dir=home) is False

    focus_vec = _vec(hot_index=8)
    _insert_chunk(
        brain_db,
        text="database migration rollback checklist",
        path="focus.md",
        workspace="project-a",
        vec=focus_vec,
    )
    target = _insert_chunk(
        brain_db,
        text="ceramic kiln timing and glaze cooling pattern",
        path="associative.md",
        region="hippocampus",
        workspace="project-b",
    )
    for i in range(5):
        _insert_chunk(brain_db, text=f"local filler {i}", path=f"local-{i}.md")

    called = {"count": 0}

    def fake_serving(session_id: str, *, home_dir: Path | None = None) -> bool:
        called["count"] += 1
        assert session_id == "S-P5"
        return True

    monkeypatch.setattr(council_marker, "council_serving", fake_serving)
    embed = _StubEmbed({"database migration": focus_vec})
    yielded = wander.wander(
        brain_db,
        "database migration",
        embed_client=embed,
        session_id="S-P5",
    )

    assert called["count"] == 1
    assert yielded.fired is False
    assert embed.calls == []

    monkeypatch.setattr(council_marker, "council_serving", lambda *a, **k: False)
    drawn = wander.wander(
        brain_db,
        "database migration",
        divergence=1.0,
        embed_client=_StubEmbed({"database migration": focus_vec}),
        rng_seed=1,
        session_id="S-P5",
    )

    assert drawn.fired is True
    assert drawn.seed is not None
    assert drawn.seed.chunk_id == target


def test_dod_p5_g_dream_writes_surprising_connections_idempotently_without_llm(
    brain_db: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from ari_os.tools.cortex import dream

    seeded_ids = set(_seed_surprising_graph(brain_db))
    before_count = db.connect(brain_db).execute("SELECT COUNT(*) FROM chunk").fetchone()[0]

    def fail_get_llm(spec=None):
        raise AssertionError("surprising-connections must not resolve a backend")

    monkeypatch.setattr("ari_os.tools.cortex.distill.get_llm", fail_get_llm)

    result = dream.run_dream(brain_db, llm=None, output_dir=tmp_path)
    second = dream.run_dream(brain_db, llm=None, output_dir=tmp_path)

    assert result.surprising_connections == 2
    assert second.surprising_connections == 0
    files = list((tmp_path / "kg_reports").glob("*-surprising-connections.md"))
    assert len(files) == 1
    body = files[0].read_text()
    assert body.index("beta concept") < body.index("delta system")
    assert "bridges hippocampus to wernicke" in body
    assert "gamma tool" not in body

    con = db.connect(brain_db)
    try:
        after_count = con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0]
        remaining = {row[0] for row in con.execute("SELECT id FROM chunk").fetchall()}
    finally:
        con.close()
    assert after_count == before_count
    assert seeded_ids.issubset(remaining)


def test_dod_p5_h_suite_surface_scrub_clean():
    offenders = _scan_for_tokens(PROD_ROOT, BANNED_TOKENS)
    for token, files in offenders.items():
        assert not files, (
            f"banned token {token!r} found in production tree:\n"
            + "\n".join(f"  {path}" for path in files)
        )
