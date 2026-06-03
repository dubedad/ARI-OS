"""ARI-OS control panel: theme, toggles, key status, update. Stdlib only.
Never prints a key value."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from .. import paths
from . import monitor
from .ask import ENV_VARS
from .cortex import MODES

EMBEDDINGS_CHOICES = ("auto", "google", "ollama", "off")


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


def set_embeddings(provider: str) -> None:
    if provider not in EMBEDDINGS_CHOICES:
        raise ValueError(f"Unknown embeddings provider: {provider}. One of {EMBEDDINGS_CHOICES}")
    cfg = load_config()
    cfg.setdefault("cortex", {})["embeddings"] = provider
    save_config(cfg)

def set_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"Unknown mode: {mode}. One of {sorted(MODES)}")
    cfg = load_config()
    cfg.setdefault("cortex", {})["mode"] = mode
    save_config(cfg)

def set_wander(on: bool) -> None:
    cfg = load_config()
    cfg.setdefault("cortex", {})["wander"] = bool(on)
    save_config(cfg)

def cortex_status() -> dict:
    c = load_config().get("cortex", {})
    return {"embeddings": c.get("embeddings", "auto"),
            "mode": c.get("mode", "default"),
            "wander": c.get("wander", True)}

def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="arios")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("theme")
    t.add_argument("name")
    tg = sub.add_parser("toggle")
    tg.add_argument("feature")
    tg.add_argument("state", choices=["on", "off"])
    sub.add_parser("keys")
    sub.add_parser("update")
    cx = sub.add_parser("cortex")
    cx.add_argument("setting", choices=["embeddings", "mode", "wander", "status"])
    cx.add_argument("value", nargs="?")
    a = ap.parse_args(argv)
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
    elif a.cmd == "cortex":
        if a.setting == "status":
            for k, v in cortex_status().items():
                print(f"{k:11} {v}")
        elif a.value is None:
            ap.error(f"'cortex {a.setting}' needs a value")
        elif a.setting == "embeddings":
            set_embeddings(a.value); print(f"embeddings -> {a.value}")
        elif a.setting == "mode":
            set_mode(a.value); print(f"mode -> {a.value}")
        elif a.setting == "wander":
            set_wander(a.value == "on"); print(f"wander -> {a.value}")


if __name__ == "__main__":
    main()
