"""ar.t8 context assembly tests — context_assembler + context_block (the regioned block).

Verifies the public, scrubbed port of the heavy brain's context assembly:

- ``context_assembler.zone_of`` maps the published region/tier combos onto
  the persona / episodic / semantic zones used by every downstream consumer.
- ``assemble`` honours per-zone ratios AND the global token budget, and
  fills leftover with any remaining ranked chunks in rank order.
- ``ContextBlock.render()`` is the exact concatenation of the four strata
  with no separator bytes, and two renders on the same input are
  byte-stable.
- The cache-stable strata (eternal + session) tolerate volatile-suffix
  changes — fingerprint test asserts this contract.
- ``render_eternal`` / ``render_session`` produce a stable (path, line_start)
  sort with no scores or counts leaking into the first line.
- End-to-end: assembling a multi-region ranked list and feeding it into
  the markdown renderer produces a block with >=2 region headers and
  scored lines.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from ari_os.tools.cortex import context_assembler as ca
from ari_os.tools.cortex import context_block as cb
from ari_os.tools.cortex import retrieve


# ---------- assembler: zone mapping ---------------------------------------


def test_zone_assignment_vmpfc_always_persona():
    assert ca.zone_of("vmpfc", 0) == "persona"
    assert ca.zone_of("vmpfc", 2) == "persona"
    assert ca.zone_of("vmpfc", 4) == "persona"


def test_zone_assignment_episodic_low_tier_language_regions():
    assert ca.zone_of("hippocampus", 0) == "episodic"
    assert ca.zone_of("broca", 1) == "episodic"
    assert ca.zone_of("wernicke", 1) == "episodic"


def test_zone_assignment_semantic_for_distilled_tiers():
    # tier>=2 anywhere is semantic (distilled material)
    assert ca.zone_of("parietal", 2) == "semantic"
    assert ca.zone_of("frontoparietal", 0) == "semantic"  # not in episodic set, not persona/tier>=4
    assert ca.zone_of("hippocampus", 2) == "semantic"


# ---------- assembler: greedy budget packing ------------------------------


@dataclass
class FakeChunk:
    chunk_id: int
    text: str
    region: str
    tier: int
    zone: str | None = None


def _toks(s: str) -> int:
    return int(len(s.split()) * 1.3)


def test_assemble_respects_budget_and_fills():
    ranked = [
        FakeChunk(chunk_id=i, text="word " * 10, region="hippocampus", tier=0)
        for i in range(20)
    ]
    budget = _toks("word " * 10) * 5 + 1   # room for ~5 chunks
    packed = ca.assemble(
        ranked, token_budget=budget,
        ratios={"persona": 0.2, "episodic": 0.4, "semantic": 0.4},
    )
    # 1 <= len <= 6 (budget cap + 1 leftover fill)
    assert 1 <= len(packed) <= 6
    # Preserved rank order
    assert [c.chunk_id for c in packed] == sorted(c.chunk_id for c in packed)
    # Every accepted chunk got a zone label
    assert all(hasattr(c, "zone") and c.zone for c in packed)


def test_assemble_balances_zones_by_ratio():
    # Build a ranked list with mixed regions, then assert the per-zone fill
    # is roughly proportional to the ratios. With a large enough budget
    # pass 1 will saturate every zone; pass 2 may not fire.
    ranked: list[FakeChunk] = []
    for i in range(10):
        ranked.append(FakeChunk(chunk_id=i,     text="alpha " * 8, region="vmpfc",       tier=0))   # persona
    for i in range(10, 20):
        ranked.append(FakeChunk(chunk_id=i,     text="hippo " * 8, region="hippocampus", tier=0))   # episodic
    for i in range(20, 30):
        ranked.append(FakeChunk(chunk_id=i,     text="sem " * 8,   region="parietal",    tier=2))   # semantic
    # Use a generous per-chunk text so pass 1 is the binding constraint;
    # 5 chunks per zone fits inside the ratio split.
    packed = ca.assemble(
        ranked, token_budget=10_000,
        ratios={"persona": 0.2, "episodic": 0.4, "semantic": 0.4},
    )
    counts = {"persona": 0, "episodic": 0, "semantic": 0}
    for c in packed:
        counts[c.zone] += 1
    # All three zones should be touched, persona should be smallest.
    assert all(v > 0 for v in counts.values())
    assert counts["persona"] <= counts["episodic"]
    assert counts["persona"] <= counts["semantic"]


def test_assemble_annotates_zone():
    ranked = [
        FakeChunk(chunk_id=1, text="x y z", region="vmpfc", tier=0),
        FakeChunk(chunk_id=2, text="x y z", region="hippocampus", tier=0),
    ]
    packed = ca.assemble(
        ranked, token_budget=10_000,
        ratios={"persona": 0.5, "episodic": 0.5, "semantic": 0.0},
    )
    by_id = {c.chunk_id: c for c in packed}
    assert by_id[1].zone == "persona"
    assert by_id[2].zone == "episodic"


def test_assemble_empty_input_returns_empty():
    packed = ca.assemble(
        [], token_budget=1000,
        ratios={"persona": 0.2, "episodic": 0.4, "semantic": 0.4},
    )
    assert packed == []


# ---------- ContextBlock: render & bounded --------------------------------


def _block() -> cb.ContextBlock:
    return cb.ContextBlock(
        eternal_prefix="## Brain - pinned memory (Tier 4)\n\n[a.md:L1-L2]\nfact\n\n",
        session_prefix="## Brain - session\n\ndigest line\n\n",
        volatile_suffix="## Brain - retrieved\n\n- hit (score=0.91)\n\n",
        user_input="what changed today?",
    )


def test_render_is_exact_concatenation():
    b = _block()
    assert b.render() == (
        b.eternal_prefix + b.session_prefix + b.volatile_suffix + b.user_input
    )


def test_render_adds_no_separator_bytes():
    b = cb.ContextBlock(
        eternal_prefix="A",
        session_prefix="B",
        volatile_suffix="C",
        user_input="D",
    )
    assert b.render() == "ABCD"


def test_render_byte_stable_across_two_calls():
    """Byte-stability is the core cache contract: same input -> same output."""
    b = _block()
    assert b.render() == b.render()


def test_render_bounded_under_budget_is_byte_identical_to_render():
    b = _block()
    assert b.render_bounded(10_000) == b.render()


def test_render_bounded_trims_only_volatile_tail():
    b = cb.ContextBlock(
        eternal_prefix="E" * 50 + "\n",
        session_prefix="S" * 50 + "\n",
        volatile_suffix="para1\n\npara2\n\npara3\n",
        user_input="USER",
    )
    out = b.render_bounded(120)
    assert out.startswith(b.eternal_prefix + b.session_prefix)
    assert out.endswith("USER")
    assert "para3" not in out
    assert len(out) <= 120


def test_render_bounded_can_drop_volatile_entirely():
    b = cb.ContextBlock(
        eternal_prefix="E\n",
        session_prefix="S\n",
        volatile_suffix="V" * 500,
        user_input="U",
    )
    out = b.render_bounded(10)
    assert out == "E\nS\nU"


def test_render_bounded_loud_fail_when_fixed_strata_exceed_budget():
    b = cb.ContextBlock(
        eternal_prefix="E" * 100,
        session_prefix="S" * 100,
        volatile_suffix="",
        user_input="U" * 100,
    )
    with pytest.raises(ValueError, match="exceed"):
        b.render_bounded(50)


def test_fingerprint_stable_and_sensitive():
    a, b = _block(), _block()
    assert a.fingerprint() == b.fingerprint()

    c = _block()
    c.volatile_suffix = "totally different"
    # Volatile changes must NOT move either fingerprint.
    assert c.fingerprint() == a.fingerprint()

    d = _block()
    d.eternal_prefix += "x"
    assert d.fingerprint()[0] != a.fingerprint()[0]
    assert d.fingerprint()[1] != a.fingerprint()[1]

    e = _block()
    e.session_prefix += "x"
    assert e.fingerprint()[0] == a.fingerprint()[0]
    assert e.fingerprint()[1] != a.fingerprint()[1]


# ---------- render_eternal / render_session ------------------------------


def test_render_eternal_sorted_by_path_then_line_never_score():
    # deliberately passed in "rank" order; must come out (path, line_start) order
    rows = [
        ("z.md", 10, 12, "zebra fact"),
        ("a.md", 5, 8, "alpha fact two"),
        ("a.md", 1, 4, "alpha fact one"),
    ]
    out = cb.render_eternal(rows)
    assert out.index("[a.md:L1-L4]") < out.index("[a.md:L5-L8]") < out.index("[z.md:L10-L12]")
    assert "score" not in out
    assert out.endswith("\n")


def test_render_eternal_empty_is_stable_header_only():
    assert cb.render_eternal([]) == cb.render_eternal([])
    assert cb.render_eternal([]).endswith("\n")


def test_render_session_deterministic_and_sorted():
    digests = [
        ("digests/2026-06-11.md", 9, 20, "later digest"),
        ("digests/2026-06-10.md", 1, 8, "earlier digest"),
    ]
    one = cb.render_session("## Brain - recent workspace findings\n\n- a finding\n", digests)
    two = cb.render_session("## Brain - recent workspace findings\n\n- a finding\n", digests)
    assert one == two
    assert one.index("earlier digest") < one.index("later digest")
    assert one.endswith("\n")


def test_render_session_empty_inputs_render_empty():
    assert cb.render_session("", []) == ""


# ---------- end-to-end: assembled chunks -> regioned block -----------------


def test_assembled_ranked_chunks_render_regioned_block():
    """The full pipeline: a mixed-region ranked list -> assemble -> emit_markdown
    must produce a block with >=2 region headers and scored lines."""
    ranked = [
        retrieve.RankedChunk(
            chunk_id=1, distance=0.30, region="vmpfc", tier=0,
            importance=0.0, retrieved_count=0,
            text="Identity / voice note.", path="identity.md",
            line_start=1, line_end=2, workspace=None,
            source="vec", score=0.91,
        ),
        retrieve.RankedChunk(
            chunk_id=2, distance=0.50, region="hippocampus", tier=0,
            importance=0.0, retrieved_count=0,
            text="What happened in the last session.",
            path="episodes/2026-06-13.md",
            line_start=10, line_end=20, workspace=None,
            source="sparse", score=0.55,
        ),
        retrieve.RankedChunk(
            chunk_id=3, distance=0.80, region="parietal", tier=2,
            importance=0.0, retrieved_count=0,
            text="Workspace overview of the repo.",
            path="project.md",
            line_start=1, line_end=10, workspace=None,
            source="adjacent", score=0.20,
        ),
    ]
    packed = ca.assemble(
        ranked, token_budget=10_000,
        ratios={"persona": 0.2, "episodic": 0.4, "semantic": 0.4},
    )
    assert len(packed) >= 2
    md = retrieve.emit_markdown(packed, mode="default")

    # >=2 region headers
    region_markers = [
        "Orbitofrontal", "Frontoparietal", "Hippocampus", "Wernicke",
        "Broca", "Occipital", "Parietal",
    ]
    hits = sum(1 for m in region_markers if m in md)
    assert hits >= 2, f"expected >=2 region headers, got: {md!r}"

    # Scored lines present
    assert "score=" in md
    # Path:line anchors present
    assert "[identity.md" in md
    assert "[episodes/2026-06-13.md" in md
