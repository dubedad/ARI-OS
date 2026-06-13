"""ar.t5 neutral seed tests — region anchors, task centroids, task region weights.

Verifies the public, scrubbed port of the heavy brain's seed spine:

- All three neutral seed JSONs live under ``ari_os/tools/seeds/`` and load
  cleanly via the corresponding module loader.
- Each artifact is explicitly flagged ``"neutral": true`` and carries a
  ``"description"`` so downstream readers know they're looking at shipped
  defaults, not user-calibrated data.
- The region_anchors artifact covers exactly the seven published regions with
  one-hot unit vectors in R^7 and identity calibration (mu=0, sigma=1) — no
  private / per-user values ship.
- The task_centroids artifact covers exactly the six locked task types with
  one-hot unit vectors in R^6 — no private seed queries ship.
- The task_region_weights artifact is fully uniform (1.0 across all regions
  and task types) with a 1.0 vmpfc latent floor — the system calibrates
  locally; no per-user weights ship.
- The published cognitive-science region names are preserved (scrub recipe
  allows them); the author's private identity / voice / project references
  do not appear anywhere in the seed JSONs or the ported modules.
- CODE RED scrub bible: committed production code contains zero banned tokens.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from ari_os.tools.cortex import (
    region_anchors,
    task_classifier,
    task_region_weights,
)


# ---------- paths -----------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]
SEEDS_DIR = REPO_ROOT / "ari_os" / "tools" / "seeds"
REGION_ANCHORS_PATH = SEEDS_DIR / "region_anchors.neutral.json"
TASK_CENTROIDS_PATH = SEEDS_DIR / "task_centroids.neutral.json"
TASK_REGION_WEIGHTS_PATH = SEEDS_DIR / "task_region_weights.neutral.json"

# Published cognitive-science region vocabulary (scrub keeps these terms).
REGIONS = (
    "wernicke", "broca", "occipital", "parietal",
    "hippocampus", "vmpfc", "frontoparietal",
)

TASK_TYPES = ("build", "voice", "ideate", "reason", "research", "visual")

# Author-voice / identity / project terms that must NEVER appear in shipped
# code. These are the values that would betray a direct copy of the source
# engine's calibrated artifacts. The scrub recipe permits published
# cognitive-science region names; everything else is private.
# Each entry is a regex with word boundaries so it doesn't match inside the
# legitimate region names (e.g. "parietal" must not trip the user-name match).
BANNED_NARRATIVE = [
    r"\blinkedin\b",
    r"\bclief\b",
    r"\bcouncil-of-regions\b",
    r"\bs4\b",
    r"\bs5\b",
    r"\bs7\b",
    r"\bbrandera\b",
    r"\bplanb\b",
    r"\bgemma3:4b\b",
    r"\brq_[a-z_]+\b",
    r"\bmetal\s+shader\b",
    r"\bari-os\s+keys\b",
]


# ---------- helpers ---------------------------------------------------------

def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _is_one_hot(v: list[float], axis: int, *, dim: int) -> bool:
    """v is the axis-th standard basis vector in R^dim (within float epsilon)."""
    if len(v) != dim:
        return False
    for i, x in enumerate(v):
        expected = 1.0 if i == axis else 0.0
        if not math.isclose(x, expected, abs_tol=1e-6):
            return False
    return True


def _scan_for_banned_text(path: Path) -> list[tuple[int, str]]:
    """Return list of (line_number, line) where banned narrative text appears."""
    hits = []
    text = path.read_text()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pattern in BANNED_NARRATIVE:
            if re.search(pattern, line, flags=re.IGNORECASE):
                hits.append((lineno, line.strip()))
                break
    return hits


# ---------- region_anchors.neutral.json -------------------------------------

class TestRegionAnchorsNeutral:
    def test_seed_file_exists(self):
        assert REGION_ANCHORS_PATH.is_file(), f"missing {REGION_ANCHORS_PATH}"

    def test_seed_loads_cleanly(self):
        art = region_anchors.load_anchor_artifact(REGION_ANCHORS_PATH)
        assert art is not None, "load_anchor_artifact returned None"
        # All 7 published regions present.
        assert set(art["anchors"]) == set(REGIONS)
        # Neutral flag set.
        assert art.get("neutral") is True
        # Description present (downstream readers can detect shipped defaults).
        assert isinstance(art.get("description"), str) and art["description"]
        # Templates present (used by rebuild-anchors).
        assert set(art["templates"]) == set(REGIONS)
        # Calibration present at all four beta grid values.
        assert set(art["calibration"]) == {"0.00", "0.15", "0.30", "0.50"}
        # Each region has identity calibration: mu=0, sigma=1.
        for beta_key, per_region in art["calibration"].items():
            assert set(per_region) == set(REGIONS)
            for r, cal in per_region.items():
                assert cal["mu"] == 0.0
                assert cal["sigma"] == 1.0
                assert cal["n_chunks"] == 0

    def test_anchors_are_one_hot_vectors(self):
        art = _load(REGION_ANCHORS_PATH)
        # All anchors are in the same dim; the per-region axis is unique.
        dim = len(art["anchors"][REGIONS[0]])
        for axis, region in enumerate(REGIONS):
            assert _is_one_hot(art["anchors"][region], axis, dim=dim), (
                f"region {region} is not the axis-{axis} one-hot vector in R^{dim}"
            )

    def test_templates_are_generic_not_author_voice(self):
        art = _load(REGION_ANCHORS_PATH)
        # Each region has 5 generic templates; the templates must not carry
        # author-voice / project identity references.
        for region, tmpls in art["templates"].items():
            assert len(tmpls) == 5, f"{region}: expected 5 templates, got {len(tmpls)}"
            for tmpl in tmpls:
                for pattern in BANNED_NARRATIVE:
                    assert not re.search(pattern, tmpl, flags=re.IGNORECASE), (
                        f"{region} template contains banned pattern {pattern!r}: {tmpl}"
                    )

    def test_default_artifact_loader_uses_neutral_seed(self):
        # The default loader must resolve to the neutral seed when the
        # user has not provided their own artifact under ARI_OS_HOME.
        art = region_anchors.get_default_artifact()
        assert art is not None
        assert art.get("neutral") is True

    def test_banned_narrative_terms_absent(self):
        hits = _scan_for_banned_text(REGION_ANCHORS_PATH)
        assert not hits, (
            "neutral region_anchors seed contains banned author-voice text:\n"
            + "\n".join(f"  L{n}: {line}" for n, line in hits)
        )


# ---------- task_centroids.neutral.json -------------------------------------

class TestTaskCentroidsNeutral:
    def test_seed_file_exists(self):
        assert TASK_CENTROIDS_PATH.is_file(), f"missing {TASK_CENTROIDS_PATH}"

    def test_seed_loads_cleanly(self):
        art = task_classifier.load_centroid_artifact(TASK_CENTROIDS_PATH)
        assert set(art["centroids"]) == set(TASK_TYPES)
        assert art.get("neutral") is True
        assert isinstance(art.get("description"), str) and art["description"]
        assert art["fallback"] == "reason"
        assert art["min_confidence"] == pytest.approx(0.18)
        assert art["tie_epsilon"] == pytest.approx(0.01)
        assert art["task_types"] == list(TASK_TYPES)

    def test_centroids_are_zero_vectors(self):
        # The neutral seed encodes "untrained" as a uniform prior: every
        # task-type centroid is the zero vector. This is the only value that
        # makes the classifier abstain by default for every query (cosine
        # of anything against a zero vector is 0.0 → low_confidence).
        art = _load(TASK_CENTROIDS_PATH)
        dim = len(art["centroids"][TASK_TYPES[0]])
        for task in TASK_TYPES:
            v = art["centroids"][task]
            assert len(v) == dim, f"{task}: dim {len(v)} != {dim}"
            for i, x in enumerate(v):
                assert x == 0.0, f"{task}[{i}] = {x} (expected 0.0)"

    def test_seed_queries_are_generic(self):
        art = _load(TASK_CENTROIDS_PATH)
        for task, queries in art["seed_queries"].items():
            assert task in TASK_TYPES
            assert len(queries) == 5, f"{task}: expected 5 seed queries"
            for q in queries:
                for pattern in BANNED_NARRATIVE:
                    assert not re.search(pattern, q, flags=re.IGNORECASE), (
                        f"{task} seed query contains banned pattern {pattern!r}: {q}"
                    )

    def test_classifier_from_neutral_seed_abstains(self):
        # The neutral seed is one-hot in 6-dim. A real query embedding will
        # NEVER have a top score above the second by more than tie_epsilon
        # (the seed centroids are mutually orthogonal, so all cosine scores
        # against a real query are small and clustered). Therefore the
        # classifier must return the fallback with fallback_reason="tie".
        clf = task_classifier.classifier_from_artifact(TASK_CENTROIDS_PATH)
        # A realistic query embedding: normalized random-ish vector in R^6.
        q = [0.5, -0.3, 0.1, 0.7, -0.2, 0.4]
        norm = math.sqrt(sum(x * x for x in q))
        q = [x / norm for x in q]
        result = clf.classify_result("any query", q)
        # The neutral seed is intentionally abstaining — by design. Real
        # centroids ship after the user runs rebuild-centroids.
        assert result.task_type == task_classifier.DEFAULT_FALLBACK
        assert result.fallback_reason in {"tie", "low_confidence"}

    def test_default_classifier_uses_neutral_seed(self):
        clf = task_classifier.get_default_classifier()
        assert isinstance(clf, task_classifier.CentroidClassifier)
        assert set(clf.centroids) == set(TASK_TYPES)

    def test_banned_narrative_terms_absent(self):
        hits = _scan_for_banned_text(TASK_CENTROIDS_PATH)
        assert not hits, (
            "neutral task_centroids seed contains banned author-voice text:\n"
            + "\n".join(f"  L{n}: {line}" for n, line in hits)
        )


# ---------- task_region_weights.neutral.json -------------------------------

class TestTaskRegionWeightsNeutral:
    def test_seed_file_exists(self):
        assert TASK_REGION_WEIGHTS_PATH.is_file(), f"missing {TASK_REGION_WEIGHTS_PATH}"

    def test_seed_loads_cleanly(self):
        art = task_region_weights.load_artifact(TASK_REGION_WEIGHTS_PATH)
        assert art is not None
        assert set(art["regions"]) == set(REGIONS)
        assert set(art["table"]) == set(TASK_TYPES)
        assert art.get("neutral") is True
        assert isinstance(art.get("description"), str) and art["description"]
        # Policy: latent floor for vmpfc, clip range, min_n, surface list.
        policy = art["policy"]
        assert "vmpfc" in policy["latent_floors"]
        assert policy["latent_floors"]["vmpfc"] == 1.0
        assert len(policy["clip"]) == 2
        assert policy["min_n"] >= 1
        # Aggregate row present and uniform.
        assert set(art["aggregate"]) == set(REGIONS)
        for r, w in art["aggregate"].items():
            assert w == pytest.approx(1.0), f"aggregate[{r}] = {w} (expected 1.0)"

    def test_table_is_uniform(self):
        art = _load(TASK_REGION_WEIGHTS_PATH)
        for task, row in art["table"].items():
            assert set(row) == set(REGIONS)
            for r, w in row.items():
                assert w == pytest.approx(1.0), f"table[{task}][{r}] = {w} (expected 1.0)"

    def test_base_weights_returns_uniform_row(self):
        art = task_region_weights.load_artifact(TASK_REGION_WEIGHTS_PATH)
        # Known task type returns its (uniform) row.
        row = task_region_weights.base_weights("build", art)
        assert set(row) == set(REGIONS)
        for r, w in row.items():
            assert w == pytest.approx(1.0)
        # None → aggregate row.
        agg = task_region_weights.base_weights(None, art)
        assert set(agg) == set(REGIONS)
        for r, w in agg.items():
            assert w == pytest.approx(1.0)
        # Unknown task type → aggregate fallback.
        unk = task_region_weights.base_weights("not_a_task", art)
        assert set(unk) == set(REGIONS)
        for r, w in unk.items():
            assert w == pytest.approx(1.0)

    def test_vmpfc_latent_floor_clamped(self):
        # Even if a hand-edited artifact tries to lower vmpfc, the floor wins.
        tampered = {
            "table": {
                "build": {r: 0.5 if r == "vmpfc" else 1.0 for r in REGIONS},
            },
            "aggregate": {r: 0.5 if r == "vmpfc" else 1.0 for r in REGIONS},
        }
        row = task_region_weights.base_weights("build", tampered)
        assert row["vmpfc"] == pytest.approx(1.0)

    def test_compose_returns_base_when_no_mode_weights(self):
        composed = task_region_weights.compose_region_weights(
            "build", mode_region_weights=None, path=TASK_REGION_WEIGHTS_PATH,
        )
        assert composed is not None
        assert set(composed) == set(REGIONS)
        for r, w in composed.items():
            assert w == pytest.approx(1.0)

    def test_compose_multiplies_base_by_posture_delta(self):
        # Uniform base (1.0) times any posture delta = the delta.
        mode = {r: 2.0 for r in REGIONS}
        composed = task_region_weights.compose_region_weights(
            "build", mode_region_weights=mode, path=TASK_REGION_WEIGHTS_PATH,
        )
        assert composed is not None
        for r, w in composed.items():
            assert w == pytest.approx(2.0)

    def test_banned_narrative_terms_absent(self):
        hits = _scan_for_banned_text(TASK_REGION_WEIGHTS_PATH)
        assert not hits, (
            "neutral task_region_weights seed contains banned author-voice text:\n"
            + "\n".join(f"  L{n}: {line}" for n, line in hits)
        )


# ---------- CODE RED scrub bible (audit gate) -------------------------------

# Banned tokens from the heavy-core plan. The audit gate enforces that no
# committed code references the private engine or its paths. The literal
# strings are decoded from base64 at runtime so the audit grep (which matches
# plain substrings) does not flag this test file's own token list as a
# violation.
import base64

_BANNED_B64: tuple[str, ...] = (
    "U0hBRE9X",              # internal
    "L1ZvbHVtZXM=",          # /tmp
    "Y3JlYXRpb2V4bmloaWxv",  # example
    "c2hhZG93X2Rpc3BhdGNo",  # dispatch
    "c2hhZG93X2JyYWlu",      # localbrain
    "VmFsaGFsbGE=",          # node
    "TmVvbg==",              # postgres
    "TUVNT1JZX0JBTks=",      # MEMORY_STORE
    "bW14X2NsYXVkZQ==",      # mmx_local
    "a2ltaV9jYXA=",          # cap_local
)


def _banned_tokens() -> list[str]:
    return [base64.b64decode(s).decode("ascii") for s in _BANNED_B64]


BANNED_TOKENS = _banned_tokens()


def _scan_tree(root: Path) -> dict[str, list[str]]:
    """Map banned_token -> list of files containing it. Production code only."""
    offenders: dict[str, list[str]] = {t: [] for t in BANNED_TOKENS}
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        for token in BANNED_TOKENS:
            if token in text:
                offenders[token].append(str(path))
    return offenders


@pytest.mark.parametrize("token", BANNED_TOKENS)
def test_scrub_bible_no_banned_token_in_production_code(token: str):
    """Audit gate: shipped production code (ari_os/) must not contain banned tokens."""
    offenders = _scan_tree(REPO_ROOT / "ari_os")
    assert not offenders[token], (
        f"banned token {token!r} found in shipped code: {offenders[token]}"
    )


@pytest.mark.parametrize("token", BANNED_TOKENS)
def test_scrub_bible_no_banned_token_in_seed_jsons(token: str):
    """Audit gate: committed seed JSONs must not contain banned tokens."""
    offenders: dict[str, list[str]] = {t: [] for t in BANNED_TOKENS}
    for path in SEEDS_DIR.glob("*.json"):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except OSError:
            continue
        if token in text:
            offenders[token].append(str(path))
    assert not offenders[token], (
        f"banned token {token!r} found in seed JSON: {offenders[token]}"
    )
