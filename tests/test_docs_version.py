from pathlib import Path

from ari_os.tools import arios


def test_readme_documents_all_arios_cortex_subcommands():
    readme = Path("README.md").read_text()

    for subcommand in ("embeddings", "mode", "wander", "ears", "lens", "status"):
        assert f"arios cortex {subcommand}" in readme


def test_version_files_are_2_3_0():
    assert Path("ari_os/VERSION").read_text().strip() == "2.3.0"
    assert 'version = "2.3.0"' in Path("pyproject.toml").read_text()


def test_documented_cortex_subcommands_match_cli_choices():
    readme = Path("README.md").read_text()
    documented = {
        word
        for word in ("embeddings", "mode", "wander", "ears", "lens", "status")
        if f"arios cortex {word}" in readme
    }

    assert documented == {
        "embeddings",
        "mode",
        "wander",
        "ears",
        "lens",
        "status",
    }
    assert set(arios.cortex_status()) == {
        "embeddings",
        "mode",
        "wander",
        "ears",
        "lens",
    }
