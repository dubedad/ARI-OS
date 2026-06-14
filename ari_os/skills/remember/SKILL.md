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

The heavy engine stores memories as chunk rows keyed by source path. A remember call **writes a memory file + ingests it** so the next session can retrieve it via `recall`.

### 1. Write the memory file

Drop a single-chunk markdown file under the active workspace's memory root:

```
$ARI_OS_HOME/memories/<context>/<UTC-timestamp>.md
```

The file body is the memory text — the conclusion, not the whole transcript. One memory per file. Use the file name as the durable handle.

### 2. Ingest it

Run: `python3 -m ari_os.tools.cortex ingest --path "$ARI_OS_HOME/memories/<context>/<UTC-timestamp>.md"`

- The `ingest` command computes the sha, classifies the region, embeds the chunk via the configured `EmbedClient`, and writes both the FTS5 index and the `chunk_vec` row.
- The memory is now retrievable through `python3 -m ari_os.tools.cortex retrieve -q "<query>" --cwd "$PWD"`.

### Programmatic path

For agents wiring `remember` into a tool loop, call the module directly:

```python
from ari_os.tools.cortex.config import brain_db_path
from ari_os.tools.cortex.embed import EmbedClient
from ari_os.tools.cortex.index import index_text

db = brain_db_path()
index_text(
    db,
    "<memory text>",
    source=f"remember:{int(time.time())}",
    layer="semantic",
    embed_client=EmbedClient(),
)
```

`index_text` is the one-chunk, no-file-path ingest path; it produces the same row layout as a file ingest.

## Conventions

- Keep related memories under the same `<context>` directory so the workspace gate treats them as one project.
- Tag unfinished work `open` in the file body (e.g. a frontmatter `tags: [open]` line) so `/morning` resurfaces it.
- Raise salience by writing a clean, distilled conclusion — the engine weights distilled chunks higher.
- Capture the conclusion, not the whole transcript.
