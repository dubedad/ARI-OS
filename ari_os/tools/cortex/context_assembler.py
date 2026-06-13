"""Context assembly — zone packing of ranked chunks into a token budget.

Public port + scrub of the heavy brain's context assembler. Zones
(persona / episodic / semantic) are derived from the published
cognitive-science region names and the chunk's distillation tier. The
returned chunks carry a ``zone`` attribute that the markdown emitter
and downstream consumers can use for budget breakdowns and metrics.
"""
from __future__ import annotations

# Identity / voice (vmpfc) and pinned Tier-4 chunks are always persona.
_PERSONA_REGIONS = {"vmpfc"}
# Hippocampus + the language regions feed the "what just happened / what
# was said" stream at low distillation tiers.
_EPISODIC_REGIONS = {"hippocampus", "broca", "wernicke"}


def zone_of(region: str, tier: int) -> str:
    """Map a (region, tier) pair to a memory zone.

    - ``vmpfc`` is persona regardless of tier (identity / voice).
    - Tier 4 (pinned, distilled) is always persona.
    - Tier 0/1 hippocampus / broca / wernicke is episodic.
    - Tier >= 2 anywhere is semantic (distilled material).
    - Everything else defaults: episodic for the language regions,
      semantic otherwise.
    """
    if region in _PERSONA_REGIONS or tier >= 4:
        return "persona"
    if tier <= 1 and region in _EPISODIC_REGIONS:
        return "episodic"
    if tier >= 2:
        return "semantic"
    return "episodic" if region in _EPISODIC_REGIONS else "semantic"


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


def assemble(ranked, token_budget: int, ratios: dict[str, float]):
    """Pack ranked chunks into a token budget respecting per-zone ratios.

    Two-pass greedy:

    1. **Per-zone fill.** Walk the ranked list in rank order; for each
       chunk, accept it if its zone still has budget.
    2. **Leftover fill.** Any global budget left over after pass 1
       accepts further chunks in rank order regardless of zone, until
       the budget is consumed or the candidate list is exhausted.

    Each accepted chunk is annotated with its ``zone``. The final
    returned list is sorted by the original rank order.
    """
    sub = {z: int(token_budget * r) for z, r in ratios.items()}
    used = {z: 0 for z in ratios}
    picked_ids, picked = set(), []
    # Pass 1: per-zone greedy by global rank
    for c in ranked:
        z = zone_of(c.region, c.tier)
        t = _approx_tokens(c.text)
        if used.get(z, 0) + t <= sub.get(z, 0):
            c.zone = z
            used[z] = used.get(z, 0) + t
            picked_ids.add(c.chunk_id)
            picked.append(c)
    # Pass 2: fill leftover budget globally
    leftover = token_budget - sum(used.values())
    for c in ranked:
        if c.chunk_id in picked_ids:
            continue
        t = _approx_tokens(c.text)
        if t <= leftover:
            c.zone = zone_of(c.region, c.tier)
            leftover -= t
            picked_ids.add(c.chunk_id)
            picked.append(c)
    picked.sort(key=lambda c: ranked.index(c))
    return picked
