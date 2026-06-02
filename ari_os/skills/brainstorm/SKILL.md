---
name: brainstorm
description: Use at the start of any "let's build / design / figure out X" task — turns loose thinking into a numbered spec before any code is written.
---

# Brainstorm (spec-first)

Use this BEFORE planning or coding. The goal is a written spec the plan can consume.

## How to run it

1. **Let the human talk; you compress.** They think out loud. You capture into a living `SPEC.md` in real time — short bullets, not prose. Mirror back what you heard so they can correct it.
2. **Challenge, don't validate.** Surface the weak assumption, the missing case, the cheaper alternative. Protect the good ideas by name. One sharp question at a time.
3. **Drive to decisions.** Every open fork gets resolved and written under a "Locked decisions" heading so it is not relitigated later.
4. **End with a numbered spec.** Sections numbered (§1, §2…) so the plan can reference them. Include: what it is, goals/non-goals, components, state/filesystem, and locked decisions.

## Output rules

- The spec is a clean markdown file. No markers, no boxes — those are for chat only.
- If the idea spans multiple independent subsystems, split into one spec per subsystem.
- Stop when the spec is complete enough to write a plan against. Do not start coding.
