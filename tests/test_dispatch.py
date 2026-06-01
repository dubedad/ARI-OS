import re, subprocess
from ari_os.tools import dispatch


def test_worker_id_shape():
    wid = dispatch.worker_id("impl-auth")
    assert re.match(r"^w-[0-9a-f]{4}-impl-auth$", wid)


def test_build_argv_basic():
    argv = dispatch.build_claude_argv(
        executor="sonnet", task="do the thing",
        cwd="/work/proj", add_dirs=["/work/extra"], read_only=False)
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "do the thing" in argv
    assert "--model" in argv and "sonnet" in argv
    assert "--add-dir" in argv and "/work/extra" in argv
    assert "--dangerously-skip-permissions" in argv


def test_build_argv_read_only_strips_write_tools():
    argv = dispatch.build_claude_argv(
        executor="haiku", task="review", cwd="/p", add_dirs=[], read_only=True)
    joined = " ".join(argv)
    assert "--disallowed-tools" in argv
    assert "Write" in joined and "Edit" in joined


def test_is_repo_root(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert dispatch.is_repo_root(str(tmp_path)) is True
    sub = tmp_path / "sub"; sub.mkdir()
    assert dispatch.is_repo_root(str(sub)) is False
