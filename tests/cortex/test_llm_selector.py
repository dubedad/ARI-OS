from __future__ import annotations

import json
import struct
from pathlib import Path

from click.testing import CliRunner


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _vec(dim: int = 768) -> list[float]:
    out = [0.0] * dim
    out[0] = 1.0
    return out


class _StubEmbed:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vec() for _ in texts]


def _seed_chunk(db_path: Path, text: str) -> None:
    from ari_os.tools.cortex import db

    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES ('notes/llm-selector.md', 'semantic', 'selector', 0, 'x', 0)"
        )
        source_id = con.execute(
            "SELECT id FROM source WHERE path = 'notes/llm-selector.md'"
        ).fetchone()[0]
        cur = con.execute(
            """INSERT INTO chunk(
                 source_id, ordinal, text, line_start, line_end, region,
                 importance, distillation_tier
               ) VALUES (?, 0, ?, 1, 1, 'wernicke', 0.5, 0)""",
            (source_id, text),
        )
        chunk_id = int(cur.lastrowid)
        con.execute(
            "INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)",
            (chunk_id, _pack(_vec())),
        )
        con.commit()
    finally:
        con.close()


def test_llm_command_accepts_persists_and_reads_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)

    from ari_os.tools.cortex import config, cortex

    runner = CliRunner()
    for backend in ("ollama", "api", "off"):
        result = runner.invoke(cortex.main, ["llm", backend])

        assert result.exit_code == 0
        assert result.output.strip() == f"cortex.llm set: {backend}"
        assert config._config_value("cortex.llm") == backend
        assert json.loads((tmp_path / "config.json").read_text())["cortex.llm"] == backend

        readback = runner.invoke(cortex.main, ["llm"])

        assert readback.exit_code == 0
        assert readback.output.strip() == backend


def test_llm_command_rejects_invalid_backend(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)

    from ari_os.tools.cortex import cortex

    result = CliRunner().invoke(cortex.main, ["llm", "bogus"])

    assert result.exit_code != 0


def test_llm_off_still_allows_core_retrieval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARI_OS_HOME", str(tmp_path))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)

    from ari_os.tools.cortex import config, db, mcp_tools, retrieve
    from ari_os.tools.cortex import llm as llm_mod

    config.set_config_value("cortex.llm", "off")
    assert mcp_tools._cortex_llm_enabled() is False

    def _raise_if_called(spec=None):
        raise AssertionError("retrieve should not load an LLM when cortex.llm is off")

    monkeypatch.setattr(llm_mod, "get_llm", _raise_if_called)

    db_path = tmp_path / "brain.db"
    db.init_db(db_path)
    seeded = "The selector retrieval token is KIWISELECTOR."
    _seed_chunk(db_path, seeded)

    result = retrieve.retrieve(
        db_path,
        query="KIWISELECTOR",
        embed_client=_StubEmbed(),
        cwd=str(tmp_path),
        mode="default",
    )

    assert any(seeded in chunk.text for chunk in result.chunks)
