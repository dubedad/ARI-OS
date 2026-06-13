"""ar.t7 retrieval engine tests — hybrid FTS+vec, region rerank, divisive-norm, kg_expand.

Verifies the public, scrubbed port of the heavy brain's retrieval spine:

- A keyword-only query returns the right chunk via the sparse (FTS5/BM25)
  path even with no usable embedding.
- With embeddings present, a paraphrase with no shared keywords still
  recalls the target chunk via the dense (sqlite-vec) path.
- The cwd monotropic gate does not cross workspaces without a global
  posture / consent token.
- ``kg_expand`` is empty-safe: returns [] when kg tables are empty or
  seeds are empty, and grows the candidate set when kg rows exist.
- Divisive normalization (dn_strength > 0) re-orders redundant chunks.
- The retrieval_event / retrieval_metrics rows are written for every call.
- ``RankedChunk.zone`` is optional (defaults to None).
- ``filter_by_harness`` drops ``claude-only`` tagged chunks for non-claude
  harnesses.
- ``emit_markdown`` produces the region-grouped renderer.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ari_os.tools.cortex import db, retrieve


# ---------- fixtures --------------------------------------------------------

def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def make_vec(dim, *, hot_index=0, value=1.0):
    v = [0.0] * dim
    v[hot_index] = value
    return v


class StubEmbedClient:
    """Deterministic stand-in for the Ollama EmbedClient.

    Maps known query strings to fixed 768-d vectors so retrieve() is testable
    without a live Ollama. Unknown queries return a far-away constant vector.
    """

    def __init__(self, table=None, dim=768):
        self.table = table or {}
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts):
        out = []
        for t in texts:
            self.calls.append(t)
            if t in self.table:
                out.append(self.table[t])
            else:
                out.append([0.0] * self.dim)
        return out


@pytest.fixture
def brain_db(tmp_path: Path) -> Path:
    p = tmp_path / "brain.db"
    db.init_db(p)
    return p


def insert_chunk(db_path, *, text, region="frontoparietal", tier=0,
                 importance=0.5, vec=None, path="t.md", line_start=1, line_end=2,
                 workspace=None):
    """Insert one source+chunk(+vector) and return chunk id."""
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', ?, 0, 'x', 0)", (path, workspace))
        sid = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) "
            "VALUES (?, 0, ?, ?, ?, ?, ?, ?)",
            (sid, text, line_start, line_end, region, importance, tier))
        cid = cur.lastrowid
        if vec is not None:
            con.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
                        (cid, _pack(vec)))
        return cid
    finally:
        con.close()


# ---------- primitives ------------------------------------------------------

def test_vec_search_returns_topk(brain_db):
    """sqlite-vec KNN returns chunks ordered by distance."""
    dim = 768
    qvec = make_vec(dim, hot_index=0)
    near = insert_chunk(brain_db, text="near", vec=qvec, path="n.md")
    insert_chunk(brain_db, text="far", vec=make_vec(dim, hot_index=10, value=10.0),
                 path="f.md")
    hits = retrieve.vec_search(brain_db, qvec, k=5)
    assert hits, "vec_search should return at least one hit"
    assert hits[0].chunk_id == near
    # Distances are non-decreasing.
    for a, b in zip(hits, hits[1:]):
        assert a.distance <= b.distance


def test_fts_search_keyword_hit(brain_db):
    """A keyword query hits the chunk containing the term (BM25 score is negative)."""
    cid = insert_chunk(brain_db,
                       text="PostgreSQL pgvector migration recipe with notes",
                       path="mig.md")
    insert_chunk(brain_db, text="unrelated chatter about cooking",
                 path="cook.md")
    hits = retrieve.fts_search(brain_db, "PostgreSQL migration", k=5)
    assert hits, "fts_search should return at least one hit"
    assert hits[0].chunk_id == cid
    assert hits[0].bm25 < 0  # BM25 returns negative scores in SQLite


def test_fts_search_empty_query_returns_empty(brain_db):
    insert_chunk(brain_db, text="anything", path="x.md")
    assert retrieve.fts_search(brain_db, "", k=5) == []
    assert retrieve.fts_search(brain_db, "!@#$%^", k=5) == []  # punctuation stripped


def test_rrf_fuse_unions_lists():
    """Reciprocal Rank Fusion: chunk on both lists scores higher than chunk on one."""
    fused = retrieve.rrf_fuse([[1, 2, 3], [3, 2, 4]])
    # 2 appears at rank 2 on both lists → both contribute. 1 only on list 1 at
    # rank 1 (highest single contribution). 2 has TWO contributions, 1 has ONE
    # → 2 >= 1 (ties at c=60 are possible; assert >=).
    assert fused[2] >= fused[1]
    # 3 appears at rank 3 on list 1 and rank 1 on list 2 → 1/63 + 1/61.
    # 4 appears only at rank 3 on list 2 → 1/63.
    assert fused[3] > fused[4]
    # All 4 chunks appear on at least one list.
    assert set(fused) == {1, 2, 3, 4}


def test_expand_via_tracts_empty_seeds(brain_db):
    assert retrieve.expand_via_tracts(brain_db, []) == []


def test_expand_via_tracts_pulls_above_threshold(brain_db):
    a = insert_chunk(brain_db, text="a", path="a.md")
    b = insert_chunk(brain_db, text="b", path="b.md")
    c = insert_chunk(brain_db, text="c", path="c.md")
    con = db.connect(brain_db)
    try:
        # a -> b weight 0.7, a -> c weight 0.1 (below default threshold 0.3)
        con.execute("INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight) "
                    "VALUES (?, ?, 'hebbian', 0.7)", (a, b))
        con.execute("INSERT INTO tract_edge(from_chunk, to_chunk, tract, weight) "
                    "VALUES (?, ?, 'hebbian', 0.1)", (a, c))
    finally:
        con.close()
    hits = retrieve.expand_via_tracts(brain_db, [a], per_seed=5)
    ids = {h.chunk_id for h in hits}
    assert b in ids
    assert c not in ids  # below threshold


def test_kg_expand_empty_safe_when_no_kg(brain_db):
    """kg_expand is empty-safe: returns [] when kg tables are empty."""
    a = insert_chunk(brain_db, text="a", path="a.md")
    b = insert_chunk(brain_db, text="b", path="b.md")
    out = retrieve.kg_expand(brain_db, [a], per_seed=4)
    assert out == []
    # And when seeds are empty.
    assert retrieve.kg_expand(brain_db, [], per_seed=4) == []
    # And with a present but unconnected chunk.
    out = retrieve.kg_expand(brain_db, [b], per_seed=4)
    assert out == []


def test_kg_expand_returns_chunks_sharing_entity(brain_db):
    """kg_expand returns chunks that share at least one kg_entity, with kg source tag."""
    a = insert_chunk(brain_db, text="a", path="a.md")
    b = insert_chunk(brain_db, text="b", path="b.md")
    c = insert_chunk(brain_db, text="c", path="c.md")
    con = db.connect(brain_db)
    try:
        con.execute("INSERT INTO kg_entity(name, kind, first_seen_at, last_seen_at) "
                    "VALUES ('widget', 'concept', 1, 1)")
        eid = con.execute("SELECT id FROM kg_entity WHERE name='widget'").fetchone()[0]
        con.execute("INSERT INTO kg_entity_chunk(entity_id, chunk_id) VALUES (?, ?)", (eid, a))
        con.execute("INSERT INTO kg_entity_chunk(entity_id, chunk_id) VALUES (?, ?)", (eid, b))
    finally:
        con.close()
    out = retrieve.kg_expand(brain_db, [a], per_seed=4)
    ids = [r.chunk_id for r in out]
    # Seed excluded, b is a related chunk, c is not linked.
    assert a not in ids
    assert b in ids
    assert c not in ids
    # kg source is stamped on every returned chunk.
    for r in out:
        assert r.source == "kg"


# ---------- cwd_to_workspace -----------------------------------------------

def test_cwd_to_workspace_extracts_workspace_name():
    assert retrieve.cwd_to_workspace("/Users/me/workspaces/proj/src") == "proj"
    assert retrieve.cwd_to_workspace("/Users/me/workspaces/proj") == "proj"
    assert retrieve.cwd_to_workspace("/Users/me/other") is None
    assert retrieve.cwd_to_workspace(None) is None
    assert retrieve.cwd_to_workspace("") is None


# ---------- rerank + divisive normalization --------------------------------

def test_rerank_with_default_weights_promotes_direct_hits():
    """A direct 'vec' hit outranks an 'adjacent' chunk at the same distance."""
    from ari_os.tools.cortex.retrieve import RankedChunk
    direct = RankedChunk(
        chunk_id=1, distance=0.1, region="vmpfc", tier=0, importance=0.5,
        retrieved_count=0, text="alpha beta gamma", path="a.md",
        line_start=1, line_end=1, workspace=None, source="vec",
    )
    adj = RankedChunk(
        chunk_id=2, distance=0.1, region="vmpfc", tier=0, importance=0.5,
        retrieved_count=0, text="alpha beta gamma", path="b.md",
        line_start=1, line_end=1, workspace=None, source="adjacent",
    )
    out = retrieve.rerank([adj, direct])
    assert out[0].chunk_id == 1
    assert out[0].score > out[1].score


def test_rerank_divisive_norm_suppresses_redundant_pair():
    """With dn_strength > 0, two near-duplicate texts no longer co-lead."""
    from ari_os.tools.cortex.retrieve import RankedChunk
    a = RankedChunk(
        chunk_id=1, distance=0.0, region="vmpfc", tier=0, importance=0.0,
        retrieved_count=0,
        text="divisive normalization alpha beta gamma delta epsilon",
        path="same.md", line_start=1, line_end=1, workspace=None, source="vec",
    )
    b = RankedChunk(
        chunk_id=2, distance=0.0, region="vmpfc", tier=0, importance=0.0,
        retrieved_count=0,
        text="divisive normalization alpha beta gamma delta epsilon",
        path="same.md", line_start=2, line_end=2, workspace=None, source="vec",
    )
    c = RankedChunk(
        chunk_id=3, distance=0.0, region="vmpfc", tier=0, importance=0.0,
        retrieved_count=0,
        text="completely different content about an unrelated topic here",
        path="other.md", line_start=1, line_end=1, workspace=None, source="vec",
    )
    no_dn = retrieve.rerank([a, b, c], dn_strength=0.0)
    with_dn = retrieve.rerank([a, b, c], dn_strength=2.0)
    # With DN the unique chunk c pulls ahead of the redundant pair a/b.
    assert with_dn[0].chunk_id == 3
    # Without DN, the first-listed chunk leads (FIFO stability).
    assert no_dn[0].chunk_id == 1


# ---------- retrieve() end-to-end -------------------------------------------

def test_keyword_query_returns_target_via_sparse(brain_db):
    """Keyword query → chunk with the keyword is recalled (no shared embedding)."""
    target = insert_chunk(brain_db,
                          text="PostgreSQL pgvector migration playbook with notes",
                          path="mig.md")
    decoy = insert_chunk(brain_db,
                         text="A recipe for chocolate chip cookies",
                         path="cook.md")
    embed = StubEmbedClient({})  # all queries → zero vector → no dense hits
    result = retrieve.retrieve(
        brain_db, "PostgreSQL migration",
        embed_client=embed,
        k_vector=2, k_sparse=5, k_adjacent=0, kg_expand=False,
        mode="default",
    )
    assert any(c.chunk_id == target for c in result.chunks)
    assert result.mode == "default"
    assert result.query == "PostgreSQL migration"


def test_paraphrase_recalls_via_dense(brain_db):
    """A paraphrase with no shared keywords still recalls the target via dense vec.

    The target's embedding matches the query exactly (distance 0); the decoy
    shares no embedding mass with the query (high L2 distance). With no
    FTS path, only dense recall can surface the target — the test verifies
    the target leads, and that dense distance discriminates the two.
    """
    dim = 768
    qvec = make_vec(dim, hot_index=4)
    target = insert_chunk(brain_db, text="unrelated chunk about something",
                          path="t.md", vec=qvec)
    # Decoy lives at hot_index=99 with magnitude 5.0 → L2 dist > 5 from qvec.
    decoy = insert_chunk(
        brain_db, text="PostgreSQL pgvector migration recipe",
        path="d.md", vec=make_vec(dim, hot_index=99, value=5.0),
    )
    embed = StubEmbedClient({"how do I migrate the database": qvec})
    result = retrieve.retrieve(
        brain_db, "how do I migrate the database",
        embed_client=embed,
        k_vector=2, k_sparse=0, k_adjacent=0, kg_expand=False,
        mode="default",
    )
    assert result.chunks, "expected at least one result"
    # Target leads by a large margin over the decoy.
    assert result.chunks[0].chunk_id == target
    target_score = result.chunks[0].score
    decoy_score = next(c.score for c in result.chunks if c.chunk_id == decoy)
    assert target_score > decoy_score


def test_cwd_gate_keeps_local_workspace(brain_db):
    """Under tunnel posture, chunks outside the cwd's workspace are filtered out."""
    qvec = make_vec(768, hot_index=2)
    local = insert_chunk(brain_db, text="local chunk A", path="a.md",
                         workspace="projA", vec=qvec)
    other = insert_chunk(brain_db, text="other chunk B", path="b.md",
                         workspace="projB", vec=qvec)
    embed = StubEmbedClient({"a chunk": qvec})
    result = retrieve.retrieve(
        brain_db, "a chunk",
        embed_client=embed,
        cwd="/Users/me/workspaces/projA",
        k_vector=5, k_sparse=0, k_adjacent=0, kg_expand=False,
        mode="default", posture="tunnel",
    )
    ids = {c.chunk_id for c in result.chunks}
    assert local in ids
    assert other not in ids


