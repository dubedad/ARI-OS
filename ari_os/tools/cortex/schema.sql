-- ARI-OS Cortex — single-machine brain schema (SQLite + sqlite-vec)

CREATE TABLE IF NOT EXISTS source (
  id          INTEGER PRIMARY KEY,
  path        TEXT UNIQUE NOT NULL,
  layer       TEXT NOT NULL,
  workspace   TEXT,
  mtime       INTEGER NOT NULL,
  sha256      TEXT NOT NULL,
  last_indexed_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk (
  id                INTEGER PRIMARY KEY,
  source_id         INTEGER NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  ordinal           INTEGER NOT NULL,
  text              TEXT NOT NULL,
  line_start        INTEGER NOT NULL,
  line_end          INTEGER NOT NULL,
  region            TEXT NOT NULL,
  importance        REAL NOT NULL DEFAULT 0.5,
  retrieved_count   INTEGER NOT NULL DEFAULT 0,
  last_retrieved_at INTEGER,
  distillation_tier INTEGER NOT NULL DEFAULT 0,
  parent_chunks     TEXT,
  distilled_at      INTEGER,
  consolidated_at   INTEGER,
  session_id        TEXT,
  created_ts        INTEGER
);

CREATE INDEX IF NOT EXISTS idx_chunk_source ON chunk(source_id);
CREATE INDEX IF NOT EXISTS idx_chunk_region ON chunk(region);
CREATE INDEX IF NOT EXISTS idx_chunk_tier_age ON chunk(distillation_tier, distilled_at);
CREATE INDEX IF NOT EXISTS idx_chunk_retrieved ON chunk(retrieved_count DESC);

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(embedding float[768]);

CREATE TABLE IF NOT EXISTS tract_edge (
  from_chunk     INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  to_chunk       INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  tract          TEXT NOT NULL,
  weight         REAL NOT NULL DEFAULT 0.5,
  co_activations INTEGER NOT NULL DEFAULT 0,
  last_fired_at  INTEGER,
  PRIMARY KEY (from_chunk, to_chunk, tract)
);

CREATE INDEX IF NOT EXISTS idx_tract_from ON tract_edge(from_chunk, weight DESC);
CREATE INDEX IF NOT EXISTS idx_tract_decay ON tract_edge(last_fired_at);

CREATE TABLE IF NOT EXISTS retrieval_event (
  id          INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  query_text  TEXT,
  cwd         TEXT,
  branch      TEXT,
  mode        TEXT NOT NULL DEFAULT 'default',
  consumer    TEXT NOT NULL,
  chunk_ids   TEXT NOT NULL,
  top_distance REAL,
  session_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_retrieval_ts ON retrieval_event(ts DESC);

CREATE TABLE IF NOT EXISTS retrieval_metrics (
  id                 INTEGER PRIMARY KEY,
  retrieval_event_id INTEGER,
  ts                 INTEGER NOT NULL,
  intent             TEXT,
  confidence         REAL,
  tokens_budget      INTEGER NOT NULL,
  tokens_packed      INTEGER NOT NULL,
  tokens_wasted      INTEGER NOT NULL,
  n_zones            INTEGER NOT NULL DEFAULT 0,
  per_zone_json      TEXT,
  assembler_on       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_retrieval_metrics_ts ON retrieval_metrics(ts DESC);

CREATE TABLE IF NOT EXISTS chunk_usage (
  id                 INTEGER PRIMARY KEY,
  retrieval_event_id INTEGER,
  chunk_id           INTEGER NOT NULL,
  overlap_score      REAL NOT NULL,
  decided_by         TEXT NOT NULL,
  used               INTEGER NOT NULL,
  judged_at          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunk_usage_event ON chunk_usage(retrieval_event_id);
CREATE INDEX IF NOT EXISTS idx_chunk_usage_chunk ON chunk_usage(chunk_id);

-- ------------------------------------------------------------------
-- Semantic knowledge graph
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS kg_entity (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  kind          TEXT NOT NULL,
  canonical_id  INTEGER REFERENCES kg_entity(id) ON DELETE SET NULL,
  confidence    REAL NOT NULL DEFAULT 0.5,
  first_seen_at INTEGER NOT NULL,
  last_seen_at  INTEGER NOT NULL,
  mention_count INTEGER NOT NULL DEFAULT 1,
  UNIQUE(name, kind)
);

CREATE INDEX IF NOT EXISTS idx_kg_entity_name ON kg_entity(name);
CREATE INDEX IF NOT EXISTS idx_kg_entity_kind ON kg_entity(kind);

CREATE TABLE IF NOT EXISTS kg_entity_chunk (
  entity_id  INTEGER NOT NULL REFERENCES kg_entity(id) ON DELETE CASCADE,
  chunk_id   INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  confidence REAL NOT NULL DEFAULT 0.5,
  PRIMARY KEY (entity_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_entity_chunk_entity ON kg_entity_chunk(entity_id);
CREATE INDEX IF NOT EXISTS idx_kg_entity_chunk_chunk  ON kg_entity_chunk(chunk_id);

CREATE TABLE IF NOT EXISTS kg_relation (
  id              INTEGER PRIMARY KEY,
  subject_id      INTEGER NOT NULL REFERENCES kg_entity(id) ON DELETE CASCADE,
  predicate       TEXT NOT NULL,
  object_id       INTEGER NOT NULL REFERENCES kg_entity(id) ON DELETE CASCADE,
  confidence      REAL NOT NULL DEFAULT 0.5,
  source_chunk_id INTEGER REFERENCES chunk(id) ON DELETE SET NULL,
  first_seen_at   INTEGER NOT NULL,
  last_seen_at    INTEGER NOT NULL,
  evidence_count  INTEGER NOT NULL DEFAULT 1,
  UNIQUE(subject_id, predicate, object_id)
);

CREATE INDEX IF NOT EXISTS idx_kg_relation_subject ON kg_relation(subject_id);
CREATE INDEX IF NOT EXISTS idx_kg_relation_object  ON kg_relation(object_id);
CREATE INDEX IF NOT EXISTS idx_kg_relation_pred    ON kg_relation(predicate);

-- ------------------------------------------------------------------
-- FSRS spaced-repetition state
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS fsrs_state (
  chunk_id        INTEGER PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
  stability       REAL NOT NULL DEFAULT 1.0,
  difficulty      REAL NOT NULL DEFAULT 5.0,
  retrievability  REAL NOT NULL DEFAULT 0.9,
  reps            INTEGER NOT NULL DEFAULT 0,
  lapses          INTEGER NOT NULL DEFAULT 0,
  last_review_at  INTEGER NOT NULL,
  next_review_at  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fsrs_next ON fsrs_state(next_review_at);

-- ------------------------------------------------------------------
-- Predictive / cross-context clustering
-- ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS chunk_cluster (
  run_id       INTEGER NOT NULL,
  chunk_id     INTEGER NOT NULL REFERENCES chunk(id) ON DELETE CASCADE,
  cluster_id   INTEGER NOT NULL,
  probability  REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (run_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_cluster_run     ON chunk_cluster(run_id);
CREATE INDEX IF NOT EXISTS idx_chunk_cluster_cluster ON chunk_cluster(run_id, cluster_id);
CREATE INDEX IF NOT EXISTS idx_chunk_cluster_chunk   ON chunk_cluster(chunk_id);

CREATE TABLE IF NOT EXISTS cluster_run (
  run_id      INTEGER PRIMARY KEY,
  ts          INTEGER NOT NULL,
  n_chunks    INTEGER NOT NULL,
  n_clusters  INTEGER NOT NULL,
  n_noise     INTEGER NOT NULL,
  params_json TEXT NOT NULL
);

-- ------------------------------------------------------------------
-- Hybrid recall (FTS5) + meta
-- ------------------------------------------------------------------

CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
  text, content='chunk', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS chunk_fts_ai AFTER INSERT ON chunk BEGIN
  INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunk_fts_ad AFTER DELETE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS chunk_fts_au AFTER UPDATE ON chunk BEGIN
  INSERT INTO chunk_fts(chunk_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO chunk_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS meta (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS kg_extract_state (
  chunk_id          INTEGER PRIMARY KEY REFERENCES chunk(id) ON DELETE CASCADE,
  extracted_at      INTEGER NOT NULL,
  extractor_version INTEGER NOT NULL DEFAULT 1
);
