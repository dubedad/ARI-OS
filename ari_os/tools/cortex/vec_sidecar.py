"""sqlite-vec partition-key sidecar for per-region KNN.

``chunk_vec`` is a flat vec0 brute scan; 7 naive per-region scans would be 7x
the vector cost. The sidecar ``chunk_vec_part`` carries the same embeddings
(backfilled by rowid join — never re-embedded) with ``region`` as a vec0
PARTITION KEY, so a per-region KNN prunes to that region's partition.

Posture:
- capability probe at migration — sqlite-vec without partition-key support
  means no sidecar, shared-pool-split continues;
- migration is an EXPLICIT CLI (``python -m ari_os.tools.cortex.vec_sidecar migrate``),
  never automatic in init_db;
- dual-write on ingest keeps the sidecar fresh; both helpers are no-ops when
  the sidecar doesn't exist;
- drift (row-count divergence vs chunk_vec) > 1% → region_knn returns None
  and logs — callers degrade to splitting the shared pool;
- additive: the live table is never rewritten; revert = DROP the sidecar.
"""
from __future__ import annotations

import logging
from pathlib import Path

SIDECAR_TABLE = "chunk_vec_part"
DRIFT_LIMIT = 0.01

log = logging.getLogger(__name__)


def has_sidecar(con) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (SIDECAR_TABLE,),
    ).fetchone() is not None


def supports_partition_keys(con) -> bool:
    """Capability probe: create/drop a throwaway partitioned vec0 table."""
    try:
        con.execute(
            "CREATE VIRTUAL TABLE _vec_part_probe "
            "USING vec0(embedding float[4], region text partition key)")
        con.execute("DROP TABLE _vec_part_probe")
        return True
    except Exception:
        try:
            con.execute("DROP TABLE IF EXISTS _vec_part_probe")
        except Exception:
            pass
        return False


def drift(con) -> float:
    """Fraction of chunk_vec rows the sidecar is missing (or has extra).

    Returns 0.0 when the sidecar has not been migrated yet — substrate-only
    callers treat "no sidecar" as "no drift to worry about". The caller that
    actually cares about drift gating should call has_sidecar() first.
    """
    n_main = con.execute("SELECT count(*) FROM chunk_vec").fetchone()[0]
    if not has_sidecar(con):
        return 0.0
    n_side = con.execute(f"SELECT count(*) FROM {SIDECAR_TABLE}").fetchone()[0]
    if n_main == 0:
        return 0.0 if n_side == 0 else 1.0
    return abs(n_main - n_side) / n_main


def migrate(db_path: Path, *, batch: int = 2000) -> dict:
    """Probe, create, and backfill the sidecar. Idempotent, additive only.

    Returns {"supported": bool, "created": bool, "backfilled": int,
    "total": int, "drift": float}.
    """
    from .db import connect

    con = connect(db_path)
    try:
        if not supports_partition_keys(con):
            log.warning("sqlite-vec lacks partition-key support; no sidecar")
            return {"supported": False, "created": False,
                    "backfilled": 0, "total": 0, "drift": 1.0}
        created = False
        if not has_sidecar(con):
            con.execute(
                f"CREATE VIRTUAL TABLE {SIDECAR_TABLE} "
                "USING vec0(embedding float[768], region text partition key)")
            created = True

        existing = {r[0] for r in con.execute(
            f"SELECT rowid FROM {SIDECAR_TABLE}").fetchall()}
        rows = con.execute(
            "SELECT v.rowid, v.embedding, c.region "
            "FROM chunk_vec v JOIN chunk c ON c.id = v.rowid").fetchall()
        missing = [r for r in rows if r[0] not in existing]
        for i in range(0, len(missing), batch):
            con.execute("BEGIN IMMEDIATE")
            con.executemany(
                f"INSERT INTO {SIDECAR_TABLE}(rowid, embedding, region) "
                "VALUES (?, ?, ?)", missing[i:i + batch])
            con.execute("COMMIT")
        return {"supported": True, "created": created,
                "backfilled": len(missing), "total": len(rows),
                "drift": drift(con)}
    finally:
        con.close()


