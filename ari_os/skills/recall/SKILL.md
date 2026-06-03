---
name: recall
description: Use before answering when past context would help — pulls relevant memories from the local brain, tunnelled to the current project.
---

# Recall

Pull relevant past context before you answer, so the model works from what is known instead of guessing.

## How
Run: `python3 -m ari_os.tools.cortex recall "<query>" --context <project> [--mode focus|default|wide]`

- It tunnels to the current project by default. If it prints `local context thin — add --wide`, surface that to the user as an offer and wait. Do not widen on your own.
- `--mode wide` for synthesis or "what am I missing"; `--mode focus` for deep single-thread work.

## Mind wander
If a recall surfaces a memory marked as a wander — a tangent from outside the current focus — surface it to the user in one line, then return to the thread. It is a deliberate re-orientation, not a mistake.
