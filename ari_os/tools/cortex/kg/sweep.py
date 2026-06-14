"""Sweep memory chunks into KG entity and relation tables."""
from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ari_os.tools.cortex import config
from ari_os.tools.cortex.db import connect
from ari_os.tools.cortex.kg.extractor import extract_entities_and_relations
from ari_os.tools.cortex.kg.state import KG_MAX_TIER, KG_REGIONS, mark_extracted, select_unextracted
from ari_os.tools.cortex.kg.store import link_entity_to_chunk, sanitize_label, upsert_entity, upsert_relation

logger = logging.getLogger(__name__)


@dataclass
class SweepStats:
    chunks_processed: int = 0
    entities_upserted: int = 0
    relations_upserted: int = 0
    skipped: int = 0
    failed: int = 0


class LLMUnavailable(RuntimeError):
    """Raised after consecutive LLM failures halt a sweep."""


_UNSET = object()
_MAX_CONSECUTIVE_FAILURES = 3
_MIN_TEXT_LEN = 20
_DEFAULT_CONCURRENCY = 12


@dataclass
class _ChunkResult:
    chunk_id: int
    ents: list = field(default_factory=list)
    rels: list = field(default_factory=list)
    error: Exception | None = None


def populate_kg(
    db_path: Path,
    *,
    llm: Any = _UNSET,
    fallback_llm: Any | None = None,
    min_tier: int = 2,
    limit: int | None = None,
    layers: set[str] | None = None,
) -> SweepStats:
    """Extract KG rows from all eligible chunks.

    This full sweep does not use ``kg_extract_state``. Re-running it is
    idempotent at the row level: existing entities and relations are updated
    through UPSERT counters instead of duplicated.
    """
    stats = SweepStats()
    resolved_llm = _resolve_llm(llm)
    if not _kg_enabled() or resolved_llm is None:
        return stats

    con = connect(db_path)
    try:
        if layers:
            placeholders = ",".join("?" * len(layers))
            query = (
                f"SELECT c.id, c.text FROM chunk c JOIN source s ON s.id = c.source_id "
                f"WHERE s.layer IN ({placeholders}) ORDER BY c.id"
            )
            params: tuple[object, ...] = tuple(sorted(layers))
        else:
            query = "SELECT id, text FROM chunk WHERE distillation_tier >= ? ORDER BY id"
            params = (min_tier,)
        if limit is not None:
            query += " LIMIT ?"
            params = (*params, int(limit))
        rows = [(int(row[0]), row[1]) for row in con.execute(query, params).fetchall()]
    finally:
        con.close()

    for chunk_id, text in rows:
        if not text or len(text.strip()) < _MIN_TEXT_LEN:
            stats.skipped += 1
            continue
        ents, rels = extract_entities_and_relations(
            text, resolved_llm, fallback_llm=fallback_llm
        )
        _commit_chunk(
            db_path,
            _ChunkResult(chunk_id=chunk_id, ents=ents, rels=rels),
            stats,
            mark_state=False,
        )

    return stats


def populate_kg_incremental(
    db_path: Path,
    *,
    llm: Any = _UNSET,
    regions: tuple[str, ...] = KG_REGIONS,
    max_tier: int = KG_MAX_TIER,
    limit: int | None = None,
) -> SweepStats:
    """Extract KG rows from not-yet-extracted chunks.

    The LLM work can run concurrently, but every SQLite write happens on the
    calling thread after a chunk result completes.
    """
    stats = SweepStats()
    resolved_llm = _resolve_llm(llm)
    if not _kg_enabled() or resolved_llm is None:
        return stats

    rows = select_unextracted(db_path, regions=regions, max_tier=max_tier, limit=limit)
    eligible = []
    for chunk_id, text in rows:
        if not text or len(text.strip()) < _MIN_TEXT_LEN:
            mark_extracted(db_path, chunk_id)
            stats.skipped += 1
            continue
        eligible.append((chunk_id, text))

    if not eligible:
        return stats

    concurrency = min(_concurrency_from_env(), max(1, len(eligible)))
    if concurrency <= 1:
        return _sweep_serial(db_path, eligible, resolved_llm, stats)
    return _sweep_concurrent(db_path, eligible, resolved_llm, stats, concurrency)


