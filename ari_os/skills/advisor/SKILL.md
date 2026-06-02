---
name: advisor
description: Use whenever a task will take real focused work (many files, long builds, deep debugging) — dispatch a background worker instead of doing it inline, and keep the main session as an advisor.
---

# Advisor (background-first dispatch)

Your main session is an **advisor seat**, not a doer. Focused execution belongs in a background worker.

## Dispatch by default when a task will

- read more than ~5 files, or
- run more than one long build/test, or
- involve deep debugging on one component, or
- consume an uncertain amount of context.

## How to dispatch

1. Write a self-contained brief to a file (the worker has none of this conversation).
2. Start a background worker:
   `python3 -m ari_os.tools.dispatch start --executor sonnet --task-file BRIEF.md --cwd <worktree-or-subdir> --label <slug>`
   (use `haiku` for trivial work; `--read-only` for review-only tasks).
3. Keep advising in the main session. Do NOT also do the work yourself.

## Surfacing worker questions

- `python3 -m ari_os.tools.dispatch questions` lists open questions.
- `python3 -m ari_os.tools.dispatch answer <worker-id> --answer "..."` composes the answer back into the task; re-dispatch with `start`.
- The monitor (`python3 -m ari_os.tools.monitor`, http://localhost:7777) shows running / blocked / done at a glance.

## Stay inline for

single-file edits, status checks, brainstorming, 2-3 tool calls.
