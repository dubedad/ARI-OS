import re
from pathlib import Path


def test_docs_do_not_show_dead_install_py_command():
    docs = "\n".join(Path(name).read_text() for name in ("README.md", "SETUP.md"))

    assert "python3 -m ari_os.install" in docs
    assert re.search(r"(^|[`\s│])python3 install\.py(\s|`|$)", docs) is None
    assert "python3 -m ari_os.install --revert" in docs
    assert "python3 -m ari_os.install --uninstall" in docs