def _resolve_llm(llm: Any) -> Any | None:
    if llm is not _UNSET:
        return llm

    from ari_os.tools.cortex.llm import get_llm
    from ari_os.tools.cortex.model_routing import model_for_stage

    return get_llm(model_for_stage("kg_extraction"))


def _kg_enabled() -> bool:
    env = os.environ.get("ARI_OS_KG")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    return config.config_bool("cortex.kg", True)


def _norm(raw: str) -> str:
    return " ".join(raw.strip().split()).lower()


def _extract_chunk(chunk_id: int, text: str, llm: Any) -> _ChunkResult:
    try:
        ents, rels = extract_entities_and_relations(text, llm)
        return _ChunkResult(chunk_id=chunk_id, ents=ents, rels=rels)
    except Exception as exc:
        return _ChunkResult(chunk_id=chunk_id, error=exc)


def _concurrency_from_env() -> int:
    raw = os.environ.get("ARI_OS_KG_CONCURRENCY", "").strip()
    if not raw:
        return _DEFAULT_CONCURRENCY
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_CONCURRENCY


def _commit_chunk(
    db_path: Path,
    result: _ChunkResult,
    stats: SweepStats,
    *,
    mark_state: bool = True,
) -> None:
    now = int(time.time())
    ent_ids: dict[str, int] = {}
    for ent in result.ents:
        if not sanitize_label(ent.name):
            continue
        entity_id = upsert_entity(db_path, ent, now=now)
        link_entity_to_chunk(
            db_path,
            entity_id=entity_id,
            chunk_id=result.chunk_id,
            confidence=ent.confidence,
        )
        ent_ids[_norm(ent.name)] = entity_id
        stats.entities_upserted += 1

    for rel in result.rels:
        subject_id = ent_ids.get(_norm(rel.subject))
        object_id = ent_ids.get(_norm(rel.object))
        if subject_id is None or object_id is None:
            continue
        upsert_relation(
            db_path,
            rel,
            subject_id=subject_id,
            object_id=object_id,
            source_chunk_id=result.chunk_id,
            now=now,
        )
        stats.relations_upserted += 1

    if mark_state:
        mark_extracted(db_path, result.chunk_id, now=now)
    stats.chunks_processed += 1


def _sweep_serial(
    db_path: Path,
    eligible: list[tuple[int, str]],
    llm: Any,
    stats: SweepStats,
) -> SweepStats:
    consecutive_failures = 0
    for chunk_id, text in eligible:
        try:
            ents, rels = extract_entities_and_relations(text, llm)
        except Exception as exc:
            consecutive_failures += 1
            stats.failed += 1
            logger.warning("kg-extract: chunk %s failed: %s", chunk_id, exc)
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                raise LLMUnavailable(
                    f"{consecutive_failures} consecutive LLM failures; aborting run"
                ) from exc
            continue
        consecutive_failures = 0
        _commit_chunk(db_path, _ChunkResult(chunk_id=chunk_id, ents=ents, rels=rels), stats)
    return stats


def _sweep_concurrent(
    db_path: Path,
    eligible: list[tuple[int, str]],
    llm: Any,
    stats: SweepStats,
    concurrency: int,
) -> SweepStats:
    consecutive_failures = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_extract_chunk, chunk_id, text, llm): chunk_id
            for chunk_id, text in eligible
        }
        for future in as_completed(futures):
            result = future.result()
            if result.error is not None:
                consecutive_failures += 1
                stats.failed += 1
                logger.warning(
                    "kg-extract: chunk %s failed: %s", result.chunk_id, result.error
                )
                abort_at = _MAX_CONSECUTIVE_FAILURES + (
                    0 if stats.chunks_processed == 0 else concurrency
                )
                if consecutive_failures >= abort_at:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise LLMUnavailable(
                        f"{consecutive_failures} consecutive LLM failures; aborting run"
                    ) from result.error
                continue
            consecutive_failures = 0
            _commit_chunk(db_path, result, stats)

    return stats
