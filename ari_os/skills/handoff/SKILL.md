---
name: handoff
description: Use when a session is ending, getting long, or work must continue later — writes a HANDOFF.md so a fresh session can resume cold with zero loss.
---

# Handoff (ICM temporal continuity)

A long task outlives one session. This skill writes the bridge.

## When to write a handoff

- The session is ~50% through its context budget.
- You are about to park work that is not finished.
- The human says "sleep on it" / "pick this up later".

## What a HANDOFF.md contains

1. **Why parked** — one line.
2. **What this is** — the goal, in 2-3 sentences.
3. **Where everything lives** — exact paths to specs, plans, the repo, briefs.
4. **Build status** — a table: each unit + state (done / building / not started).
5. **Locked decisions** — so the next session does not relitigate them.
6. **What to do on resume** — a numbered, ordered list.

## The first-turn rule (MANDATORY footer)

Every handoff MUST end with this line, verbatim:

> FIRST TURN: read the referenced docs ONE AT A TIME (no parallel tool calls, no batched reads). Parallel reads on the first turn can wedge a new session; sequential reads avoid it.

A resumed session's first action is to read the handoff, then the referenced docs one at a time.
