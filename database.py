"""Central PostgreSQL access and non-destructive schema initialization."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

log = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    id BIGSERIAL PRIMARY KEY,
    raw_text TEXT,
    ai_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_favorite BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_notes_created_at ON notes(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_notes_favorite ON notes(is_favorite) WHERE is_favorite;

CREATE TABLE IF NOT EXISTS ai_daily_items (
    id BIGSERIAL PRIMARY KEY,
    external_id TEXT,
    fallback_key TEXT NOT NULL,
    title TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    normalized_url TEXT NOT NULL,
    published_at TIMESTAMPTZ,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    why_it_matters TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_read BOOLEAN NOT NULL DEFAULT FALSE,
    is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
    saved_note_id BIGINT REFERENCES notes(id) ON DELETE SET NULL,
    fetched_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_normalized_url ON ai_daily_items(normalized_url);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_fallback_key ON ai_daily_items(fallback_key);
CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_external_id ON ai_daily_items(source_name, external_id)
 WHERE external_id IS NOT NULL AND external_id <> '';
CREATE INDEX IF NOT EXISTS ix_ai_daily_published_at ON ai_daily_items(published_at DESC);

CREATE TABLE IF NOT EXISTS ai_daily_editions (
    id BIGSERIAL PRIMARY KEY,
    edition_date DATE NOT NULL UNIQUE,
    learning_topic TEXT NOT NULL,
    learning_reason TEXT NOT NULL,
    learning_minutes INTEGER NOT NULL,
    learning_points JSONB NOT NULL,
    growth_notes_relation TEXT NOT NULL,
    practice_title TEXT NOT NULL,
    practice_description TEXT NOT NULL,
    practice_minutes INTEGER NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def database_url() -> str:
    value = os.getenv("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required; set it to your Neon PostgreSQL connection string")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if not value.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("DATABASE_URL must be a PostgreSQL connection string")
    if value.startswith("postgresql+psycopg://"):
        value = "postgresql://" + value[len("postgresql+psycopg://"):]
    return value


def get_connection():
    return psycopg.connect(database_url(), connect_timeout=10, row_factory=dict_row)


@contextmanager
def transaction():
    connection = get_connection()
    try:
        with connection.transaction():
            yield connection
    except Exception:
        log.exception("Database transaction failed")
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with transaction() as connection:
        connection.execute(SCHEMA_SQL)
    log.info("PostgreSQL schema initialized")


def database_health_check() -> bool:
    try:
        with get_connection() as connection:
            return connection.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
    except Exception:
        log.warning("Database health check failed")
        return False
