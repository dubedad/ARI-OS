from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from ari_os.tools.cortex import cortex


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tune_inspects_active_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))

    result = CliRunner().invoke(cortex.main, ["tune"])

    assert result.exit_code == 0, result.output
    assert "active mode:" in result.output
    assert "wernicke" in result.output
    assert "available modes" in result.output


def test_tuning_docs_are_linked():
    assert "Tuning your brain" in (REPO_ROOT / "README.md").read_text()
    assert "Tuning your brain" in (REPO_ROOT / "SETUP.md").read_text()
