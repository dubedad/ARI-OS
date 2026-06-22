import pytest

from ari_os import paths
from ari_os.tools import dispatch


def test_safe_segment_strips_traversal():
    assert paths.safe_segment("../../etc/passwd") == "passwd"
    assert paths.safe_segment("w-ab12-foo") == "w-ab12-foo"
    for bad in ("", "..", "."):
        with pytest.raises(ValueError):
            paths.safe_segment(bad)


def test_resolve_within_rejects_escape(tmp_path):
    base = tmp_path / "questions"
    base.mkdir()
    assert paths.resolve_within(base, "ok.md") == (base / "ok.md").resolve()
    with pytest.raises(ValueError):
        paths.resolve_within(base, "../../escape.md")


def test_worker_id_sanitises_label():
    wid = dispatch.worker_id("../../evil")
    assert "/" not in wid and ".." not in wid
    assert wid.endswith("-evil")
