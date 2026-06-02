"""ARI-OS control panel: theme, toggles, key status, update. Stdlib only.
Never prints a key value."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from .. import paths
from . import monitor
from .ask import ENV_VARS


def _config_path():
    return paths.state_home() / "config.json"


def load_config() -> dict:
    p = _config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))


def set_theme(name: str) -> None:
    if name not in monitor.THEMES:
        raise ValueError(f"Unknown theme: {name}. One of {sorted(monitor.THEMES)}")
    cfg = load_config()
    cfg["theme"] = name
    save_config(cfg)


def toggle(feature: str, on: bool) -> None:
    cfg = load_config()
    cfg.setdefault("toggles", {})[feature] = bool(on)
    save_config(cfg)


def keys_status() -> dict:
    out = {}
    for provider, env in ENV_VARS.items():
        out[provider] = "present" if os.environ.get(env) else "missing"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="arios")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("theme")
    t.add_argument("name")
    tg = sub.add_parser("toggle")
    tg.add_argument("feature")
    tg.add_argument("state", choices=["on", "off"])
    sub.add_parser("keys")
    sub.add_parser("update")
    a = ap.parse_args()
    if a.cmd == "theme":
        set_theme(a.name)
        print(f"Theme set to {a.name}.")
    elif a.cmd == "toggle":
        toggle(a.feature, a.state == "on")
        print(f"{a.feature} -> {a.state}")
    elif a.cmd == "keys":
        for k, v in keys_status().items():
            print(f"{k:10} {v}")
    elif a.cmd == "update":
        subprocess.run([sys.executable, "-m", "ari_os.install", "--update"], check=False)


if __name__ == "__main__":
    main()
