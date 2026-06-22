"""ARI-OS multi-provider text-in/text-out CLI. Stdlib only.

Keys resolve from env vars first, then macOS Keychain (service com.ari-os.keys).
Key values are never printed. Designed to be called by the orchestrator as a
cheap executor for non-file text work (drafts, research, second opinions).
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from urllib.request import Request
from urllib.error import HTTPError
from . import _http

KEYCHAIN_SERVICE = "com.ari-os.keys"
ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "google":    "GEMINI_API_KEY",
    "moonshot":  "MOONSHOT_API_KEY",
    "minimax":   "MINIMAX_API_KEY",
}

MODELS = {
    "haiku":   {"provider": "anthropic", "model_id": "claude-haiku-4-5"},
    "sonnet":  {"provider": "anthropic", "model_id": "claude-sonnet-4-6"},
    "opus":    {"provider": "anthropic", "model_id": "claude-opus-4-6"},
    "gemini":  {"provider": "google",    "model_id": "gemini-3-pro-preview"},
    "kimi":    {"provider": "moonshot",  "model_id": "kimi-k2.5"},
    "minimax": {"provider": "minimax",   "model_id": "MiniMax-M2.5"},
    "gemma":   {"provider": "ollama",    "model_id": "gemma3:4b"},
}
OPENAI_ENDPOINTS = {
    "moonshot": "https://api.moonshot.cn/v1",
    "minimax":  "https://api.minimax.io/v1",
}

def _keychain_lookup(service: str, account: str) -> str | None:
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None

def get_key(provider: str) -> str:
    env_name = ENV_VARS.get(provider)
    if not env_name:
        print(f"Unknown provider: {provider}", file=sys.stderr); sys.exit(1)
    val = os.environ.get(env_name) or _keychain_lookup(KEYCHAIN_SERVICE, env_name)
    if not val:
        print(f"Missing key for {provider}. Set ${env_name} or add it to the "
              f"'{KEYCHAIN_SERVICE}' keychain item.", file=sys.stderr)
        sys.exit(1)
    return val

# --- callers (network; not unit-tested in Plan 1) ---

def call_anthropic(key, model_id, prompt, system):
    body = {"model": model_id, "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}]}
    if system: body["system"] = system
    req = Request("https://api.anthropic.com/v1/messages",
                  data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json", "x-api-key": key,
                           "anthropic-version": "2023-06-01"})
    with _http.open_url(req, timeout=300) as r:
        res = json.loads(r.read())
    return "\n".join(b["text"] for b in res.get("content", []) if b.get("type") == "text") or "(empty)"

def call_openai_compat(key, model_id, prompt, system, base_url):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    req = Request(f"{base_url}/chat/completions",
                  data=json.dumps({"model": model_id, "messages": msgs,
                                   "max_tokens": 8192}).encode(),
                  headers={"Content-Type": "application/json",
                           "Authorization": f"Bearer {key}"})
    with _http.open_url(req, timeout=300) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def call_google(key, model_id, prompt, system):
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system: body["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    req = Request(url, data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json",
                           "x-goog-api-key": key})
    with _http.open_url(req, timeout=300) as r:
        res = json.loads(r.read())
    cands = res.get("candidates", [])
    return "".join(p.get("text", "") for p in cands[0]["content"]["parts"]) if cands else "(no candidates)"

def call_ollama(model_id, prompt, system):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    with _http.open_url(Request("http://localhost:11434/api/chat",
                                data=json.dumps({"model": model_id, "messages": msgs,
                                                 "stream": False}).encode(),
                                headers={"Content-Type": "application/json"}), timeout=600) as r:
        return json.loads(r.read()).get("message", {}).get("content", "(empty)")

def call_model(name: str, prompt: str, system: str | None) -> str:
    cfg = MODELS[name]; prov = cfg["provider"]; mid = cfg["model_id"]
    if prov == "ollama":
        return call_ollama(mid, prompt, system)
    key = get_key(prov)
    if prov == "anthropic":
        return call_anthropic(key, mid, prompt, system)
    if prov == "google":
        return call_google(key, mid, prompt, system)
    if prov in OPENAI_ENDPOINTS:
        return call_openai_compat(key, mid, prompt, system, OPENAI_ENDPOINTS[prov])
    print(f"No caller for provider: {prov}", file=sys.stderr); sys.exit(1)

def main() -> None:
    ap = argparse.ArgumentParser(epilog="Models: " + ", ".join(MODELS))
    ap.add_argument("-m", "--model", required=True, choices=list(MODELS))
    ap.add_argument("-s", "--system", default=None)
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("prompt", nargs="?", default=None)
    a = ap.parse_args()
    prompt = sys.stdin.read().strip() if a.stdin else a.prompt
    if not prompt:
        ap.error("Provide a prompt or use --stdin")
    try:
        print(call_model(a.model, prompt, a.system))
    except HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
