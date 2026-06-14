"""Entity and relation extraction over chunk text."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


FALLBACK_CONFIDENCE_THRESHOLD = 0.6

_VALID_KINDS = {
    "project",
    "person",
    "voice",
    "tool",
    "brand",
    "concept",
    "workspace",
    "place",
}


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    kind: str
    confidence: float


@dataclass(frozen=True)
class ExtractedRelation:
    subject: str
    predicate: str
    object: str
    confidence: float


class _LLMShape(Protocol):
    def extract_entities(self, text: str) -> list[str]: ...


def confidence_label(conf: float) -> str:
    """Return the reporting label for a numeric KG confidence."""
    if conf >= 0.85:
        return "EXTRACTED"
    if conf >= 0.55:
        return "INFERRED"
    return "AMBIGUOUS"


def parse_entity_lines(lines: list[str]) -> list[ExtractedEntity]:
    """Parse ``name | kind | confidence`` lines defensively."""
    out: list[ExtractedEntity] = []
    for raw_line in lines:
        line = raw_line.strip().lstrip("-* ").strip()
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 3:
            continue

        name, kind, confidence_raw = parts
        if not name or not kind:
            continue
        confidence = _parse_confidence(confidence_raw)
        if confidence is None:
            continue

        normalized_kind = kind.lower()
        if normalized_kind not in _VALID_KINDS:
            normalized_kind = "concept"
        out.append(
            ExtractedEntity(
                name=name,
                kind=normalized_kind,
                confidence=confidence,
            )
        )
    return out


def parse_relation_lines(lines: list[str]) -> list[ExtractedRelation]:
    """Parse ``subject | predicate | object | confidence`` lines defensively."""
    out: list[ExtractedRelation] = []
    for raw_line in lines:
        line = raw_line.strip().lstrip("-* ").strip()
        if not line or "|" not in line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4:
            continue

        subject, predicate, object_name, confidence_raw = parts
        if not subject or not predicate or not object_name:
            continue
        confidence = _parse_confidence(confidence_raw)
        if confidence is None:
            continue
        out.append(
            ExtractedRelation(
                subject=subject,
                predicate=predicate,
                object=object_name,
                confidence=confidence,
            )
        )
    return out


def extract_entities(text: str, llm: _LLMShape) -> list[ExtractedEntity]:
    """Ask the configured LLM for entity candidates and parse valid rows."""
    raw = llm.extract_entities(_ENTITY_PROMPT.format(body=text))
    return parse_entity_lines(raw)


def extract_entities_and_relations(
    text: str,
    llm: _LLMShape,
    *,
    fallback_llm: _LLMShape | None = None,
) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
    """Extract entities, then grounded relations conditioned on those entities.

    The optional fallback is public and explicit: callers pass an API-backed
    adapter when configured. This module never reads provider-specific env gates.
    """
    entities = extract_entities(text, llm)
    relations = _extract_relations(text, entities, llm)

    if fallback_llm is not None and _average_confidence(entities) < FALLBACK_CONFIDENCE_THRESHOLD:
        fallback_entities = extract_entities(text, fallback_llm)
        fallback_relations = _extract_relations(text, fallback_entities, fallback_llm)
        return fallback_entities, fallback_relations

    return entities, relations


def _extract_relations(
    text: str,
    entities: list[ExtractedEntity],
    llm: _LLMShape,
) -> list[ExtractedRelation]:
    if not entities:
        return []
    raw = llm.extract_entities(
        _RELATION_PROMPT.format(
            entities="\n".join(f"- {entity.name} ({entity.kind})" for entity in entities),
            body=text,
        )
    )
    return parse_relation_lines(raw)


def _average_confidence(entities: list[ExtractedEntity]) -> float:
    if not entities:
        return 0.0
    return sum(entity.confidence for entity in entities) / len(entities)


def _parse_confidence(raw: str) -> float | None:
    try:
        value = float(raw.strip())
    except ValueError:
        return None
    return max(0.0, min(1.0, value))


_ENTITY_PROMPT = """\
Extract named entities from the text below. Output one entity per line as:
name | kind | confidence

Use kind from: project, person, voice, tool, brand, concept, workspace, place.
Use confidence from 0.0 to 1.0. Skip pronouns and stop words.

Text:
{body}
"""


_RELATION_PROMPT = """\
Given the entities below, list relations between them grounded in the text.
Output one relation per line as:
subject | predicate | object | confidence

Use a short predicate phrase such as uses, mentions, blocks, supersedes, or ships_as.
Use confidence from 0.0 to 1.0.

Entities:
{entities}

Text:
{body}
"""
