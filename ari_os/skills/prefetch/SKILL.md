---
name: prefetch
description: Use at the start of a workspace session to print recently useful Cortex memories for the current working directory.
---

# Prefetch

Prime the session with deterministic workspace-local memory before deeper recall.

## How

Run: `python3 -m ari_os.tools.cortex prefetch --cwd "$PWD"`

- If the brain DB is missing, the command exits cleanly with a short status line.
- If predictive memory is disabled, the command exits cleanly without touching the DB.
- If no prior chunks match the cwd, it prints an empty line.

Use this before broad retrieval when you want the workspace's recent context, not a semantic search.
