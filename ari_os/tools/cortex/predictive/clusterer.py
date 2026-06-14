"""HDBSCAN clustering over Hebbian + co-retrieval features."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from ari_os.tools.cortex.db import connect as _connect


def build_hebbian_matrix(db_path: Path) -> tuple[list[int], np.ndarray]:
    """Return (chunk_ids, NxN symmetric weight matrix) over Hebbian-connected chunks.

    Only chunks that appear in at least one hebbian tract_edge are included.
    """
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT from_chunk, to_chunk, weight FROM tract_edge WHERE tract='hebbian'"
        ).fetchall()
    finally:
        con.close()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)

    nodes: set[int] = set()
    for a, b, _ in rows:
        nodes.add(a)
        nodes.add(b)
    chunk_ids = sorted(nodes)
    idx = {cid: i for i, cid in enumerate(chunk_ids)}
    n = len(chunk_ids)
    X = np.zeros((n, n), dtype=np.float32)
    for a, b, w in rows:
        i, j = idx[a], idx[b]
        X[i, j] = max(X[i, j], float(w))
        X[j, i] = max(X[j, i], float(w))
    return chunk_ids, X


def build_co_retrieval_matrix(db_path: Path) -> tuple[list[int], np.ndarray]:
    """Return (chunk_ids, NxN co-retrieval frequency matrix).

    Two chunks co-occurring in the same retrieval_event row count once.
    """
    con = _connect(db_path)
    try:
        rows = con.execute("SELECT chunk_ids FROM retrieval_event").fetchall()
    finally:
        con.close()
    if not rows:
        return [], np.zeros((0, 0), dtype=np.float32)

    nodes: set[int] = set()
    parsed: list[list[int]] = []
    for (raw,) in rows:
        try:
            ids = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(ids, list):
            continue
        clean = [int(c) for c in ids if isinstance(c, int)]
        if len(clean) >= 2:
            parsed.append(clean)
            nodes.update(clean)
    if not nodes:
        return [], np.zeros((0, 0), dtype=np.float32)

    chunk_ids = sorted(nodes)
    idx = {cid: i for i, cid in enumerate(chunk_ids)}
    n = len(chunk_ids)
    X = np.zeros((n, n), dtype=np.float32)
    for ids in parsed:
        for a in ids:
            for b in ids:
                if a == b:
                    continue
                X[idx[a], idx[b]] += 1.0
    return chunk_ids, X


def combine_features(
    heb_ids: Sequence[int],
    heb_X: np.ndarray,
    co_ids: Sequence[int],
    co_X: np.ndarray,
    hebbian_weight: float = 1.0,
    co_weight: float = 0.5,
) -> tuple[list[int], np.ndarray]:
    """Union-align both feature spaces and return a weighted-sum NxN matrix."""
    union = sorted(set(heb_ids) | set(co_ids))
    if not union:
        return [], np.zeros((0, 0), dtype=np.float32)
    idx = {cid: i for i, cid in enumerate(union)}
    n = len(union)
    F = np.zeros((n, n), dtype=np.float32)
    if heb_ids:
        for a, ia in enumerate(heb_ids):
            for b, ib in enumerate(heb_ids):
                F[idx[ia], idx[ib]] += hebbian_weight * float(heb_X[a, b])
    if co_ids:
        co_max = float(co_X.max()) if co_X.size else 1.0
        norm = co_max if co_max > 0 else 1.0
        for a, ia in enumerate(co_ids):
            for b, ib in enumerate(co_ids):
                F[idx[ia], idx[ib]] += co_weight * float(co_X[a, b]) / norm
    return union, F


def cluster(
    chunk_ids: Sequence[int],
    F: np.ndarray,
    min_cluster_size: int = 3,
    min_samples: int | None = None,
) -> dict[int, tuple[int, float]]:
    """Run HDBSCAN on similarity matrix F; return {chunk_id: (cluster_id, probability)}.

    Noise points (HDBSCAN convention) get cluster_id = -1.
    """
    if not chunk_ids or F.size == 0:
        return {}
    from sklearn.cluster import HDBSCAN  # local import — keeps startup cheap

    fmax = float(F.max()) if F.size else 1.0
    if fmax <= 0:
        return {cid: (-1, 0.0) for cid in chunk_ids}
    D = (fmax - F).astype(np.float64)
    np.fill_diagonal(D, 0.0)
    clusterer = HDBSCAN(
        metric="precomputed",
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        allow_single_cluster=True,
    )
    labels = clusterer.fit_predict(D)
    probs = getattr(clusterer, "probabilities_", np.ones(len(labels), dtype=np.float64))
    return {
        cid: (int(labels[i]), float(probs[i]))
        for i, cid in enumerate(chunk_ids)
    }


def persist_clusters(
    db_path: Path,
    assignments: dict[int, tuple[int, float]],
    params: dict,
) -> int:
    """Write a new cluster_run + chunk_cluster rows. Returns new run_id."""
    now = int(time.time())
    n_chunks = len(assignments)
    cluster_ids = {cl for cl, _ in assignments.values()}
    n_clusters = len([c for c in cluster_ids if c != -1])
    n_noise = sum(1 for cl, _ in assignments.values() if cl == -1)
    con = _connect(db_path)
    try:
        cur = con.execute(
            "INSERT INTO cluster_run(ts, n_chunks, n_clusters, n_noise, params_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (now, n_chunks, n_clusters, n_noise, json.dumps(params, sort_keys=True)),
        )
        run_id = int(cur.lastrowid)
        con.executemany(
            "INSERT INTO chunk_cluster(run_id, chunk_id, cluster_id, probability) "
            "VALUES (?, ?, ?, ?)",
            [(run_id, cid, cl, prob) for cid, (cl, prob) in assignments.items()],
        )
        con.commit()
        return run_id
    finally:
        con.close()


def _filter_to_existing_chunks(db_path: Path, chunk_ids: Sequence[int]) -> set[int]:
    """Return the subset of chunk_ids that exist in the chunk table.

    Needed because retrieval_event.chunk_ids is JSON (no FK enforcement) — IDs there
    can outlive their chunk rows, and chunk_cluster has a FK constraint to chunk(id).
    """
    if not chunk_ids:
        return set()
    con = _connect(db_path)
    try:
        ids_csv = ",".join(str(int(c)) for c in chunk_ids)
        rows = con.execute(f"SELECT id FROM chunk WHERE id IN ({ids_csv})").fetchall()
    finally:
        con.close()
    return {int(r[0]) for r in rows}


def run_cluster_sweep(
    db_path: Path,
    min_cluster_size: int = 3,
    min_samples: int | None = None,
    hebbian_weight: float = 1.0,
    co_weight: float = 0.5,
) -> int:
    """Top-level entry: build features, cluster, persist, return run_id."""
    heb_ids, heb_X = build_hebbian_matrix(db_path)
    co_ids, co_X = build_co_retrieval_matrix(db_path)
    chunk_ids, F = combine_features(
        heb_ids, heb_X, co_ids, co_X, hebbian_weight=hebbian_weight, co_weight=co_weight
    )
    assignments = cluster(chunk_ids, F, min_cluster_size=min_cluster_size, min_samples=min_samples)
    if assignments:
        existing = _filter_to_existing_chunks(db_path, list(assignments.keys()))
        assignments = {cid: v for cid, v in assignments.items() if cid in existing}
    params = {
        "min_cluster_size": min_cluster_size,
        "min_samples": min_samples,
        "hebbian_weight": hebbian_weight,
        "co_weight": co_weight,
    }
    return persist_clusters(db_path, assignments, params)
