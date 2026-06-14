---
name: night
description: Use at the end of a work session to run dream first, then prepare a clean next-session review.
---

# Night

Close the session by consolidating first, then surfacing the threads that should survive into the next session.

## How

### 1. Run Dream First

Run:

```bash
python3 -m ari_os.tools.cortex dream
```

Summarise the result in one or two lines. If the LLM backend is `off`, treat that as a valid no-summary pass.

### 2. Review Open Threads

Retrieve open items:

```bash
python3 -m ari_os.tools.cortex retrieve -q "open threads [open]" --cwd "$PWD" --mode synthesis
```

Surface only active threads that still need a next action.

### 3. Check Pending Near-Duplicate Memories

If the session created memory drafts, run a local near-duplicate check with `ari_os.tools.cortex.dedup.run_dedup_check`.

Report candidates as:

- `possible duplicate`
- `possible extension`
- `distinct`

Do not delete or rewrite memories automatically.

### 4. Suggest Tomorrow's Focus

Use the dream output, open threads, and recent retrieved memories to propose one "tomorrow's focus" line.

Keep it generic:

- One primary focus.
- One optional maintenance item.
- Any blocker that needs the user.

## Safety

- Never delete user memories.
- Never require a network model.
- Never include private workflow names or internal operator paths.
- Ask before changing any durable file beyond the local Cortex state written by `dream`.
