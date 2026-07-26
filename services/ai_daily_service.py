"""Persistence and rule-based edition generation for AI Daily."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

from services.ai_daily_feed_service import AI_DAILY_FEEDS, fetch_feed
from services.ai_daily_summary_service import MAX_AI_ITEMS_PER_REFRESH, enrich_item


WHY_BY_CATEGORY = {
    "fastapi": "API開発の保守性や安全性に関わる更新です。既存アプリへ適用できる点を確認しましょう。",
    "developer tools": "日々の開発フローを短縮し、AIとの協働を再現可能にするヒントになります。",
    "machine learning": "モデルの構築・評価・運用を現実のシステムへつなげる知識です。",
    "ai product": "AI機能の現在地を把握し、プロダクト設計や利用方法を見直す材料になります。",
}
DEFAULT_WHY = "AI分野の変化を理解し、次の学習や実践テーマを選ぶ材料になります。"


@contextmanager
def connect(db_path: str | Path):
    connection = sqlite3.connect(str(db_path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_ai_daily_db(db_path: str | Path) -> None:
    with connect(db_path) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS ai_daily_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                external_id TEXT,
                fallback_key TEXT NOT NULL,
                title TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                normalized_url TEXT NOT NULL,
                published_at TEXT,
                category TEXT NOT NULL,
                summary TEXT NOT NULL,
                why_it_matters TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
                is_favorite INTEGER NOT NULL DEFAULT 0 CHECK (is_favorite IN (0, 1)),
                saved_note_id INTEGER,
                fetched_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(saved_note_id) REFERENCES notes(id) ON DELETE SET NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_normalized_url ON ai_daily_items(normalized_url);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_fallback_key ON ai_daily_items(fallback_key);
            CREATE UNIQUE INDEX IF NOT EXISTS ux_ai_daily_external_id ON ai_daily_items(source_name, external_id)
                WHERE external_id IS NOT NULL AND external_id <> '';
            CREATE INDEX IF NOT EXISTS ix_ai_daily_published_at ON ai_daily_items(published_at DESC);
            CREATE TABLE IF NOT EXISTS ai_daily_editions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edition_date TEXT NOT NULL UNIQUE,
                learning_topic TEXT NOT NULL,
                learning_reason TEXT NOT NULL,
                learning_minutes INTEGER NOT NULL,
                learning_points TEXT NOT NULL,
                growth_notes_relation TEXT NOT NULL,
                practice_title TEXT NOT NULL,
                practice_description TEXT NOT NULL,
                practice_minutes INTEGER NOT NULL,
                generated_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tags_for_item(item: dict) -> list[str]:
    candidates = [item["source_name"], item["category"], *item.get("ai_tags", [])]
    title = item["title"].casefold()
    keywords = {
        "agent": "Agents", "model": "Models", "api": "API", "security": "Security",
        "python": "Python", "fastapi": "FastAPI", "gemini": "Gemini", "claude": "Claude",
        "openai": "OpenAI", "github": "GitHub",
    }
    candidates.extend(label for word, label in keywords.items() if word in title)
    result: list[str] = []
    for value in candidates:
        clean = " ".join(value.split())[:50]
        if clean and clean.casefold() not in {tag.casefold() for tag in result}:
            result.append(clean)
    return result[:6]


def why_it_matters(category: str) -> str:
    return WHY_BY_CATEGORY.get(category.casefold(), DEFAULT_WHY)


def save_items(db_path: str | Path, items: list[dict]) -> dict[str, int]:
    report = {"new_items": 0, "updated_items": 0, "skipped_items": 0}
    timestamp = now_utc()
    with connect(db_path) as connection:
        for item in items:
            existing = connection.execute(
                "SELECT id FROM ai_daily_items WHERE normalized_url=? OR fallback_key=? OR (source_name=? AND external_id=?) LIMIT 1",
                (item["normalized_url"], item["fallback_key"], item["source_name"], item.get("external_id")),
            ).fetchone()
            values = (
                item.get("external_id"), item["fallback_key"], item["title"], item["source_name"],
                item["source_url"], item["normalized_url"], item.get("published_at"), item["category"],
                item["summary"], item.get("why_it_matters") or why_it_matters(item["category"]), json.dumps(tags_for_item(item), ensure_ascii=False),
                timestamp, timestamp,
            )
            if existing:
                connection.execute("""
                    UPDATE ai_daily_items SET external_id=?, fallback_key=?, title=?, source_name=?, source_url=?,
                        normalized_url=?, published_at=?, category=?, summary=?, why_it_matters=?, tags=?,
                        fetched_at=?, updated_at=? WHERE id=?
                """, values + (existing["id"],))
                report["updated_items"] += 1
            else:
                connection.execute("""
                    INSERT INTO ai_daily_items (external_id, fallback_key, title, source_name, source_url,
                        normalized_url, published_at, category, summary, why_it_matters, tags, fetched_at,
                        created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values[:-1] + (timestamp, timestamp))
                report["new_items"] += 1
    return report


