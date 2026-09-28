-- Provenance store schema (KT §11, Step 7). Two flat tables, no ORM.

-- Keyed by content hash, not by (config, stage): values shared upstream of the
-- first differing model (most eventual derived configurations, per N19) are
-- stored once regardless of how many configurations produced them.
CREATE TABLE IF NOT EXISTS stage_output_values (
    content_hash  TEXT PRIMARY KEY,
    payload       JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per run_pipeline() call (B5: written after, not during). Keyed by
-- the document's own content hash for the same de-duplication reason.
CREATE TABLE IF NOT EXISTS provenance_records (
    id            TEXT PRIMARY KEY,
    execution_set TEXT NOT NULL,
    config_label  TEXT NOT NULL,
    document      JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS provenance_records_execution_set_config_label_idx
    ON provenance_records (execution_set, config_label);

-- One row per orchestrator run (analysis.py / `python -m pvdials run`).
-- id doubles as the run id (no separate column) -- saved/updated after every
-- step, so a crash mid-run leaves a queryable partial row (status = last
-- step reached).
CREATE TABLE IF NOT EXISTS analyses (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status     TEXT NOT NULL,
    inputs     JSONB NOT NULL,
    phase1     JSONB,
    phase2     JSONB,
    phase3     JSONB,
    reexec     JSONB
);

-- Links an analysis to every provenance_records row it touched. A separate
-- link table, not a run-id column on provenance_records: that table's id is
-- content-derived (sha256 of the document JSON), so two analyses with
-- identical inputs produce the identical id -- a single owning-run column
-- could only ever point to whichever analysis inserted the row first. This
-- table lets every analysis that touched a given record be recorded,
-- dedup or not. ON DELETE CASCADE on both sides: a link has no meaning once
-- either side it points to is gone, and existing tests/scripts that clear
-- provenance_records directly (pre-dating this table) must keep working
-- unchanged, not start hitting a foreign-key violation.
CREATE TABLE IF NOT EXISTS analysis_records (
    analysis_id TEXT NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
    record_id   TEXT NOT NULL REFERENCES provenance_records(id) ON DELETE CASCADE,
    PRIMARY KEY (analysis_id, record_id)
);
