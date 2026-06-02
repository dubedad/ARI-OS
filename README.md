```
┌──────────────────────────────────────────────────────────┐
│ ▢  ░░░░░░░░░░░░░░░░░░░  A R I · O S  ░░░░░░░░░░░░░░░░░░░░│
├──────────────────────────────────────────────────────────┤
│                                                          │
│   An orchestrator-first operating layer for              │
│   Claude Code. You stop typing tasks one at a time       │
│   and start running a background crew you watch.         │
│                                                          │
│   brainstorm → plan → dispatch → watch → ship            │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

Pure Python standard library. No third-party dependencies. One install.

## What is this, in plain English?

Out of the box, Claude Code does **one thing at a time**. You give it a task, you
watch it work, you wait, you give it the next task. You are the bottleneck. Your
session fills up with the mess of doing the work, and when it ends, the context
is gone.

ARI-OS changes the shape of the work. Instead of doing tasks yourself in one
chat, you **hand whole tasks to background workers** (cheaper, faster models),
keep your own session free to think and steer, and **watch every worker in a
little dashboard** until it is done. You stop being the typist and become the
director.

Three ideas make that work, and ARI-OS ships all three as installable pieces:

1. **Spec-first thinking.** Talk an idea into a short written spec before any code
   exists, so the work has a target.
2. **Background-first dispatch.** Fire focused work off to a worker and keep
   advising. The worker runs on its own; you review the result.
3. **Continuity.** A handoff format lets a fresh session pick up cold with zero
   loss, so a long job survives across days.

## The shift

```
        BEFORE                          AFTER
   ┌──────────────┐               ┌──────────────┐
   │ you type a   │               │ you define   │
   │ task         │               │ an outcome   │
   │ you wait     │               │ workers run  │
   │ you babysit  │               │ in parallel  │
   │ one at a time│               │ you review   │
   └──────────────┘               └──────────────┘
   bottleneck = you           bottleneck = removed
```

You move from *doing* to *directing*. The grunt work runs on cheap models in the
background. Your attention is spent where humans actually add value: judgment,
taste, and deciding what "done" means.

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

## What you actually get

```
┌─ WHAT YOU GET ───────────────────────────────────────────┐
│ skills    brainstorm · handoff · advisor · teach         │
│ commands  /brainstorm /handoff /dispatch /monitor        │
│ dispatch  detached background workers                    │
│ monitor   System 7 dashboard + color picker              │
│ status    ctx% · model · branch · workers · clock        │
└──────────────────────────────────────────────────────────┘
```

- **Skills** teach your assistant the workflow: `brainstorm` (turn loose thinking
  into a spec), `handoff` (write a resume doc so a new session continues cold),
  `advisor` (dispatch instead of doing it yourself), `teach` (optional one-line
  tips while you learn).
- **Dispatch** spawns a detached worker from a brief and tracks it. It refuses to
  run at a repo root and has a read-only mode, so a worker cannot wander.
- **Monitor** is a tiny local web dashboard styled like classic Mac OS. It shows
  every worker as running, blocked, or done, surfaces any questions they have,
  and lets you recolor the background.
- **Format** keeps replies skimmable: clear action and decision markers, plus
  best-effort boxes for status.
- **Status line** puts context %, model, branch, worker count, and the clock in
  your footer.

## A typical loop

```bash
# 1. Think it through. The brainstorm skill writes a spec with you.
/brainstorm a rate limiter for the API

# 2. Turn the spec into a plan, then dispatch the build to a worker:
python3 -m ari_os.tools.dispatch start --executor sonnet \
    --task-file BRIEF.md --cwd ./worktree --label rate-limit

# 3. Watch it (and any others) in the dashboard:
python3 -m ari_os.tools.monitor          # http://localhost:7777

# 4. If a worker has a question, answer it and let it carry on:
python3 -m ari_os.tools.dispatch questions
python3 -m ari_os.tools.dispatch answer w-1a2b-rate-limit --answer "use a token bucket"

# 5. Review the result, then ship.
```

While that worker builds, your own session stays free. Dispatch two more. You are
running a crew, not waiting on a queue of one.

## Why this is a more powerful way to work

- **Parallelism.** One assistant becomes many workers. Three tasks move at once
  instead of in a line.
- **You stay in judgment mode.** The advisor seat is reserved for the decisions
  only you can make. The typing is delegated.
- **Cheaper.** Grunt work runs on small, fast models. You spend the expensive
  model on thinking, not boilerplate.
- **Reviewable and reversible.** Workers commit per step; the installer backs up
  every change and can be reverted or uninstalled cleanly.
- **It survives time.** The handoff format means a job that outlives one session
  is resumed without losing the thread.

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

It copies the skills and commands into your Claude Code directory, registers a
status line, and adds a short managed block to your `CLAUDE.md`. Every change is
**backed up and recorded**, so it is fully reversible. Your existing settings and
keys are parsed and merged, never overwritten. See **[SETUP.md](SETUP.md)** for
the manual path.

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

Keys resolve from environment variables first (for example
`ANTHROPIC_API_KEY`), then the macOS Keychain service `com.ari-os.keys`. Key
values are never printed.

## Single home

ARI-OS is the home for these patterns. The earlier `icm-handoff-protocol` and
`advisor-driven-dev` repos now point here.
