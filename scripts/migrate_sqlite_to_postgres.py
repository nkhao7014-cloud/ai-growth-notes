"""Repeatable, conservative migration of the v1.3 SQLite data to PostgreSQL."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

# Load configuration relative to this file, never relative to the caller's cwd.
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from database import get_connection
from services.ai_daily_feed_service import normalized_url_or_fallback

TABLES = ("notes", "ai_daily_items", "ai_daily_editions")
ITEM_BODY_FIELDS = (
    "title", "source_name", "source_url", "published_at", "category", "summary",
    "why_it_matters", "tags", "fetched_at", "updated_at",
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def open_readonly(path: Path):
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _stats() -> Counter:
    return Counter(inserted=0, updated=0, skipped=0, conflicts=0, unmapped_foreign_keys=0)


def _note_key(row: dict) -> tuple:
    created = row.get("created_at")
    if isinstance(created, str) and created:
        try:
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            pass
    if isinstance(created, datetime):
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(timezone.utc).isoformat()
    return row.get("raw_text"), row.get("ai_summary"), created


def _target_counts(connection) -> dict[str, int]:
    return {table: connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"] for table in TABLES}


def migrate_notes(connection, source_rows: list[dict], dry_run: bool) -> tuple[dict[int, int | None], Counter]:
    """Map exact note copies, otherwise append; never overwrite a target note."""
    target_rows = connection.execute(
        "SELECT id,raw_text,ai_summary,created_at FROM notes ORDER BY id"
    ).fetchall()
    available: dict[tuple, list[int]] = {}
    for row in target_rows:
        available.setdefault(_note_key(row), []).append(row["id"])
    mapping: dict[int, int | None] = {}
    stats = _stats()
    virtual_id = -1
    for row in source_rows:
        matches = available.get(_note_key(row), [])
        if matches:
            mapping[row["id"]] = matches.pop(0)
            stats["skipped"] += 1
            continue
        if dry_run:
            mapping[row["id"]] = virtual_id
            virtual_id -= 1
        else:
            inserted = connection.execute(
                "INSERT INTO notes(raw_text,ai_summary,created_at,is_favorite) VALUES(%s,%s,%s,%s) RETURNING id",
                (row["raw_text"], row["ai_summary"], row["created_at"] or None, bool(row["is_favorite"])),
            ).fetchone()
            mapping[row["id"]] = inserted["id"]
        stats["inserted"] += 1
    return mapping, stats


def _find_item(connection, normalized_url: str, row: dict):
    """Prefer the business key; also detect the table's two secondary unique keys."""
    return connection.execute(
        "SELECT * FROM ai_daily_items WHERE normalized_url=%s "
        "OR fallback_key=%s OR (external_id IS NOT NULL AND external_id<>'' AND source_name=%s AND external_id=%s) "
        "ORDER BY CASE WHEN normalized_url=%s THEN 0 WHEN fallback_key=%s THEN 1 ELSE 2 END,id LIMIT 1",
        (normalized_url, row["fallback_key"], row["source_name"], row.get("external_id"),
         normalized_url, row["fallback_key"]),
    ).fetchone()


