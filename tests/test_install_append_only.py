from ari_os import install
from ari_os.install import END, START


def test_user_content_survives_install_and_update():
    user = "# My rules\nnever delete me\n## Section 2\nkeep this too\n"
    once = install.inject_block(user, "v1")
    twice = install.inject_block(once, "v2")

    assert "never delete me" in twice and "keep this too" in twice
    assert twice.count(START) == 1 and twice.count(END) == 1
    assert "v2" in twice and "v1" not in twice
    assert twice.rstrip().endswith(END)


def test_orphaned_marker_is_repaired_not_duplicated():
    broken = f"# My rules\n{START}\nstale half-block with no end marker\n"

    out = install.inject_block(broken, "v1")

    assert out.count(START) == 1 and out.count(END) == 1
    assert "# My rules" in out
