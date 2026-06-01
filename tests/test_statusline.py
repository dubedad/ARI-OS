import json
from ari_os.tools.statusline import build_line

def test_build_line_basic():
    payload = {"model": {"display_name": "claude-opus-4-8"},
               "workspace": {"current_dir": "/x/my-project"}}
    line = build_line(payload, branch="main", dirty=True, workers=1, now="00:24",
                      ctx_pct=19)
    assert "19%" in line
    assert "claude-opus-4-8" in line
    assert "my-project" in line
    assert "main*" in line
    assert "1" in line and "🛠" in line
    assert "00:24" in line
    assert " · " in line

def test_degrades_without_git_or_workers():
    payload = {"model": {"display_name": "m"}, "workspace": {"current_dir": "/x/p"}}
    line = build_line(payload, branch=None, dirty=False, workers=0, now="01:00",
                      ctx_pct=None)
    assert "main" not in line          # no branch segment
    assert "0🛠" in line
    assert line.count(" · ") >= 1      # still a valid joined line
