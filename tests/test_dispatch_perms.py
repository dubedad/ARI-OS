from pathlib import Path

from ari_os.tools import dispatch


def test_worker_skip_permissions_flag_enabled_by_default(monkeypatch):
    monkeypatch.delenv("ARI_OS_WORKER_SKIP_PERMISSIONS", raising=False)

    argv = dispatch.build_claude_argv(
        executor="sonnet", cwd="/work/proj", add_dirs=[], read_only=False
    )

    assert "--dangerously-skip-permissions" in argv


def test_worker_skip_permissions_flag_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ARI_OS_WORKER_SKIP_PERMISSIONS", "0")

    argv = dispatch.build_claude_argv(
        executor="sonnet", cwd="/work/proj", add_dirs=[], read_only=False
    )

    assert "--dangerously-skip-permissions" not in argv


def test_readme_documents_worker_skip_permissions_env_var():
    readme = Path("README.md").read_text()

    assert "ARI_OS_WORKER_SKIP_PERMISSIONS" in readme
