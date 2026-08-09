# Changelog

## Unreleased — workspace-safe installer

Fixes found while installing ARI-OS scoped to a single project directory
(`ARI_OS_CLAUDE_DIR=<project>/.claude`) rather than into `~/.claude`. Several
affect every install, not just the scoped case.

### Fixed

- **SessionStart hook never ran.** The managed marker `# ari-os-session-start`
  was prepended to the command, so a shell read the whole line as a comment and
  the hook exited 0 having done nothing. The marker is now a trailing comment.
- **SessionStart hook was written in a shape harnesses ignore.** A bare command
  object was appended directly to the `SessionStart` array; harnesses expect a
  matcher group with a nested `hooks` list. A bare entry is skipped silently, so
  brain context on session start never fired for anyone. Entries are now written
  in group form, and `_strip_ari_os_session_start` understands both shapes so
  existing installs upgrade cleanly.
- **Hook and status line invoked a bare `python3`.** Whatever `python3` the
  harness found first was rarely the interpreter ARI-OS was installed into — the
  status line then died with `ModuleNotFoundError` on every render, and the hook
  produced nothing. Both now use `sys.executable`, captured at install time
  (`STATUSLINE_COMMAND`, `MCP_SERVER_COMMAND`).
- **`--dry-run` crashed on default flags.** MCP intents were emitted as
  three-element tuples while `main()` unpacked pairs, raising `ValueError: too
  many values to unpack`. Intents are now pairs.
- **`--dry-run` reported destinations the install would not touch.** The dry-run
  branch resolved MCP paths with its own stale logic. It now mirrors the real
  code path, including the global opt-in gate.
- **A workspace-scoped install wrote to global agent configs.** Installing into
  a project directory still registered the Cortex MCP server in
  `~/.codex/config.toml`, `~/.gemini/settings.json` and `~/.kimi-code/mcp.json`.
  Registration is now confined to the install target; reaching other harnesses
  requires the explicit `--register-global-harnesses`, which prints a warning
  naming the scope. `--update` inherits the safe default, so an update can never
  silently widen an existing install.
- **Claude MCP config was written where Claude Code does not read it.** It went
  to `$CLAUDE_DIR/.mcp.json`; Claude Code reads project-scoped servers from
  `.mcp.json` at the *project root*. For a scoped install the file now lands at
  the project root. For a global install (`~/.claude`) registration is skipped
  with the correct `claude mcp add --scope user` command printed, rather than
  merging into unrelated user state. `unregister_mcp_server` cleans both the new
  and legacy locations.
- **`mcp` was unbounded.** `mcp>=1.0` resolved to 2.0, which removed
  `mcp.server.FastMCP` — a fresh install produced a memory server that could not
  start. Now `mcp>=1.0,<2`.
- **The installed `CLAUDE.md` block documented commands that do not run.** It
  told agents to invoke `cortex recall` / `remember`, which are not CLI verbs —
  the Cortex CLI provides `ingest` and `retrieve -q` — and to run them under a
  bare `python3`, which usually cannot import `ari_os`. Both corrected; the
  block now names `sys.executable` via the shared `ARI_OS_PYTHON` constant.
  (`/recall` and `/remember` as slash commands are real and unchanged.)

### Fixed — test suite

- **Running the tests rewrote the developer's own machine configuration.**
  Several tests in `test_install.py` call `apply(..., dry_run=False)` with MCP
  registration left at its default, and redirected only `ARI_OS_HOME` and
  `ARI_OS_CLAUDE_DIR` — so each run wrote ARI-OS entries into the developer's
  real `~/.codex/config.toml` and `~/.gemini/settings.json`. A new autouse
  fixture in `tests/conftest.py` redirects every config root, plus `HOME`, into
  a per-test temp directory.
- **`test_writes_all_harness_configs` was host-dependent.** It asserted the
  exact set `{claude, codex, gemini}`, which only held on machines without Kimi
  installed. Relaxed to a subset assertion over the harnesses it sets up.

### Added

- `tests/test_workspace_safety.py` — ten regression tests: hook executable and
  idempotent, dry run complete and write-free, global configs untouched by a
  scoped install, global reach gated behind the opt-in flag, MCP config at the
  project root, update preserving a working install, dependency bound declared,
  and docs naming only real CLI commands.
- `tests/test_mcp_handshake.py` — starts the Cortex MCP server over stdio in the
  resolved environment and asserts a valid `initialize` result.
- `install.iter_session_start_commands(settings)` — reads SessionStart commands
  from both the group and legacy shapes.
- `--register-global-harnesses` — explicit, warned opt-in for machine-wide MCP
  registration.