def migrate_items(connection, source_rows: list[dict], note_map: dict[int, int | None], dry_run: bool) -> tuple[dict[int, int | None], Counter]:
    item_map: dict[int, int | None] = {}
    stats = _stats()
    seen_urls: set[str] = set()
    virtual_id = -1
    for row in source_rows:
        normalized_url = normalized_url_or_fallback(row.get("source_url"), row["fallback_key"])
        try:
            existing = _find_item(connection, normalized_url, row)
            if normalized_url in seen_urls:
                stats["conflicts"] += 1
            seen_urls.add(normalized_url)
            saved_note_id = None
            if row.get("saved_note_id") is not None:
                saved_note_id = note_map.get(row["saved_note_id"])
                if saved_note_id is None:
                    stats["unmapped_foreign_keys"] += 1
                    print(f"WARNING ai_daily_items source_id={row['id']} normalized_url={normalized_url}: "
                          f"saved_note_id={row['saved_note_id']} cannot be mapped; using NULL")
            if existing:
                item_map[row["id"]] = existing["id"]
                if existing["normalized_url"] != normalized_url:
                    # A secondary unique key matched a different URL. Preserve its identity and URL.
                    stats["conflicts"] += 1
                    normalized_url = existing["normalized_url"]
                if not dry_run:
                    connection.execute(
                        "UPDATE ai_daily_items SET title=%s,source_name=%s,source_url=%s,normalized_url=%s,"
                        "published_at=%s,category=%s,summary=%s,why_it_matters=%s,tags=%s::jsonb,fetched_at=%s,updated_at=%s WHERE id=%s",
                        (row["title"], row["source_name"], row.get("source_url") or "", normalized_url,
                         row.get("published_at"), row["category"], row["summary"], row["why_it_matters"],
                         row["tags"], row["fetched_at"], row["updated_at"], existing["id"]),
                    )
                stats["updated"] += 1
                continue
            if dry_run:
                item_map[row["id"]] = virtual_id
                virtual_id -= 1
            else:
                inserted = connection.execute(
                    "INSERT INTO ai_daily_items(external_id,fallback_key,title,source_name,source_url,normalized_url,"
                    "published_at,category,summary,why_it_matters,tags,is_read,is_favorite,saved_note_id,fetched_at,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (row.get("external_id"), row["fallback_key"], row["title"], row["source_name"],
                     row.get("source_url") or "", normalized_url, row.get("published_at"), row["category"],
                     row["summary"], row["why_it_matters"], row["tags"], bool(row["is_read"]),
                     bool(row["is_favorite"]), saved_note_id, row["fetched_at"], row["created_at"], row["updated_at"]),
                ).fetchone()
                item_map[row["id"]] = inserted["id"]
            stats["inserted"] += 1
        except Exception as exc:
            raise RuntimeError(f"ai_daily_items source_id={row['id']} normalized_url={normalized_url}: {exc}") from exc
    return item_map, stats


def migrate_editions(connection, source_rows: list[dict], dry_run: bool) -> Counter:
    """Editions contain no item IDs in the current schema; edition_date is their stable key."""
    stats = _stats()
    existing_dates = {str(row["edition_date"]) for row in connection.execute("SELECT edition_date FROM ai_daily_editions").fetchall()}
    for row in source_rows:
        if str(row["edition_date"]) in existing_dates:
            stats["skipped"] += 1  # preserve an edition generated online
            continue
        existing_dates.add(str(row["edition_date"]))
        if not dry_run:
            try:
                connection.execute(
                    "INSERT INTO ai_daily_editions(edition_date,learning_topic,learning_reason,learning_minutes,learning_points,"
                    "growth_notes_relation,practice_title,practice_description,practice_minutes,generated_at,created_at,updated_at) "
                    "VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s)",
                    (row["edition_date"], row["learning_topic"], row["learning_reason"], row["learning_minutes"],
                     row["learning_points"], row["growth_notes_relation"], row["practice_title"],
                     row["practice_description"], row["practice_minutes"], row["generated_at"], row["created_at"], row["updated_at"]),
                )
            except Exception as exc:
                raise RuntimeError(f"ai_daily_editions source_id={row['id']} edition_date={row['edition_date']}: {exc}") from exc
        stats["inserted"] += 1
    return stats


