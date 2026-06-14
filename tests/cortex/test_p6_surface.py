"""P6 surface tests for toggles, predictive CLI, and prefetch skill."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ari_os.tools.cortex import config, db
from ari_os.tools.cortex.cortex import main


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.setenv("ARI_OS_BRAIN_DB", str(home / "brain.db"))
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    path = ari_home / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(db_path: Path, *, text: str, path: str, workspace: str = "surface") -> int:
    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', ?, 0, 'x', 0)",
            (path, workspace),
        )
        source_id = con.execute("SELECT id FROM source WHERE path = ?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) VALUES (?, 0, ?, 1, 2, 'wernicke', 0.5, 0)",
            (source_id, text),
        )
        return int(cur.lastrowid)
    finally:
        con.close()


def test_fsrs_and_predictive_toggles_read_config_and_env(
    ari_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"fsrs": False, "predictive": False}})
    )
    monkeypatch.delenv("ARI_OS_FSRS", raising=False)
    monkeypatch.delenv("ARI_OS_PREDICTIVE", raising=False)

    assert config.fsrs_enabled() is False
    assert config.predictive_enabled() is False

    monkeypatch.setenv("ARI_OS_FSRS", "1")
    monkeypatch.setenv("ARI_OS_PREDICTIVE", "yes")

    assert config.fsrs_enabled() is True
    assert config.predictive_enabled() is True


def test_prefetch_cli_exits_zero_and_renders_or_empty(brain_db: Path, tmp_path: Path):
    cwd = str(tmp_path / "project")
    first = _insert_chunk(brain_db, text="surface prefetch memory", path="surface.md")
    con = db.connect(brain_db)
    try:
        con.execute(
            "INSERT INTO retrieval_event(ts, query_text, cwd, branch, mode, consumer, chunk_ids) "
            "VALUES (1, 'q', ?, NULL, 'default', 'test', ?)",
            (cwd, json.dumps([first])),
        )
    finally:
        con.close()

    result = CliRunner().invoke(main, ["prefetch", "--cwd", cwd])

    assert result.exit_code == 0, result.output
    assert "workspace pre-fetch" in result.output
    assert "surface prefetch memory" in result.output

    empty = CliRunner().invoke(main, ["prefetch", "--cwd", str(tmp_path / "empty")])
    assert empty.exit_code == 0, empty.output
    assert empty.output == "\n"


def test_predict_and_prefetch_degrade_cleanly_when_disabled(
    ari_home: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ARI_OS_PREDICTIVE", "0")

    predict = CliRunner().invoke(main, ["predict", "--cluster", "--signals"])
    prefetch = CliRunner().invoke(main, ["prefetch", "--cwd", str(ari_home)])

    assert predict.exit_code == 0, predict.output
    assert prefetch.exit_code == 0, prefetch.output
    assert "cortex.predictive disabled" in predict.output
    assert "cortex.predictive disabled" in prefetch.output


def test_prefetch_skill_has_valid_frontmatter():
    skill = Path("ari_os/skills/prefetch/SKILL.md")

    content = skill.read_text()

    assert content.startswith("---\n")
    assert "\nname: prefetch\n" in content
    assert "\ndescription:" in content
    assert "\n---\n\n# Prefetch\n" in content
