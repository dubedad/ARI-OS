# ARI-OS

An orchestrator-first operating layer for Claude Code:

**brainstorm → plan → dispatch background workers → watch → review → ship.**

Your main session stays an *advisor* — focused work runs in cheap background
workers you watch in a little System 7 dashboard. ARI-OS is pure Python
standard library: no third-party dependencies.

## Install

```bash
python3 install.py
```

That copies the skills + commands into your Claude Code directory, registers a
status line, and adds a short managed block to your `CLAUDE.md`. Every change is
**backed up and recorded** — it is fully reversible.

Prefer to do it by hand (or have your assistant do it)? Read **[SETUP.md](SETUP.md)**.

## What you get

- **Skills** — `brainstorm` (spec-first ideation), `handoff` (resume a session
  cold), `advisor` (dispatch background workers), `teach` (optional tips).
- **Commands** — `/brainstorm`, `/handoff`, `/dispatch`, `/monitor`.
- **Dispatcher** — `python3 -m ari_os.tools.dispatch start --executor sonnet
  --task-file BRIEF.md --cwd <dir> --label <name>`.
- **Monitor** — `python3 -m ari_os.tools.monitor` → http://localhost:7777. A
  System 7 dashboard of running / blocked / done workers, with a live gradient
  color picker (top-right).
- **Status line** — `ctx% · model · dir · branch · 🛠workers · clock`.

## Control panel

```bash
python3 -m ari_os.tools.arios keys            # which provider keys resolve
python3 -m ari_os.tools.arios theme stipple   # monitor background theme
python3 -m ari_os.tools.arios toggle teach on # turn a feature on/off
python3 -m ari_os.tools.arios update          # in-place update
```

## Update / revert / uninstall

```bash
python3 install.py --update      # refresh in place; keeps your keys + config
python3 install.py --revert      # undo the last change
python3 install.py --uninstall   # remove everything ARI-OS added
```

## Keys

Resolve from environment variables first (e.g. `ANTHROPIC_API_KEY`), then the
macOS Keychain service `com.ari-os.keys`. Key values are never printed.

## Single home

ARI-OS is the home for these patterns. The earlier `icm-handoff-protocol` and
`advisor-driven-dev` repos now point here.
