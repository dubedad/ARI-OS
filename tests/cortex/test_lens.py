from __future__ import annotations

import json
from pathlib import Path


def test_parse_card_reads_frontmatter_and_body(tmp_path: Path) -> None:
    from ari_os.tools.cortex.media.lens_adapter import parse_card

    card_path = tmp_path / "lens" / "signals" / "published" / "taste-001.md"
    card_path.parent.mkdir(parents=True)
    card_path.write_text(
        "---\n"
        "id: taste-001\n"
        "genre: signal\n"
        "title: Taste Is Evidence\n"
        "tags:\n"
        "  - media\n"
        "related:\n"
        "  - taste-002\n"
        "owner: local\n"
        "---\n"
        "The card body survives intact.\n",
    )

    card = parse_card(card_path)

    assert card.slug == "taste-001"
    assert card.kind == "trend"
    assert card.genre == "signal"
    assert card.title == "Taste Is Evidence"
    assert card.tags == ["media"]
    assert card.related == ["taste-002"]
    assert card.owner == "local"
    assert card.body == "The card body survives intact."
    assert card.source_path == card_path


def test_lens_returns_card_from_state_home_when_enabled(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex import mcp_tools

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))
    (home / "config.json").write_text(json.dumps({"cortex": {"lens": True}}))
    card_path = home / "lens" / "signals" / "published" / "outcome-brief.md"
    card_path.parent.mkdir(parents=True)
    card_path.write_text(
        "---\n"
        "id: outcome-brief\n"
        "genre: method\n"
        "title: Outcome Brief\n"
        "---\n"
        "Define the outcome before choosing the path.\n",
    )

    result = mcp_tools.lens(home / "brain.db", "outcome-brief")

    assert "# Outcome Brief" in result
    assert "Define the outcome before choosing the path." in result


def test_lens_disabled_and_missing_slug_return_clean_messages(
    tmp_path: Path, monkeypatch
) -> None:
    from ari_os.tools.cortex import mcp_tools

    home = tmp_path / ".ari-os"
    home.mkdir()
    monkeypatch.setenv("ARI_OS_HOME", str(home))

    off = mcp_tools.lens(home / "brain.db", "anything")
    assert "brain.lens is off" in off

    (home / "config.json").write_text(json.dumps({"cortex": {"lens": True}}))
    missing = mcp_tools.lens(home / "brain.db", "missing-card")
    assert missing == "## LENS card not found: missing-card\n"
