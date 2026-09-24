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