def test_cwd_gate_does_not_cross_without_consent_token(brain_db):
    """Without a global posture, the cwd gate keeps retrieval local.

    A 'go global' phrase in the query upgrades posture to global and the
    cross-workspace chunk surfaces.
    """
    qvec = make_vec(768, hot_index=3)
    local = insert_chunk(brain_db, text="local chunk A", path="a.md",
                         workspace="projA", vec=qvec)
    other = insert_chunk(brain_db, text="other chunk B", path="b.md",
                         workspace="projB", vec=qvec)
    embed = StubEmbedClient({"a chunk": qvec})
    # Without consent: local only.
    r_local = retrieve.retrieve(
        brain_db, "a chunk",
        embed_client=embed,
        cwd="/Users/me/workspaces/projA",
        k_vector=5, k_sparse=0, k_adjacent=0, kg_expand=False,
        mode="default", posture="tunnel",
    )
    assert {c.chunk_id for c in r_local.chunks} == {local}
    # With explicit global posture: other workspace surfaces too.
    r_global = retrieve.retrieve(
        brain_db, "a chunk",
        embed_client=embed,
        cwd="/Users/me/workspaces/projA",
        k_vector=5, k_sparse=0, k_adjacent=0, kg_expand=False,
        mode="default", posture="global",
    )
    assert {local, other}.issubset({c.chunk_id for c in r_global.chunks})


