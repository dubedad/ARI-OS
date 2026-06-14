---
name: dream
description: Use to run the local Cortex consolidation pass before review or handoff work.
---

# Dream

Run the heavy Cortex consolidation pass.

## How

Run:

```bash
python3 -m ari_os.tools.cortex dream
```

## What It Does

- Runs local consolidation over the configured `brain.db`.
- Applies deterministic decay and dream queue maintenance.
- Uses the configured consolidation model only when `cortex.llm` is enabled.
- Completes cleanly when the LLM backend is `off`.
- Writes state under `ARI_OS_HOME`, not inside the project checkout.

## Report Shape

After the command finishes, report:

- The number of summaries created.
- Whether any queue items were written.
- The suggested mode, if the command emitted one.
- Any skip message, such as a missing database or disabled backend.

Keep the report short. The routine is a maintenance pass, not a transcript dump.
