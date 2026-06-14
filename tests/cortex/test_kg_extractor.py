"""LLM-gated KG entity and relation extraction."""
from __future__ import annotations

from ari_os.tools.cortex.kg.extractor import (
    ExtractedEntity,
    ExtractedRelation,
    confidence_label,
    extract_entities,
    extract_entities_and_relations,
    parse_entity_lines,
    parse_relation_lines,
)


class StubLLM:
    def __init__(self, responses: list[list[str]]) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def extract_entities(self, text: str) -> list[str]:
        self.prompts.append(text)
        if not self.responses:
            return []
        return self.responses.pop(0)


def test_confidence_label_maps_thresholds():
    assert confidence_label(0.85) == "EXTRACTED"
    assert confidence_label(0.84) == "INFERRED"
    assert confidence_label(0.55) == "INFERRED"
    assert confidence_label(0.54) == "AMBIGUOUS"


def test_parse_entity_lines_skips_malformed_and_normalizes_unknown_kind():
    assert parse_entity_lines(
        [
            "ARI OS | project | 0.95",
            "- Cortex | system | 1.2",
            "missing confidence | concept",
            "bad confidence | concept | nope",
            "no delimiters here",
            " | concept | 0.5",
        ]
    ) == [
        ExtractedEntity(name="ARI OS", kind="project", confidence=0.95),
        ExtractedEntity(name="Cortex", kind="concept", confidence=1.0),
    ]


def test_parse_relation_lines_skips_malformed_and_clamps_confidence():
    assert parse_relation_lines(
        [
            "ARI OS | uses | Cortex | 0.81",
            "* Cortex | powers | Recall | -0.5",
            "missing | fields | 0.7",
            "bad | confidence | value | nope",
            " | relates | Cortex | 0.6",
        ]
    ) == [
        ExtractedRelation(
            subject="ARI OS", predicate="uses", object="Cortex", confidence=0.81
        ),
        ExtractedRelation(
            subject="Cortex", predicate="powers", object="Recall", confidence=0.0
        ),
    ]


def test_extract_entities_calls_brain_llm_and_parses_entity_lines():
    llm = StubLLM(
        [
            [
                "ARI OS | project | 0.95",
                "ARI OS | uses | Cortex | 0.82",
                "Cortex | tool | 0.88",
            ]
        ]
    )

    assert extract_entities("ARI OS uses Cortex.", llm) == [
        ExtractedEntity(name="ARI OS", kind="project", confidence=0.95),
        ExtractedEntity(name="Cortex", kind="tool", confidence=0.88),
    ]
    assert "name | kind | confidence" in llm.prompts[0]
    assert "ARI OS uses Cortex." in llm.prompts[0]


def test_extract_entities_and_relations_uses_relation_prompt_after_entities():
    llm = StubLLM(
        [
            ["ARI OS | project | 0.95", "Cortex | tool | 0.88"],
            ["ARI OS | uses | Cortex | 0.82"],
        ]
    )

    entities, relations = extract_entities_and_relations("ARI OS uses Cortex.", llm)

    assert entities == [
        ExtractedEntity(name="ARI OS", kind="project", confidence=0.95),
        ExtractedEntity(name="Cortex", kind="tool", confidence=0.88),
    ]
    assert relations == [
        ExtractedRelation(
            subject="ARI OS", predicate="uses", object="Cortex", confidence=0.82
        )
    ]
    assert len(llm.prompts) == 2
    assert "subject | predicate | object | confidence" in llm.prompts[1]
    assert "ARI OS (project)" in llm.prompts[1]
    assert "Cortex (tool)" in llm.prompts[1]


def test_extract_entities_and_relations_uses_public_fallback_when_low_confidence():
    local = StubLLM(
        [
            ["ARI OS | project | 0.4"],
            ["ARI OS | mentions | Cortex | 0.4"],
        ]
    )
    fallback = StubLLM(
        [
            ["ARI OS | project | 0.96", "Cortex | tool | 0.9"],
            ["ARI OS | uses | Cortex | 0.91"],
        ]
    )

    entities, relations = extract_entities_and_relations(
        "ARI OS uses Cortex.", local, fallback_llm=fallback
    )

    assert entities == [
        ExtractedEntity(name="ARI OS", kind="project", confidence=0.96),
        ExtractedEntity(name="Cortex", kind="tool", confidence=0.9),
    ]
    assert relations == [
        ExtractedRelation(
            subject="ARI OS", predicate="uses", object="Cortex", confidence=0.91
        )
    ]
    assert len(local.prompts) == 2
    assert len(fallback.prompts) == 2


def test_extract_entities_and_relations_skips_relation_call_when_no_entities():
    llm = StubLLM([["bad line"]])

    assert extract_entities_and_relations("Nothing structured.", llm) == ([], [])
    assert len(llm.prompts) == 1
