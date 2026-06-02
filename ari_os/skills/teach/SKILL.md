---
name: teach
description: Optional. When enabled, drop a one-line ICM tip at a natural pause so the user learns the workflow as they use it. Off by default; toggle in `arios`.
---

# Teach (learn-as-you-go)

Optional coaching. When enabled, surface ONE short tip at a natural pause — never mid-task, never more than one at a time.

## Rules

- One line, at a pause (after a commit, before a dispatch, at a decision point).
- Tie the tip to what just happened ("you could have dispatched that — it touched 8 files").
- Never block the work to teach. If unsure, stay quiet.
- Respect the toggle: if teach is off in `~/.ari-os/config.json`, say nothing.

## Example tips

- "That was a long build — `advisor` would have run it in the background."
- "Before you park this, `handoff` writes the resume doc for you."
- "Markers help a skimming reader — end with → DECISION when you need a call."