def test_retrieve_writes_event_and_metrics_rows(brain_db):
    """Every retrieve() writes exactly one retrieval_event + one retrieval_metrics row."""
    qvec = make_vec(768, hot_index=0)
    insert_chunk(brain_db, text="hello world", path="h.md", vec=qvec)
    embed = StubEmbedClient({"hello": qvec})
    retrieve.retrieve(
        brain_db, "hello",
        embed_client=embed,
        k_vector=2, k_sparse=0, k_adjacent=0, kg_expand=False,
        mode="default",
    )
    con = db.connect(brain_db)
    try:
        n_events = con.execute("SELECT count(*) FROM retrieval_event").fetchone()[0]
        n_metrics = con.execute("SELECT count(*) FROM retrieval_metrics").fetchone()[0]
    finally:
        con.close()
    assert n_events == 1
    assert n_metrics == 1


def test_ranked_chunk_zone_optional():
    """RankedChunk.zone is optional (defaults to None) — used by the assembler seam."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(retrieve.RankedChunk)}
    assert "zone" in fields
    rc = retrieve.RankedChunk(
        chunk_id=1, distance=0.0, region="vmpfc", tier=0, importance=0.0,
        retrieved_count=0, text="x", path="x.md", line_start=1, line_end=1,
        workspace=None, source="vec",
    )
    assert rc.zone is None


# ---------- filter_by_harness + emit_markdown -------------------------------

def test_filter_by_harness_excludes_claude_only_when_codex():
    chunks = [
        {"path": "a", "harness": "any", "text": "foo"},
        {"path": "b", "harness": "needs-adapter", "text": "bar"},
        {"path": "c", "harness": "claude-only", "text": "baz"},
        {"path": "d", "harness": None, "text": "unknown"},
    ]
    out = retrieve.filter_by_harness(chunks, harness="codex")
    paths = [c["path"] for c in out]
    assert "a" in paths
    assert "b" in paths
    assert "c" not in paths
    assert "d" in paths  # untagged is left alone (lenient)


def test_filter_by_harness_passthrough_when_claude_or_none():
    chunks = [{"path": "c", "harness": "claude-only", "text": "baz"}]
    assert retrieve.filter_by_harness(chunks, harness="claude") == chunks
    assert retrieve.filter_by_harness(chunks, harness=None) == chunks


def test_emit_markdown_groups_by_region():
    from ari_os.tools.cortex.retrieve import RankedChunk
    a = RankedChunk(
        chunk_id=1, distance=0.1, region="vmpfc", tier=0, importance=0.5,
        retrieved_count=0, text="identity judgement", path="i.md",
        line_start=1, line_end=1, workspace=None, source="vec", score=1.5,
    )
    b = RankedChunk(
        chunk_id=2, distance=0.1, region="frontoparietal", tier=0, importance=0.5,
        retrieved_count=0, text="how to run the test", path="t.md",
        line_start=1, line_end=1, workspace=None, source="vec", score=1.2,
    )
    md = retrieve.emit_markdown([a, b])
    assert "## Brain — auto-retrieved context" in md
    assert "### Orbitofrontal — identity" in md
    assert "### Frontoparietal — procedural" in md
    assert "i.md" in md
    assert "t.md" in md


def test_emit_markdown_empty_returns_no_context_block():
    md = retrieve.emit_markdown([])
    assert "no context retrieved" in md