def _edition_content(category: str) -> dict:
    topic = category or "AI基礎"
    return {
        "learning_topic": topic,
        "learning_reason": f"本日の記事で扱われている「{topic}」を、ニュースだけで終わらせず自分の言葉で整理するためです。",
        "learning_minutes": 15,
        "learning_points": [f"{topic}の目的と利用場面", "従来手法との違い", "自分の業務や学習への適用例"],
        "growth_notes_relation": "学んだ要点と自分の判断をNotesへ残すことで、後から検索・振り返りができます。",
        "practice_title": f"{topic}を3行で説明する",
        "practice_description": "記事を1件選び、要点・重要な理由・次に試すことを各1行でノートにまとめてください。外部サービスの契約や危険な操作は不要です。",
        "practice_minutes": 20,
    }


def ensure_edition(db_path: str | Path, edition_date: str) -> dict:
    with connect(db_path) as connection:
        row = connection.execute("SELECT * FROM ai_daily_editions WHERE edition_date = ?", (edition_date,)).fetchone()
        if row:
            return edition_row(row)
        category_row = connection.execute("""
            SELECT category, COUNT(*) AS count FROM ai_daily_items
            WHERE COALESCE(substr(published_at, 1, 10), substr(fetched_at, 1, 10)) <= ?
            GROUP BY category ORDER BY count DESC, category LIMIT 1
        """, (edition_date,)).fetchone()
        content = _edition_content(category_row["category"] if category_row else "AI基礎")
        timestamp = now_utc()
        connection.execute("""
            INSERT INTO ai_daily_editions (edition_date, learning_topic, learning_reason, learning_minutes,
                learning_points, growth_notes_relation, practice_title, practice_description, practice_minutes,
                generated_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (edition_date, content["learning_topic"], content["learning_reason"], content["learning_minutes"],
              json.dumps(content["learning_points"], ensure_ascii=False), content["growth_notes_relation"],
              content["practice_title"], content["practice_description"], content["practice_minutes"],
              timestamp, timestamp, timestamp))
        row = connection.execute("SELECT * FROM ai_daily_editions WHERE edition_date = ?", (edition_date,)).fetchone()
        return edition_row(row)


def edition_row(row: sqlite3.Row) -> dict:
    return {
        "date": row["edition_date"],
        "learning": {"topic": row["learning_topic"], "reason": row["learning_reason"], "minutes": row["learning_minutes"],
                     "points": json.loads(row["learning_points"]), "growth_notes_relation": row["growth_notes_relation"]},
        "practice": {"title": row["practice_title"], "description": row["practice_description"], "minutes": row["practice_minutes"]},
        "generated_at": row["generated_at"],
    }


def item_row(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in ("id", "title", "source_name", "source_url", "published_at", "category", "summary", "why_it_matters", "saved_note_id")} | {
        "tags": json.loads(row["tags"] or "[]"), "is_read": bool(row["is_read"]), "is_favorite": bool(row["is_favorite"]),
    }


def get_daily(db_path: str | Path, edition_date: str) -> dict:
    with connect(db_path) as connection:
        rows = connection.execute("""
            SELECT * FROM ai_daily_items
            WHERE COALESCE(substr(published_at, 1, 10), substr(fetched_at, 1, 10)) <= ?
            ORDER BY COALESCE(published_at, fetched_at) DESC, id DESC LIMIT 50
        """, (edition_date,)).fetchall()
        last_updated = connection.execute("SELECT MAX(fetched_at) FROM ai_daily_items").fetchone()[0]
    items = [item_row(row) for row in rows]
    edition = ensure_edition(db_path, edition_date) if items else None
    highlights: list[dict] = []
    used_sources: set[str] = set()
    for item in items:
        if item["source_name"] not in used_sources or len(highlights) >= 3:
            highlights.append(item)
            used_sources.add(item["source_name"])
        if len(highlights) == 5:
            break
    return {"date": edition_date, "last_updated_at": last_updated, "highlights": highlights,
            "learning": edition["learning"] if edition else None, "practice": edition["practice"] if edition else None,
            "reading_list": items, "fetch_status": "ready" if items else "empty", "using_saved_data": False}


def refresh(db_path: str | Path) -> dict:
    report = {"feed_count": len(AI_DAILY_FEEDS), "successful_feeds": 0, "failed_feeds": 0,
              "new_items": 0, "updated_items": 0, "skipped_items": 0, "errors": []}
    ai_remaining = MAX_AI_ITEMS_PER_REFRESH
    for feed in AI_DAILY_FEEDS:
        try:
            items = fetch_feed(feed)
            if ai_remaining:
                with connect(db_path) as connection:
                    new_items = {item["normalized_url"] for item in items if not connection.execute(
                        "SELECT 1 FROM ai_daily_items WHERE normalized_url=? OR fallback_key=? OR (source_name=? AND external_id=?)",
                        (item["normalized_url"], item["fallback_key"], item["source_name"], item.get("external_id")),
                    ).fetchone()}
                enriched = []
                for item in items:
                    if item["normalized_url"] in new_items and ai_remaining:
                        item = enrich_item(item)
                        ai_remaining -= 1
                    enriched.append(item)
                items = enriched
            saved = save_items(db_path, items)
            report["successful_feeds"] += 1
            for key in ("new_items", "updated_items", "skipped_items"):
                report[key] += saved[key]
        except Exception as exc:
            report["failed_feeds"] += 1
            report["errors"].append({"source": feed["name"], "message": "取得できませんでした"})
    ensure_edition(db_path, date.today().isoformat()) if report["new_items"] or report["updated_items"] else None
    return report
