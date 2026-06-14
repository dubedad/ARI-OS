"""P5 KG config toggles, CLI surface, MCP handlers, and retrieval gate."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from ari_os.tools.cortex import config, db, mcp_tools, retrieve
from ari_os.tools.cortex.cortex import main
from ari_os.tools.cortex.kg.store import link_entity_to_chunk, upsert_entity, upsert_relation


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    monkeypatch.delenv("ARI_OS_KG", raising=False)
    monkeypatch.delenv("ARI_OS_COUNCIL", raising=False)
    monkeypatch.delenv("ARI_OS_KG_LLM", raising=False)
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    path = ari_home / "brain.db"
    db.init_db(path)
    return path


class StubKGLLM:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def extract_entities(self, prompt: str) -> list[str]:
        self.prompts.append(prompt)
        if "subject | predicate | object | confidence" in prompt:
            return ["ARI OS | uses | Cortex | 0.9"]
        return ["ARI OS | project | 0.95", "Cortex | tool | 0.8"]


class StubEmbed:
    def __init__(self, table: dict[str, list[float]]) -> None:
        self.table = table

    def embed(self, texts):
        return [self.table[text] for text in texts]


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _entity(name: str, kind: str = "concept", confidence: float = 0.7):
    return SimpleNamespace(name=name, kind=kind, confidence=confidence)


def _relation(predicate: str, confidence: float = 0.7):
    return SimpleNamespace(predicate=predicate, confidence=confidence)


def _insert_chunk(
    db_path: Path,
    *,
    text: str,
    path: str,
    region: str = "hippocampus",
    tier: int = 0,
    vec: list[float] | None = None,
) -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', 'tests', 0, 'x', 0)",
            (path,),
        )
        source_id = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, importance, distillation_tier) "
            "VALUES (?, 0, ?, 1, 1, ?, 0.5, ?)",
            (source_id, text, region, tier),
        )
        chunk_id = int(cur.lastrowid)
        if vec is not None:
            con.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)", (chunk_id, _pack(vec)))
        return chunk_id
    finally:
        con.close()


def _seed_kg(db_path: Path) -> tuple[int, int]:
    first = _insert_chunk(
        db_path,
        text="ARI OS uses Cortex for local retrieval.",
        path="first.md",
    )
    second = _insert_chunk(
        db_path,
        text="Cortex keeps graph context beside chunks.",
        path="second.md",
    )
    ari = upsert_entity(db_path, _entity("ARI OS", kind="project", confidence=0.95), now=100)
    cortex = upsert_entity(db_path, _entity("Cortex", kind="tool", confidence=0.8), now=100)
    link_entity_to_chunk(db_path, entity_id=ari, chunk_id=first, confidence=0.95)
    link_entity_to_chunk(db_path, entity_id=cortex, chunk_id=first, confidence=0.8)
    link_entity_to_chunk(db_path, entity_id=cortex, chunk_id=second, confidence=0.75)
    upsert_relation(
        db_path,
        _relation("uses", confidence=0.9),
        subject_id=ari,
        object_id=cortex,
        source_chunk_id=first,
        now=100,
    )
    return first, second


def test_config_toggles_read_config_and_env_overrides(ari_home: Path, monkeypatch: pytest.MonkeyPatch):
    assert config.kg_enabled() is False
    assert config.council_enabled() is False

    (ari_home / "config.json").write_text(json.dumps({"cortex": {"kg": True, "council": True}}))
    assert config.kg_enabled() is True
    assert config.council_enabled() is True

    monkeypatch.setenv("ARI_OS_KG", "0")
    monkeypatch.setenv("ARI_OS_COUNCIL", "off")
    assert config.kg_enabled() is False
    assert config.council_enabled() is False


def test_kg_extract_stats_and_list_cli_over_seeded_sweep(
    brain_db: Path,
    ari_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        path="kg.md",
        tier=0,
    )
    (ari_home / "config.json").write_text(json.dumps({"cortex": {"kg": True}}))
    monkeypatch.setattr("ari_os.tools.cortex.llm.get_llm", lambda spec=None: StubKGLLM())

    extracted = CliRunner().invoke(main, ["kg", "extract", "--limit", "1"])
    assert extracted.exit_code == 0, extracted.output
    assert "chunks=1" in extracted.output
    assert "entities=2" in extracted.output
    assert "relations=1" in extracted.output

    stats = CliRunner().invoke(main, ["kg", "stats"])
    assert stats.exit_code == 0, stats.output
    assert "entities=2" in stats.output
    assert "relations=1" in stats.output

    listed = CliRunner().invoke(main, ["kg", "list", "--kind", "tool"])
    assert listed.exit_code == 0, listed.output
    assert "cortex" in listed.output
    assert "ari os" not in listed.output


def test_kg_extract_off_exits_zero_without_network(
    brain_db: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex to retrieve useful memory context for local workflows.",
        path="kg.md",
    )

    def fail_get_llm(spec=None):
        raise AssertionError("kg off must not resolve an LLM backend")

    monkeypatch.setattr("ari_os.tools.cortex.llm.get_llm", fail_get_llm)
    result = CliRunner().invoke(main, ["kg", "extract", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert "kg off" in result.output


def test_kg_expand_off_injects_nothing_even_when_rows_exist(
    brain_db: Path,
    ari_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    qvec = [0.0] * 768
    qvec[0] = 1.0
    first = _insert_chunk(
        brain_db,
        text="ARI OS uses Cortex for local retrieval.",
        path="first.md",
        vec=qvec,
    )
    second = _insert_chunk(
        brain_db,
        text="Cortex keeps graph context beside chunks.",
        path="second.md",
        vec=None,
    )
    cortex = upsert_entity(brain_db, _entity("Cortex", kind="tool", confidence=0.8), now=100)
    link_entity_to_chunk(brain_db, entity_id=cortex, chunk_id=first, confidence=0.8)
    link_entity_to_chunk(brain_db, entity_id=cortex, chunk_id=second, confidence=0.75)
    (ari_home / "config.json").write_text(json.dumps({"cortex": {"kg": False}}))

    result = retrieve.retrieve(
        brain_db,
        query="cortex retrieval",
        embed_client=StubEmbed({"cortex retrieval": qvec}),
        k_vector=1,
        k_sparse=0,
        k_adjacent=0,
        kg_expand=True,
        posture="global",
    )

    assert [chunk.chunk_id for chunk in result.chunks] == [first]


def test_mcp_entities_and_relations_return_seeded_rows(brain_db: Path):
    _seed_kg(brain_db)

    entities = mcp_tools.entities(brain_db, kind="tool", k=50)
    assert entities == [
        {
            "id": entities[0]["id"],
            "name": "cortex",
            "kind": "tool",
            "confidence": 0.8,
            "mention_count": 1,
        }
    ]

    relations = mcp_tools.relations(brain_db, entity="ari os", k=50)
    assert relations == [
        {
            "id": relations[0]["id"],
            "subject": "ari os",
            "predicate": "uses",
            "object": "cortex",
            "confidence": 0.9,
            "evidence_count": 1,
        }
    ]
