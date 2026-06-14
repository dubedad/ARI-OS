"""Trend detection over cluster_run history."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ari_os.tools.cortex.db import connect as _connect


@dataclass
class TrendSignal:
    cluster_id: int
    old_size: int
    new_size: int
    growth_ratio: float
    window_seconds: int
    sample_chunk_ids: list[int] = field(default_factory=list)


def cluster_sizes_at(db_path: Path, run_id: int) -> dict[int, int]:
    """Return {cluster_id: chunk_count} for a given run, excluding noise (-1)."""
    con = _connect(db_path)
    try:
        rows = con.execute(
            "SELECT cluster_id, COUNT(*) FROM chunk_cluster "
            "WHERE run_id=? AND cluster_id != -1 GROUP BY cluster_id",
            (run_id,),
        ).fetchall()
    finally:
        con.close()
    return {int(cid): int(n) for cid, n in rows}


def detect_growth_signals(
    db_path: Path,
    growth_threshold: float = 4.0,
    window_seconds: int = 30 * 24 * 3600,  # 30 days
) -> list[TrendSignal]:
    """Compare most-recent cluster_run vs the oldest one inside the window.

    Returns one TrendSignal per cluster whose size grew by >= growth_threshold.
    """
    con = _connect(db_path)
    try:
        latest = con.execute(
            "SELECT run_id, ts FROM cluster_run ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return []
        latest_run, latest_ts = int(latest[0]), int(latest[1])
        earliest = con.execute(
            "SELECT run_id, ts FROM cluster_run WHERE ts >= ? ORDER BY ts ASC LIMIT 1",
            (latest_ts - window_seconds,),
        ).fetchone()
        if not earliest or earliest[0] == latest_run:
            return []
        old_run, old_ts = int(earliest[0]), int(earliest[1])
        signals: list[TrendSignal] = []
        old_sizes = cluster_sizes_at(db_path, old_run)
        new_sizes = cluster_sizes_at(db_path, latest_run)
        for cid, new_n in new_sizes.items():
            old_n = old_sizes.get(cid, 0)
            baseline = max(old_n, 1)
            ratio = new_n / baseline
            if ratio >= growth_threshold and new_n >= 3:
                samples = [
                    int(r[0])
                    for r in con.execute(
                        "SELECT chunk_id FROM chunk_cluster "
                        "WHERE run_id=? AND cluster_id=? LIMIT 5",
                        (latest_run, cid),
                    ).fetchall()
                ]
                signals.append(
                    TrendSignal(
                        cluster_id=cid,
                        old_size=old_n,
                        new_size=new_n,
                        growth_ratio=ratio,
                        window_seconds=latest_ts - old_ts,
                        sample_chunk_ids=samples,
                    )
                )
        return signals
    finally:
        con.close()
