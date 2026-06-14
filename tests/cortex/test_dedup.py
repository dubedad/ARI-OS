"""P4 memory dedup tests: cosine nearest-neighbor hygiene helper."""
from __future__ import annotations

from pathlib import Path

from ari_os.tools.cortex import dedup


class _StubEmbed:
    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self.vectors[text] for text in texts]


def _write_memory(path: Path, description: str) -> None:
    path.write_text(
        "---\n"
        f"description: {description}\n"
        "---\n\n"
        f"# {path.stem}\n",
        encoding="utf-8",
    )


def test_parse_memory_description_reads_frontmatter(tmp_path: Path):
    memory = tmp_path / "memory.md"
    _write_memory(memory, "A clear reusable system pattern.")

    assert dedup.parse_memory_description(memory) == "A clear reusable system pattern."


def test_run_dedup_check_ranks_near_duplicate_above_distinct(tmp_path: Path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    _write_memory(
        memory_dir / "near-a.md",
        "Prefer outcome definitions instead of prompt micromanagement.",
    )
    _write_memory(
        memory_dir / "near-b.md",
        "Define the outcome tightly before asking a model to create.",
    )
    _write_memory(
        memory_dir / "distinct.md",
        "Mac overlay windows need explicit compositor flushes.",
    )

    new_text = "A tight outcome brief beats micromanaging model prompts."
    embed_client = _StubEmbed(
        {
            new_text: [1.0, 0.0, 0.0],
            "Prefer outcome definitions instead of prompt micromanagement.": [0.99, 0.01, 0.0],
            "Define the outcome tightly before asking a model to create.": [0.95, 0.05, 0.0],
            "Mac overlay windows need explicit compositor flushes.": [0.0, 1.0, 0.0],
        }
    )

    result = dedup.run_dedup_check(
        new_text,
        memory_dir,
        top_k=3,
        embed_client=embed_client,
    )

    nearest = result["entries"][0]["nearest"]
    assert [Path(item["path"]).name for item in nearest] == [
        "near-a.md",
        "near-b.md",
        "distinct.md",
    ]
    assert nearest[0]["similarity"] > nearest[1]["similarity"] > nearest[2]["similarity"]
    assert embed_client.calls == [
        [
            new_text,
            "Mac overlay windows need explicit compositor flushes.",
            "Prefer outcome definitions instead of prompt micromanagement.",
            "Define the outcome tightly before asking a model to create.",
        ]
    ]
