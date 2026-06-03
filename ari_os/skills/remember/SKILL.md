---
name: remember
description: Use when something worth keeping is decided or learned — a decision, a fact, an open thread — so the next session has it.
---

# Remember

Capture durable context into the local brain so it survives the session.

## When to use
- A decision got made, and why.
- A fact or constraint worth carrying forward.
- An open thread to pick up later — tag it `open`.

## How
Run: `python3 -m ari_os.tools.cortex remember "<text>" --context <project> --tags "<space separated>" [--salience N]`

- `--context` is the project you are in; keep related memories under the same context.
- Tag unfinished work `open` so `/morning` resurfaces it.
- Raise `--salience` for things you must not lose.

Capture the conclusion, not the whole transcript.
