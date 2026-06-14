---
name: recall
description: Use before answering when past context would help — pulls relevant memories from the local brain, tunnelled to the current project.
---

# Recall

Pull relevant past context before you answer, so the model works from what is known instead of guessing.

## How

Run: `python3 -m ari_os.tools.cortex retrieve -q "<query>" --cwd "$PWD" [--mode focus|default|wide|synthesis|deep|creative|visual]`

- The heavy `retrieve` runs the hybrid FTS+vec pipeline and prints a regioned context block. It is the heavy-engine replacement for the light `recall` shim.
- `--cwd "$PWD"` is the workspace gate: results are biased toward the current project by default. The `mode_router` decides posture (tunnel / global / auto) from the query.
- If the printed block contains `local context thin — widen?`, surface that to the user as an offer and wait. Do not widen on your own.

### Modes

- `--mode focus` — deep single-thread work (debugging, fixing).
- `--mode wide` — cross-workspace synthesis ("what am I missing").
- `--mode synthesis` — bridge / connect / tie together.
- `--mode deep` — consolidate / distill / summarise.
- `--mode creative` — brainstorm / riff.
- `--mode visual` — palette / lens / frame.
- `--mode default` — balanced retrieval.

`/morning` and the `SessionStart` hook call `mode auto` first; the chosen mode is then passed to `retrieve`.

## Mind wander

If a recall surfaces a memory flagged as a wander — a tangent from outside the current workspace — surface it to the user in one line, then return to the thread. It is a deliberate re-orientation, not a mistake.

> Mind-wander one-liner placeholder: when the retrieval engine surfaces a chunk whose source path is outside the current `cwd`, render a single line like `↪ wander: <path>:<line> — <one-line gloss>` before the next response, then return to the thread.
