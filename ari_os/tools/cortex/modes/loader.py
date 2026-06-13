"""Mode YAML loader — parse, validate, and cache the public mode set.

Ported + scrubbed from the private engine. No path changes needed beyond
``$ARI_OS_HOME`` semantics.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import yaml

_MODES_DIR = Path(__file__).parent

_REQUIRED_KEYS = frozenset({
    "name", "description", "region_weights", "tier_weights",
    "k_vector", "k_adjacent", "k_kg", "kg_expand", "token_budget", "fsrs_enabled",
})

# mtime-keyed cache: full path → (mtime, parsed_dict)
_cache: dict = {}


_OPTIONAL_NUMERIC = ("dn_strength", "dn_sigma")

# Optional `council:` block — a partial overlay on the council's
# default params. Knobs are data; an unknown key is a typo that would
# otherwise silently no-op, so it's a hard validation error.
_COUNCIL_NUMERIC = frozenset({
    "rho", "tau", "lam", "gamma", "epsilon", "theta_floor", "fallback_threshold",
    "dup_veto", "nu",
})
_COUNCIL_KEYS = _COUNCIL_NUMERIC | {"m_top", "caps", "soft_targets", "intrusion_regions"}


def _validate_council_block(c):
    if not isinstance(c, dict):
        raise ValueError(f"Mode YAML 'council' must be a mapping, got {type(c).__name__}")
    unknown = set(c.keys()) - _COUNCIL_KEYS
    if unknown:
        raise ValueError(f"Mode YAML 'council' has unknown keys: {sorted(unknown)}")
    for key in _COUNCIL_NUMERIC & set(c.keys()):
        v = c[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ValueError(f"Mode YAML council.{key} must be a non-negative number, got {v!r}")
    if "m_top" in c:
        v = c["m_top"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise ValueError(f"Mode YAML council.m_top must be a positive int, got {v!r}")
    if "soft_targets" in c and not isinstance(c["soft_targets"], bool):
        raise ValueError(f"Mode YAML council.soft_targets must be a bool, got {c['soft_targets']!r}")
    if "intrusion_regions" in c:
        ir = c["intrusion_regions"]
        if not isinstance(ir, list) or not all(isinstance(r, str) for r in ir):
            raise ValueError(
                f"Mode YAML council.intrusion_regions must be a list of region names, got {ir!r}")
    if "caps" in c:
        caps = c["caps"]
        if not isinstance(caps, dict):
            raise ValueError(f"Mode YAML council.caps must be a mapping, got {caps!r}")
        for region, share in caps.items():
            if isinstance(share, bool) or not isinstance(share, (int, float)) or not 0 <= share <= 1:
                raise ValueError(
                    f"Mode YAML council.caps[{region!r}] must be a number in [0, 1], got {share!r}")


def validate_mode(d):
    missing = _REQUIRED_KEYS - set(d.keys())
    if missing:
        raise ValueError(f"Mode YAML missing required keys: {sorted(missing)}")
    for key in _OPTIONAL_NUMERIC:
        if key in d:
            v = d[key]
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
                raise ValueError(f"Mode YAML {key!r} must be a non-negative number, got {v!r}")
    if "council" in d:
        _validate_council_block(d["council"])


def load_mode(name, modes_dir=None):
    if modes_dir is None:
        modes_dir = _MODES_DIR
    path = Path(modes_dir) / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"No mode YAML found: {path}")
    mtime = path.stat().st_mtime
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = yaml.safe_load(path.read_text())
    validate_mode(data)
    _cache[path] = (mtime, data)
    return data


def list_modes(modes_dir=None):
    if modes_dir is None:
        modes_dir = _MODES_DIR
    return sorted(p.stem for p in Path(modes_dir).glob("*.yaml"))


def _home(home_dir):
    if home_dir is not None:
        return home_dir
    base = os.environ.get("ARI_OS_HOME")
    if base:
        return Path(base)
    return Path.home() / ".ari-os"


def active_mode_for_cwd(cwd, home_dir=None):
    sha = hashlib.sha1(str(cwd).encode()).hexdigest()
    path = _home(home_dir) / "active_mode" / sha
    if not path.exists():
        return "default"
    name = path.read_text().strip()
    try:
        load_mode(name)
    except (FileNotFoundError, ValueError):
        return "default"
    return name


def set_active_mode(cwd, name, home_dir=None):
    try:
        load_mode(name)
    except FileNotFoundError:
        raise ValueError(f"Unknown mode: {name!r}")
    sha = hashlib.sha1(str(cwd).encode()).hexdigest()
    base = _home(home_dir) / "active_mode"
    base.mkdir(parents=True, exist_ok=True)
    target = base / sha
    tmp = target.with_suffix(".tmp")
    tmp.write_text(name)
    tmp.rename(target)
