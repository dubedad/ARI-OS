---
name: morning
description: Use at session start to produce a Cortex maintenance and dashboard block from the local brain.
---

# Morning

Start with a compact maintenance and dashboard block grounded in the local Cortex database.

## How

### 1. Database Integrity

Check that `ARI_OS_HOME` exists and that `brain.db` is present.

If the database exists, run a SQLite integrity check before retrieving context. If it is missing, say that Cortex is not initialised yet and keep going.

### 2. Ingest Freshness

Check whether the memory roots under `ARI_OS_HOME` have newer markdown files than the indexed source records.

If freshness is uncertain, suggest running:

```bash
python3 -m ari_os.tools.cortex ingest
```

Do not run a rebuild unless the user asks.

### 3. Recent Memories

Retrieve recent session context:

```bash
python3 -m ari_os.tools.cortex retrieve -q "recent memories and decisions" --cwd "$PWD" --mode default
```

Keep the result short and cite only the useful handles or source labels.

### 4. Open Threads

Retrieve unfinished items:

```bash
python3 -m ari_os.tools.cortex retrieve -q "open threads [open]" --cwd "$PWD" --mode synthesis
```

List active threads as next actions, not as a long archive.

### 5. Suggestions

End with one to three suggestions based on database health, ingest freshness, recent memories, and open threads.

## Output Format

Use this shape:

```text
## Morning

### Maintenance
[Database integrity, ingest freshness, and any issue.]

### Dashboard
[Recent memories and open threads.]

### Suggestions
[One to three concrete next moves.]
```

Keep the briefing public, local, and generic.
