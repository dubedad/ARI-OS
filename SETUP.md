# ARI-OS — Advanced Setup (manual path)

Prefer the wizard? Run `python3 install.py` and skip this file. This is the
do-it-by-hand path: hand it to your assistant ("read SETUP.md and set this up")
or follow it yourself. It mirrors exactly what `install.py` does — with the same
safety rules.

## Dependencies

ARI-OS is a Python package. Install its dependencies once with
`uv pip install -e .` (or `pip install -e .`): `sqlite-vec`, `scikit-learn`,
`httpx`, `pyyaml`, `click`, `mcp`. The optional media extras
(`pip install -e '.[media]'`) add `youtube-transcript-api` + `pillow` for
EARS / LENS. An optional local [Ollama](https://ollama.com) provides semantic
embeddings (`nomic-embed-text`) and the consolidation model (`gemma3:4b`).

## What gets installed

ARI-OS adds files to your Claude Code directory (`~/.claude` by default,
override with `ARI_OS_CLAUDE_DIR`) and keeps its own state under `~/.ari-os`
(override with `ARI_OS_HOME`). Nothing else on your machine is touched.

1. **Skills** → `~/.claude/skills/<name>/SKILL.md` — copies of `brainstorm`,
   `handoff`, `advisor`, `teach` from `ari_os/skills/`.
2. **Commands** → `~/.claude/commands/<name>.md` — the `/brainstorm`,
   `/handoff`, `/dispatch`, `/monitor` shims from `ari_os/commands/`.
3. **Status line** → `~/.claude/settings.json` — sets `statusLine` to
   `python3 -m ari_os.tools.statusline`. **Parse the file and merge this one
   key. Never rewrite it** — your existing keys/hooks must survive.
4. **CLAUDE.md block** → `~/.claude/CLAUDE.md` — a short ARI-OS section inserted
   **only** between `<!-- ARI-OS:start -->` and `<!-- ARI-OS:end -->`. Content
   outside those markers is never modified. If the markers already exist,
   replace what is between them; otherwise append the block.
5. **SessionStart hook + MCP server** → `~/.claude/settings.json` and
   `~/.claude/.mcp.json` — registers the Cortex brain-context hook and the
   `ari-os-cortex` MCP server (`brain.recall` / `lineage` / `regions`). Merged
   idempotently; `--no-mcp` opts out.
6. **Local brain** → `~/.ari-os/brain.db` — a fresh, empty SQLite brain is
   created. The `--llm` backend choice (default `ollama`) is saved to
   `~/.ari-os/config.json`; `--ears` / `--lens` opt into media ingest (off by
   default). `--revert` / `--uninstall` never delete the brain.

## Non-negotiable safety rules

- **Back up first.** Before editing `settings.json` or `CLAUDE.md`, copy the
  existing file into `~/.ari-os/backups/<timestamp>/`.
- **Record what you changed** in `~/.ari-os/installed.json` so it can be undone.
- **Idempotent.** Running setup twice changes nothing the second time.
- **Reversible.** `python3 install.py --revert` undoes the last change;
  `--uninstall` removes everything ARI-OS added.

## Keys

API keys resolve from environment variables first (e.g. `ANTHROPIC_API_KEY`),
then from the macOS Keychain service `com.ari-os.keys`. Key values are never
printed. Check status any time with `python3 -m ari_os.tools.arios keys`.

## Tuning your brain

Use `python3 -m ari_os.tools.cortex tune` to inspect the active cognitive mode and
its retrieval weights. Use `python3 -m ari_os.tools.cortex mode list|get|set
<name>` to list, inspect, or switch modes.

## Verify

```bash
python3 -m pytest -q                       # all green
python3 -m ari_os.tools.monitor            # http://localhost:7777
python3 -m ari_os.tools.arios keys         # present / missing per provider
```
