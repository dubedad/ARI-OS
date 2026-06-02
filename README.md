```
┌──────────────────────────────────────────────────────────┐
│ ▢  ░░░░░░░░░░░░░░░░░░░  A R I · O S  ░░░░░░░░░░░░░░░░░░░░│
├──────────────────────────────────────────────────────────┤
│                                                          │
│   An orchestrator-first operating layer for              │
│   Claude Code. Your main seat stays the advisor          │
│   — the focused work runs in the shadows.                │
│                                                          │
│   brainstorm → plan → dispatch → watch → ship            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Pure Python standard library. No third-party dependencies.

```
        ┌───────────┐     ┌───────────┐
        │ BRAINSTORM│ ──→ │   PLAN    │
        └───────────┘     └─────┬─────┘
                                │
        ┌───────────┐     ┌─────▼─────┐
        │  REVIEW   │ ←── │ DISPATCH  │
        └─────┬─────┘     └─────┬─────┘
              │                 │ background workers
              │           ┌─────▼─────┐
              │           │  MONITOR  │  localhost:7777
              ▼           └───────────┘
        ┌───────────┐
        │   SHIP    │
        └───────────┘
```

## Install

```
┌─ INSTALL ────────────────────────────────────────────────┐
│ python3 install.py        easy wizard                    │
│ read SETUP.md             advanced / by hand             │
│                                                          │
│ backed up · reversible · idempotent                      │
└──────────────────────────────────────────────────────────┘
```

```bash
python3 install.py          # or: "read SETUP.md and set this up"
```

Copies the skills + commands into your Claude Code directory, registers a
status line, and adds a short managed block to your `CLAUDE.md`. Every change is
**backed up and recorded** — fully reversible. See **[SETUP.md](SETUP.md)** for
the manual path.

## What you get

```
┌─ WHAT YOU GET ───────────────────────────────────────────┐
│ skills    brainstorm · handoff · advisor · teach         │
│ commands  /brainstorm /handoff /dispatch /monitor        │
│ dispatch  detached background workers                    │
│ monitor   System 7 dashboard + color picker              │
│ status    ctx% · model · branch · workers · clock        │
└──────────────────────────────────────────────────────────┘
```

Dispatch a worker and watch it:

```bash
python3 -m ari_os.tools.dispatch start --executor sonnet \
    --task-file BRIEF.md --cwd <dir> --label <name>
python3 -m ari_os.tools.monitor          # http://localhost:7777
```

## Control panel

```
┌─ CONTROL PANEL  (arios) ─────────────────────────────────┐
│ arios keys              which provider keys resolve      │
│ arios theme stipple     monitor background               │
│ arios toggle teach on   flip a feature                   │
│ arios update            in-place update                  │
└──────────────────────────────────────────────────────────┘
```

```bash
python3 -m ari_os.tools.arios keys
python3 -m ari_os.tools.arios theme stipple
```

## Lifecycle

```
┌─ LIFECYCLE ──────────────────────────────────────────────┐
│ install.py --update     refresh; keeps keys + config     │
│ install.py --revert     undo the last change             │
│ install.py --uninstall  remove everything               │
└──────────────────────────────────────────────────────────┘
```

## Keys

Resolve from environment variables first (e.g. `ANTHROPIC_API_KEY`), then the
macOS Keychain service `com.ari-os.keys`. Key values are never printed.

## Single home

ARI-OS is the home for these patterns. The earlier `icm-handoff-protocol` and
`advisor-driven-dev` repos now point here.
