"""Mode routing config — load the structural / inferred routing table.

Reads ``$ARI_OS_HOME/mode_routing.yaml`` if present, otherwise the package
default. The config powers mode_router's structural-skill and inferred-keyword
lookups.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PKG_DEFAULT = Path(__file__).parent / "mode_routing.yaml"

_DEFAULT_POSTURE = {
    "overfetch_factor": 3,
    "local_coverage_floor": 3,
    "tunnel_dn_strength": 0.2,
    "tunnel_dn_sigma": 1.0,
    "global_dn_strength": 1.2,
    "global_dn_sigma": 1.0,
}


@dataclass
class RoutingConfig:
    skills: dict = field(default_factory=dict)
    cwd_substrings: dict = field(default_factory=dict)
    keywords: dict = field(default_factory=dict)
    posture_defaults: dict = field(default_factory=lambda: dict(_DEFAULT_POSTURE))


def _user_override():
    base = os.environ.get("ARI_OS_HOME")
    home = Path(base) if base else Path.home() / ".ari-os"
    return home / "mode_routing.yaml"


def load_routing_config(path=None):
    if path is None:
        override = _user_override()
        path = override if override.exists() else _PKG_DEFAULT
    data = yaml.safe_load(Path(path).read_text()) or {}
    structural = data.get("structural") or {}
    inferred = data.get("inferred") or {}
    posture_raw = data.get("posture") or {}
    posture = dict(_DEFAULT_POSTURE)
    posture.update({k: v for k, v in posture_raw.items() if k in _DEFAULT_POSTURE})
    return RoutingConfig(
        skills=dict(structural.get("skills") or {}),
        cwd_substrings=dict(structural.get("cwd_substrings") or {}),
        keywords={k: list(v) for k, v in (inferred.get("keywords") or {}).items()},
        posture_defaults=posture,
    )