def _raise_if_vec0_missing(exc: Exception, op: str) -> None:
    """A sidecar table that EXISTS but can't be touched means the caller opened
    the DB without the sqlite-vec extension (raw sqlite3.connect). Swallowing
    that desyncs the sidecar from chunk_vec — fail loud instead."""
    if "no such module: vec0" in str(exc):
        raise RuntimeError(
            f"sidecar {op} failed: sqlite-vec (vec0) is not loaded on this "
            "connection. Open the DB with ari_os.tools.cortex.db.connect(), "
            "not raw sqlite3.connect()."
        ) from exc


def dual_write(con, rowid: int, packed_embedding: bytes, region: str) -> None:
    """Mirror a chunk_vec insert into the sidecar; no-op when absent."""
    try:
        if has_sidecar(con):
            con.execute(
                f"INSERT INTO {SIDECAR_TABLE}(rowid, embedding, region) "
                "VALUES (?, ?, ?)", (rowid, packed_embedding, region))
    except Exception as e:
        _raise_if_vec0_missing(e, "dual_write")
        log.exception("sidecar dual_write failed (rowid=%s)", rowid)


def dual_delete(con, rowid: int) -> None:
    """Mirror a chunk_vec delete; no-op when absent."""
    try:
        if has_sidecar(con):
            con.execute(
                f"DELETE FROM {SIDECAR_TABLE} WHERE rowid = ?", (rowid,))
    except Exception as e:
        _raise_if_vec0_missing(e, "dual_delete")
        log.exception("sidecar dual_delete failed (rowid=%s)", rowid)


def region_knn(
    db_path: Path,
    query_vec: list[float],
    *,
    k_per_region: int = 6,
    regions: tuple = None,
) -> dict[str, list[tuple[int, float]]] | None:
    """Per-region KNN over the sidecar; None = degrade to shared-pool-split.

    Returns {region: [(chunk_id, distance), ...]} for every region that has
    any rows. Degrades (None) when the sidecar is absent or drifted >1%.
    """
    from .db import connect

    if regions is None:
        # Region list is populated by ar.t6 (region_anchors). Substrate stays
        # region-agnostic — pass `regions=...` explicitly when calling.
        regions = ()

    con = connect(db_path)
    try:
        if not has_sidecar(con):
            return None
        d = drift(con)
        if d > DRIFT_LIMIT:
            log.warning("sidecar drift %.3f > %.2f — degrading to shared pool",
                        d, DRIFT_LIMIT)
            return None
        out: dict[str, list[tuple[int, float]]] = {}
        if not regions:
            return out
        packed = _pack_floats(query_vec)
        for region in regions:
            rows = con.execute(
                f"""SELECT rowid, distance FROM {SIDECAR_TABLE}
                    WHERE region = ? AND embedding MATCH ?
                    ORDER BY distance LIMIT ?""",
                (region, packed, k_per_region)).fetchall()
            if rows:
                out[region] = [(r[0], r[1]) for r in rows]
        return out
    finally:
        con.close()


def _pack_floats(vec: list[float]) -> bytes:
    """Pack a python list[float] into the raw bytes form sqlite-vec expects.

    Mirrors the source brain's `embed.pack_embedding`; duplicated here so the
    substrate has no embed dependency. Used only by region_knn().
    """
    import struct
    return struct.pack(f"{len(vec)}f", *vec)


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="vec sidecar utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    mig = sub.add_parser("migrate")
    mig.add_argument("--db", type=Path, required=True)
    st = sub.add_parser("status")
    st.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "migrate":
        print(json.dumps(migrate(args.db)))
    elif args.command == "status":
        from .db import connect
        con = connect(args.db)
        try:
            if not has_sidecar(con):
                print(json.dumps({"sidecar": False}))
            else:
                print(json.dumps({"sidecar": True, "drift": drift(con)}))
        finally:
            con.close()


if __name__ == "__main__":
    main()
