"""PostgreSQL persistence and rule-based edition generation for AI Daily."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from database import transaction
from services.ai_daily_feed_service import AI_DAILY_FEEDS, fetch_feed, normalized_url_or_fallback
from services.ai_daily_summary_service import MAX_AI_ITEMS_PER_REFRESH, enrich_item
from services.ai_daily_translation_service import (
    translate_ai_daily_item,
    translation_needed,
    translation_provider_status,
    translation_succeeded,
)

WHY_BY_CATEGORY = {
    "fastapi": "API開発の保守性や安全性に関わる更新です。既存アプリへ適用できる点を確認しましょう。",
    "developer tools": "日々の開発フローを短縮し、AIとの協働を再現可能にするヒントになります。",
    "machine learning": "モデルの構築・評価・運用を現実のシステムへつなげる知識です。",
    "ai product": "AI機能の現在地を把握し、プロダクト設計や利用方法を見直す材料になります。",
}
DEFAULT_WHY = "AI分野の変化を理解し、次の学習や実践テーマを選ぶ材料になります。"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def tags_for_item(item: dict) -> list[str]:
    values = [item.get("category"), item.get("source_name")]
    return list(dict.fromkeys(str(x).strip() for x in values if str(x or "").strip()))[:6]


def why_it_matters(category: str) -> str:
    return WHY_BY_CATEGORY.get((category or "").casefold(), DEFAULT_WHY)


def _list_value(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def save_items(items: list[dict]) -> dict[str, int]:
    counts = {"new_items": 0, "updated_items": 0, "translated_items": 0}
    timestamp = now_utc()
    with transaction() as connection:
        for item in items:
            normalized_url = normalized_url_or_fallback(item.get("source_url"), item["fallback_key"])
            row = connection.execute(
                "SELECT id,title,summary,why_it_matters,title_ja,summary_ja,why_it_matters_ja,key_points_ja,translated_at "
                "FROM ai_daily_items WHERE normalized_url=%s OR fallback_key=%s OR "
                "(source_name=%s AND external_id=%s) LIMIT 1",
                (normalized_url, item["fallback_key"], item["source_name"], item.get("external_id")),
            ).fetchone()
            original_why = item.get("why_it_matters") or why_it_matters(item["category"])
            translation_input = {**item, "why_it_matters": original_why}
            if translation_needed(translation_input, row):
                translated = translate_ai_daily_item(translation_input)
                translated_at = timestamp
                counts["translated_items"] += 1
            else:
                translated = {key: row[key] for key in ("title_ja", "summary_ja", "why_it_matters_ja", "key_points_ja")}
                translated_at = row["translated_at"]
            values = (item.get("external_id"), item["fallback_key"], item["title"], item["source_name"],
                      item.get("source_url") or "", normalized_url, item.get("published_at"), item["category"], item["summary"],
                      original_why, translated["title_ja"], translated["summary_ja"], translated["why_it_matters_ja"],
                      json.dumps(_list_value(translated["key_points_ja"]), ensure_ascii=False), translated_at,
                      json.dumps(item.get("tags") or tags_for_item(item), ensure_ascii=False), timestamp, timestamp)
            if row:
                connection.execute(
                    "UPDATE ai_daily_items SET external_id=%s,fallback_key=%s,title=%s,source_name=%s,source_url=%s,"
                    "normalized_url=%s,published_at=%s,category=%s,summary=%s,why_it_matters=%s,"
                    "title_ja=%s,summary_ja=%s,why_it_matters_ja=%s,key_points_ja=%s::jsonb,translated_at=%s,"
                    "tags=%s::jsonb,fetched_at=%s,updated_at=%s WHERE id=%s",
                    (*values, row["id"]),
                )
                counts["updated_items"] += 1
            else:
                connection.execute(
                    "INSERT INTO ai_daily_items(external_id,fallback_key,title,source_name,source_url,normalized_url,published_at,category,summary,"
                    "why_it_matters,title_ja,summary_ja,why_it_matters_ja,key_points_ja,translated_at,tags,fetched_at,updated_at,created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s,%s,%s)",
                    (*values, timestamp),
                )
                counts["new_items"] += 1
    return counts


def _edition_content(category: str) -> dict:
    topic = category or "AI Product"
    return {"learning_topic": f"{topic}の最新動向を理解する", "learning_reason": WHY_BY_CATEGORY.get(topic.casefold(), DEFAULT_WHY),
            "learning_minutes": 10, "learning_points": ["変更点を一つ説明する", "自分の用途への影響を考える", "次の小さな実験を決める"],
            "growth_notes_relation": "気づきと次の行動をNotesへ残すと学習を継続できます。",
            "practice_title": "今日の一行メモ", "practice_description": "最も重要だった記事から、明日試すことを一行で記録してください。", "practice_minutes": 5}


def ensure_edition(edition_date: str) -> dict:
    with transaction() as connection:
        row = connection.execute("SELECT * FROM ai_daily_editions WHERE edition_date=%s", (edition_date,)).fetchone()
        if not row:
            category = connection.execute("SELECT category,COUNT(*) count FROM ai_daily_items GROUP BY category ORDER BY count DESC LIMIT 1").fetchone()
            content = _edition_content(category["category"] if category else "AI Product")
            timestamp = now_utc()
            row = connection.execute(
                "INSERT INTO ai_daily_editions(edition_date,learning_topic,learning_reason,learning_minutes,learning_points,growth_notes_relation,"
                "practice_title,practice_description,practice_minutes,generated_at,created_at,updated_at) "
                "VALUES(%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (edition_date, content["learning_topic"], content["learning_reason"], content["learning_minutes"],
                 json.dumps(content["learning_points"], ensure_ascii=False), content["growth_notes_relation"], content["practice_title"],
                 content["practice_description"], content["practice_minutes"], timestamp, timestamp, timestamp),
            ).fetchone()
    return edition_row(row)


def edition_row(row: dict) -> dict:
    points = row["learning_points"]
    if isinstance(points, str): points = json.loads(points)
    return {"learning": {"topic": row["learning_topic"], "reason": row["learning_reason"], "minutes": row["learning_minutes"],
                          "points": points, "growth_notes_relation": row["growth_notes_relation"]},
            "practice": {"title": row["practice_title"], "description": row["practice_description"], "minutes": row["practice_minutes"]}}


def item_row(row: dict) -> dict:
    value = dict(row)
    if isinstance(value.get("tags"), str): value["tags"] = json.loads(value["tags"] or "[]")
    if isinstance(value.get("key_points_ja"), str): value["key_points_ja"] = json.loads(value["key_points_ja"] or "[]")
    for key in ("published_at", "fetched_at", "created_at", "updated_at", "translated_at"):
        if value.get(key) and hasattr(value[key], "isoformat"): value[key] = value[key].isoformat()
    return value


def get_daily(edition_date: str) -> dict:
    edition = ensure_edition(edition_date)
    with transaction() as connection:
        rows = connection.execute("SELECT * FROM ai_daily_items ORDER BY published_at DESC NULLS LAST,id DESC LIMIT 60").fetchall()
        latest = connection.execute("SELECT MAX(fetched_at) AS value FROM ai_daily_items").fetchone()["value"]
    items = [item_row(row) for row in rows]
    return {"date": edition_date, "last_updated_at": latest.isoformat() if latest else None, "highlights": items[:3],
            "reading_list": items, **edition, "using_saved_data": False, "fetch_status": "ok"}


def backfill_japanese_content(limit: int = 20, dry_run: bool = False) -> dict:
    """Translate a bounded batch of existing rows; safe to run repeatedly."""
    limit = max(1, min(int(limit), 50))
    with transaction() as connection:
        rows = connection.execute(
            "SELECT id,title,summary,why_it_matters FROM ai_daily_items "
            "WHERE title_ja IS NULL OR title_ja='' OR summary_ja IS NULL OR summary_ja='' "
            "OR why_it_matters_ja IS NULL OR why_it_matters_ja='' OR key_points_ja IS NULL "
            "OR (title_ja=title AND summary_ja=summary) "
            "ORDER BY published_at DESC NULLS LAST,id DESC LIMIT %s",
            (limit,),
        ).fetchall()
    status = translation_provider_status()
    if dry_run:
        return {"candidate_items": len(rows), "processed_items": 0, "failed_items": 0,
                "dry_run": True, "translation_available": status["available"]}
    if not status["available"]:
        return {"candidate_items": len(rows), "processed_items": 0, "failed_items": 0,
                "dry_run": False, "translation_available": False}
    processed = failed = 0
    for row in rows:
        try:
            source = dict(row)
            translated = translate_ai_daily_item(source)
            succeeded = translation_succeeded(source, translated)
            with transaction() as connection:
                connection.execute(
                    "UPDATE ai_daily_items SET title_ja=%s,summary_ja=%s,why_it_matters_ja=%s,"
                    "key_points_ja=%s::jsonb,translated_at=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s",
                    (translated["title_ja"], translated["summary_ja"], translated["why_it_matters_ja"],
                     json.dumps(_list_value(translated["key_points_ja"]), ensure_ascii=False), now_utc(), row["id"]),
                )
            processed += 1
            if not succeeded:
                failed += 1
        except Exception:
            failed += 1
            continue
    return {"candidate_items": len(rows), "processed_items": processed, "failed_items": failed,
            "dry_run": False, "translation_available": True}


def refresh() -> dict:
    all_items, successful, failed = [], 0, 0
    for feed in AI_DAILY_FEEDS:
        try:
            fetched = fetch_feed(feed)
            successful += 1
            for item in fetched:
                item["why_it_matters"] = why_it_matters(item["category"])
                item["tags"] = tags_for_item(item)
            all_items.extend(fetched)
        except Exception:
            failed += 1
    for index, item in enumerate(all_items[:MAX_AI_ITEMS_PER_REFRESH]):
        all_items[index] = enrich_item(item)
    counts = save_items(all_items)
    ensure_edition(date.today().isoformat())
    return {**counts, "successful_feeds": successful, "failed_feeds": failed, "fetched_items": len(all_items)}
