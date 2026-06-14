"""Council allocation over an already-ranked retrieval pool.

The council is opt-in via ``cortex.council`` or ``ARI_OS_COUNCIL``. It is a
DB-free allocator: callers pass ranked chunks and receive a token-budgeted
selection plus telemetry.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from . import config
from .retrieve import _tokens


DEFAULT_PARAMS: dict = {
    "rho": 0.25,
    "tau": 0.25,
    "m_top": 3,
    "lam": 0.5,
    "gamma": 0.0,
    "epsilon": 0.0,
    "intrusion_regions": ["hippocampus", "vmpfc"],
    "dup_veto": 0.0,
    "nu": 0.0,
    "theta_floor": 0.5,
    "caps": {},
    "fallback_threshold": 0.5,
    "soft_targets": True,
}

PROTECTED_REGION = "vmpfc"


def enabled() -> bool:
    """Return whether council allocation is enabled for this runtime."""
    return config.council_enabled(default=False)


def _approx_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)


@dataclass
class _RegionState:
    candidates: list = field(default_factory=list)
    zs: list[float] = field(default_factory=list)
    activation: float = 0.0
    salience: float = 1.0
    ignited: bool = False
    next_idx: int = 0
    seats: int = 0
    tokens: int = 0
    target_tokens: float = 0.0
    wins: int = 0
    intrusions: int = 0
    vetoes: int = 0


def allocate(
    ranked: list,
    token_budget: int,
    *,
    salience: dict[str, float] | None = None,
    params: dict | None = None,
    seed: int = 0,
    zscores: dict[int, float] | None = None,
) -> tuple[list, dict]:
    """Compete the token budget among regions.

    ``ranked`` must be ordered best-first. ``salience`` is an optional
    per-region prior; missing regions default to 1.0. ``zscores`` may provide a
    calibrated comparable score per chunk. If it does not cover the full pool,
    within-region percentile stand-ins are used instead.
    """
    p = dict(DEFAULT_PARAMS)
    if params:
        p.update(params)
    salience = salience or {}

    for c in ranked:
        if c.source in ("intrusion", "fallback"):
            c.source = "vec"

    regions: dict[str, _RegionState] = {}
    for c in ranked:
        regions.setdefault(c.region, _RegionState()).candidates.append(c)

    if not regions or token_budget <= 0:
        return [], _telemetry({}, [], seed, "empty", p)

    z_source = "percentile"
    if zscores is not None and all(c.chunk_id in zscores for c in ranked):
        z_source = "anchors"

    for name, st in regions.items():
        if z_source == "anchors":
            st.candidates.sort(key=lambda c: zscores[c.chunk_id], reverse=True)
            st.zs = [zscores[c.chunk_id] for c in st.candidates]
            top = st.zs[: int(p["m_top"])]
            agg = sum(top) / len(top)
        else:
            n = len(st.candidates)
            st.zs = [1.0 - i / n for i in range(n)]
            top = st.zs[: int(p["m_top"])]
            agg = sum(top) / float(p["m_top"])
        st.salience = float(salience.get(name, 1.0))
        st.activation = st.salience * agg

    a_max = max(st.activation for st in regions.values())
    for st in regions.values():
        st.ignited = a_max > 0 and st.activation >= float(p["rho"]) * a_max
    ignited = {n: st for n, st in regions.items() if st.ignited}

    tau = max(float(p["tau"]), 1e-6)
    exps = {n: math.exp(st.activation / tau) for n, st in ignited.items()}
    z_sum = sum(exps.values())
    shares = {n: e / z_sum for n, e in exps.items()} if z_sum else {}
    caps = p.get("caps") or {}
    shares = {n: min(s, float(caps.get(n, 1.0))) for n, s in shares.items()}
    s_sum = sum(shares.values()) or 1.0
    for n, st in ignited.items():
        st.target_tokens = (shares.get(n, 0.0) / s_sum) * token_budget

    packed: list = []
    used = 0
    gamma = float(p["gamma"])
    lam = float(p["lam"])
    eps = float(p["epsilon"])
    rng = random.Random(seed) if eps > 0 else None
    intrusion_regions = tuple(p.get("intrusion_regions") or ())
    veto = float(p["dup_veto"])
    nu = float(p["nu"])
    token_cache: dict[int, set[str]] = {}

    def _tok(c) -> set[str]:
        cached = token_cache.get(id(c))
        if cached is None:
            cached = _tokens(c.text)
            token_cache[id(c)] = cached
        return cached

    def _red(a, b) -> float:
        if a.path and a.path == b.path:
            return 1.0
        ta = _tok(a)
        tb = _tok(b)
        if not ta or not tb:
            return 0.0
        union = len(ta | tb)
        return len(ta & tb) / union if union else 0.0

    def _max_red(c) -> float:
        return max((_red(c, b) for b in packed), default=0.0)

    def _vetoed(c) -> bool:
        return veto > 0 and _max_red(c) >= veto

    def _value(st: _RegionState) -> float:
        c = st.candidates[st.next_idx]
        z = st.zs[st.next_idx]
        red = _max_red(c)
        value = (1.0 / (1.0 + math.exp(-z))) * (1.0 - lam * red)
        if gamma > 0:
            value *= (1.0 + st.wins) ** (-gamma)
        return value

    def _intrude() -> bool:
        nonlocal used
        assert rng is not None
        pool = []
        for name in intrusion_regions:
            st = regions.get(name)
            if st is None:
                continue
            for i in range(st.next_idx, len(st.candidates)):
                if veto > 0 and _vetoed(st.candidates[i]):
                    continue
                pool.append((st, i))
        if not pool:
            return False
        if nu > 0:
            weights = [
                (1.0 / (1.0 + st.candidates[i].retrieved_count)) ** nu
                for st, i in pool
            ]
            st, i = rng.choices(pool, weights=weights, k=1)[0]
        else:
            st, i = pool[rng.randrange(len(pool))]
        chunk = st.candidates[i]
        cost = _approx_tokens(chunk.text)
        if used + cost > token_budget and packed:
            return False
        del st.candidates[i]
        del st.zs[i]
        chunk.source = "intrusion"
        packed.append(chunk)
        used += cost
        st.seats += 1
        st.tokens += cost
        st.intrusions += 1
        return True

    def _fill(limit_fn):
        nonlocal used
        while used < token_budget:
            if rng is not None and rng.random() < eps and _intrude():
                continue
            if veto > 0:
                for st in ignited.values():
                    while st.next_idx < len(st.candidates) and _vetoed(st.candidates[st.next_idx]):
                        st.next_idx += 1
                        st.vetoes += 1
            eligible = [
                (name, st)
                for name, st in ignited.items()
                if st.next_idx < len(st.candidates) and st.tokens < limit_fn(name, st)
            ]
            if not eligible:
                break
            _, st = max(eligible, key=lambda item: (_value(item[1]), item[0]))
            chunk = st.candidates[st.next_idx]
            st.next_idx += 1
            cost = _approx_tokens(chunk.text)
            if used + cost > token_budget and packed:
                continue
            packed.append(chunk)
            used += cost
            st.seats += 1
            st.tokens += cost
            st.wins += 1

    _fill(lambda n, st: min(st.target_tokens, float(caps.get(n, 1.0)) * token_budget))
    if p.get("soft_targets") and used < token_budget:
        _fill(lambda n, st: float(caps.get(n, 1.0)) * token_budget)

    protected_fired = False
    protected = regions.get(PROTECTED_REGION)
    if protected and protected.seats == 0:
        floor = float(p["theta_floor"])
        for best, z in zip(protected.candidates, protected.zs):
            if z < floor:
                break
            if veto > 0 and _vetoed(best):
                protected.vetoes += 1
                continue
            cost = _approx_tokens(best.text)
            packed.append(best)
            used += cost
            protected.seats += 1
            protected.tokens += cost
            protected_fired = True
            break

    fallback_used = False
    if used < float(p["fallback_threshold"]) * token_budget:
        have = {id(c) for c in packed}
        for c in ranked:
            if id(c) in have:
                continue
            cost = _approx_tokens(c.text)
            if used + cost > token_budget and packed:
                break
            c.source = "fallback"
            packed.append(c)
            used += cost
            fallback_used = True

    status = "allocated" if ignited else "no_ignition_fallback"
    tele = _telemetry(regions, packed, seed, status, p)
    tele["protected_seat"] = protected_fired
    tele["fallback_fill"] = fallback_used
    tele["tokens_used"] = used
    tele["z_source"] = z_source
    return packed, tele


def _telemetry(regions: dict, packed: list, seed: int, status: str, params: dict) -> dict:
    per_region = {}
    for name, st in regions.items():
        per_region[name] = {
            "candidates": len(st.candidates),
            "activation": round(st.activation, 4),
            "salience": round(st.salience, 4),
            "ignited": st.ignited,
            "gated_out": bool(st.candidates) and not st.ignited,
            "seats": st.seats,
            "tokens": st.tokens,
            "intrusions": st.intrusions,
            "vetoes": st.vetoes,
        }
    return {
        "status": status,
        "seed": seed,
        "coalition": [name for name, st in regions.items() if st.seats > 0],
        "regions": per_region,
        "intrusion_seats": sum(st.intrusions for st in regions.values()),
        "dup_vetoes": sum(st.vetoes for st in regions.values()),
        "params": {k: v for k, v in params.items() if k != "caps"},
    }