def _fix_and_validate(connection, dry_run: bool) -> None:
    duplicates = connection.execute(
        "SELECT COUNT(*) AS n FROM (SELECT normalized_url FROM ai_daily_items GROUP BY normalized_url HAVING COUNT(*)>1) d"
    ).fetchone()["n"]
    bad_fks = connection.execute(
        "SELECT COUNT(*) AS n FROM ai_daily_items i LEFT JOIN notes n ON n.id=i.saved_note_id "
        "WHERE i.saved_note_id IS NOT NULL AND n.id IS NULL"
    ).fetchone()["n"]
    if duplicates or bad_fks:
        raise RuntimeError(f"validation failed: duplicate_normalized_urls={duplicates}, invalid_saved_note_ids={bad_fks}")
    sequence_issues = []
    for table in TABLES:
        if not dry_run:
            connection.execute(
                f"SELECT setval(pg_get_serial_sequence(%s,'id'),COALESCE((SELECT MAX(id) FROM {table}),1),"
                f"EXISTS(SELECT 1 FROM {table}))", (table,),
            )
        seq = connection.execute(
            "SELECT last_value,is_called FROM " + table + "_id_seq"
        ).fetchone()
        maximum = connection.execute(f"SELECT COALESCE(MAX(id),0) AS n FROM {table}").fetchone()["n"]
        effective_next = seq["last_value"] + (1 if seq["is_called"] else 0)
        if effective_next <= maximum:
            sequence_issues.append(f"{table}(next={effective_next},max={maximum})")
        if not dry_run and effective_next <= maximum:
            raise RuntimeError(f"sequence validation failed for {table}: next={effective_next}, max_id={maximum}")
    sequence_status = "needs_fix:" + ";".join(sequence_issues) if sequence_issues else "ok"
    print(f"Validation: duplicate_normalized_urls={duplicates}, invalid_saved_note_ids={bad_fks}, sequences={sequence_status}")


def _print_stats(name: str, stats: Counter) -> None:
    keys = ("inserted", "updated", "skipped", "conflicts", "unmapped_foreign_keys")
    print(name + ": " + ", ".join(f"{key}={stats[key]}" for key in keys))


def migrate(path: Path, dry_run: bool = False) -> None:
    before_hash = digest(path)
    source = open_readonly(path)
    try:
        actual = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = set(TABLES) - actual
        if missing:
            raise RuntimeError("Missing source tables: " + ", ".join(sorted(missing)))
        rows = {name: [dict(row) for row in source.execute(f'SELECT * FROM "{name}" ORDER BY id')] for name in TABLES}
    finally:
        source.close()
    print("Source SHA-256 before: " + before_hash)
    print("Source counts: " + ", ".join(f"{name}={len(rows[name])}" for name in TABLES))

    connection = get_connection()
    try:
        with connection.transaction():
            if dry_run:
                connection.execute("SET TRANSACTION READ ONLY")
            before_counts = _target_counts(connection)
            print("Target before: " + ", ".join(f"{k}={v}" for k, v in before_counts.items()))
            note_map, note_stats = migrate_notes(connection, rows["notes"], dry_run)
            _, item_stats = migrate_items(connection, rows["ai_daily_items"], note_map, dry_run)
            edition_stats = migrate_editions(connection, rows["ai_daily_editions"], dry_run)
            _fix_and_validate(connection, dry_run)
            after_counts = _target_counts(connection)
            if dry_run:
                after_counts = {table: before_counts[table] + stats["inserted"] for table, stats in (
                    ("notes", note_stats), ("ai_daily_items", item_stats), ("ai_daily_editions", edition_stats)
                )}
            print("Target after: " + ", ".join(f"{k}={v}" for k, v in after_counts.items()))
        _print_stats("notes", note_stats)
        _print_stats("ai_daily_items", item_stats)
        _print_stats("ai_daily_editions", edition_stats)
    except Exception:
        print("Migration failed; PostgreSQL transaction rolled back.", file=sys.stderr)
        raise
    finally:
        connection.close()
    after_hash = digest(path)
    print("Source SHA-256 after:  " + after_hash)
    if after_hash != before_hash:
        raise RuntimeError("Source SQLite file changed during migration")
    print("Dry run completed; PostgreSQL was not modified." if dry_run else "Migration completed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default="notes.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    sqlite_path = Path(args.sqlite_path)
    if not sqlite_path.is_file():
        raise SystemExit("SQLite file not found")
    migrate(sqlite_path, args.dry_run)
