from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest


def _pack(vec):
    return struct.pack(f"{len(vec)}f", *vec)


def _make_vec(dim: int, *, hot_index: int = 0, value: float = 1.0) -> list[float]:
    v = [0.0] * dim
    v[hot_index] = value
    return v


class StubEmbedClient:
    def __init__(self, table: dict[str, list[float]], dim: int = 768) -> None:
        self.table = table
        self.dim = dim
        self.calls: list[str] = []

    def embed(self, texts):
        out = []
        for text in texts:
            self.calls.append(text)
            out.append(self.table.get(text, [0.0] * self.dim))
        return out


class StubVisionClient:
    def __init__(self, caption: str) -> None:
        self.caption = caption
        self.calls: list[Path] = []

    def __call__(self, path: Path) -> str:
        self.calls.append(path)
        return self.caption


@pytest.fixture
def ari_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    monkeypatch.delenv("ARI_OS_LLM", raising=False)
    return home


@pytest.fixture
def brain_db(ari_home: Path) -> Path:
    from ari_os.tools.cortex import db

    path = ari_home / "brain.db"
    db.init_db(path)
    return path


def _insert_chunk(db_path: Path, *, text: str, region: str, vec, path: str) -> int:
    from ari_os.tools.cortex import db

    con = db.connect(db_path)
    try:
        con.execute(
            "INSERT OR IGNORE INTO source(path, layer, workspace, mtime, sha256, last_indexed_at) "
            "VALUES (?, 'semantic', NULL, 0, 'x', 0)",
            (path,),
        )
        sid = con.execute("SELECT id FROM source WHERE path=?", (path,)).fetchone()[0]
        cur = con.execute(
            "INSERT INTO chunk(source_id, ordinal, text, line_start, line_end, region, "
            "importance, distillation_tier) "
            "VALUES (?, 0, ?, 1, 1, ?, 0.5, 0)",
            (sid, text, region),
        )
        cid = cur.lastrowid
        con.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?, ?)", (cid, _pack(vec)))
        return cid
    finally:
        con.close()


def test_brain_see_returns_caption_and_similar_chunks_when_lens_enabled(
    ari_home: Path,
    brain_db: Path,
) -> None:
    from ari_os.tools.cortex import mcp_tools

    (ari_home / "config.json").write_text(json.dumps({"cortex": {"lens": True}}))
    image = ari_home / "sample.png"
    image.write_bytes(b"fake image bytes")

    caption = "cyan-lit glass sculpture with sharp reflective edges"
    qvec = _make_vec(768, hot_index=11)
    target = _insert_chunk(
        brain_db,
        text="Occipital note about cyan reflective installation lighting.",
        region="occipital",
        vec=qvec,
        path="vision-note.md",
    )
    vision = StubVisionClient(caption)
    embed = StubEmbedClient({caption: qvec})

    result = mcp_tools.see_image(
        brain_db,
        str(image),
        mode="visual",
        vision_client=vision,
        embed_client=embed,
    )

    assert result["caption"] == caption
    assert result["similar_chunks"], "brain.see should return similar chunks"
    assert result["similar_chunks"][0]["chunk_id"] == target
    assert result["similar_chunks"][0]["region"] == "occipital"
    assert vision.calls == [image]
    assert embed.calls == [caption]


def test_brain_see_default_off_never_calls_vision_backend(
    ari_home: Path,
    brain_db: Path,
) -> None:
    from ari_os.tools.cortex import mcp_tools

    image = ari_home / "sample.png"
    image.write_bytes(b"fake image bytes")
    vision = StubVisionClient("should not be used")
    embed = StubEmbedClient({})

    result = mcp_tools.see_image(
        brain_db,
        str(image),
        vision_client=vision,
        embed_client=embed,
    )

    assert result["caption"] is None
    assert result["similar_chunks"] == []
    assert "brain.see is off" in result["note"]
    assert vision.calls == []
    assert embed.calls == []


def test_brain_see_llm_off_never_calls_vision_backend(
    ari_home: Path,
    brain_db: Path,
) -> None:
    from ari_os.tools.cortex import mcp_tools

    (ari_home / "config.json").write_text(
        json.dumps({"cortex": {"lens": True, "llm": "off"}})
    )
    image = ari_home / "sample.png"
    image.write_bytes(b"fake image bytes")
    vision = StubVisionClient("should not be used")

    result = mcp_tools.see_image(brain_db, str(image), vision_client=vision)

    assert result["caption"] is None
    assert result["similar_chunks"] == []
    assert "cortex.llm is off" in result["note"]
    assert vision.calls == []
