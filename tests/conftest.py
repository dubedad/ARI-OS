"""Global test isolation.

Every ARI-OS config root is redirected into a per-test temp directory before
any test runs. Without this, tests that call ``install.apply`` with the default
``register_mcp=True`` write MCP registrations into the developer's real
``~/.codex/config.toml``, ``~/.gemini/settings.json`` and ``~/.claude`` — a
running-the-tests-mutates-your-machine bug.

Individual tests may still monkeypatch these vars to point somewhere specific;
a later ``monkeypatch.setenv`` in the test simply wins.
"""
from __future__ import annotations

import pytest

# Every environment variable that can steer a write outside the repo.
_CONFIG_ENV_VARS = (
    "ARI_OS_HOME",
    "ARI_OS_CLAUDE_DIR",
    "CODEX_HOME",
    "GEMINI_DIR",
    "KIMI_CODE_HOME",
)


@pytest.fixture(autouse=True)
def isolate_config_roots(tmp_path_factory, monkeypatch):
    """Point every config root at a fresh temp dir for the duration of a test."""
    sandbox = tmp_path_factory.mktemp("cfg")
    for var in _CONFIG_ENV_VARS:
        monkeypatch.setenv(var, str(sandbox / var.lower()))
    # HOME too, so any bare ``~`` expansion that slips past the vars above
    # still lands inside the sandbox rather than the developer's home.
    monkeypatch.setenv("HOME", str(sandbox / "home"))
    (sandbox / "home").mkdir(parents=True, exist_ok=True)
    yield sandbox
