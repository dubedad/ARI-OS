---
name: dream
description: Use to consolidate the local brain — dedup, decay, and surface housekeeping suggestions. Safe; it never deletes real memories without you.
---

# Dream

Consolidate the local brain and surface hygiene suggestions.

## How
Run: `python3 -m ari_os.tools.dream`

- It collapses exact duplicates (keeping the highest-salience copy) and decays stale, low-value memories. These are safe.
- It then lists suggestions — duplicate clusters, orphans, bloat. Present them; never delete a memory on a suggestion without confirming with the user first.
