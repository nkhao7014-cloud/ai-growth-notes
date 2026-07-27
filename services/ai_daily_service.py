"""PostgreSQL persistence and rule-based edition generation for AI Daily."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from database import transaction
from services.ai_daily_feed_service import AI_DAILY_FEEDS, fetch_feed, normalized_url_or_fallback
from services.ai_daily_summary_service import MAX_AI_ITEMS_PER_REFRESH, enrich_item

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


def save_items(items: list[dict]) -> dict[str, int]:
    counts = {"new_items": 0, "updated_items": 0}
    timestamp = now_utc()
    with transaction() as connection:
        for item in items:
            normalized_url = normalized_url_or_fallback(item.get("source_url"), item["fallback_key"])
            row = connection.execute(
                "SELECT id FROM ai_daily_items WHERE normalized_url=%s OR fallback_key=%s OR "
                "(source_name=%s AND external_id=%s) LIMIT 1",
                (normalized_url, item["fallback_key"], item["source_name"], item.get("external_id")),
            ).fetchone()
            values = (item.get("external_id"), item["fallback_key"], item["title"], item["source_name"],
                      item.get("source_url") or "", normalized_url, item.get("published_at"), item["category"], item["summary"],
                      item.get("why_it_matters") or why_it_matters(item["category"]),
                      json.dumps(item.get("tags") or tags_for_item(item), ensure_ascii=False), timestamp, timestamp)
            if row:
                connection.execute(
                    "UPDATE ai_daily_items SET external_id=%s,fallback_key=%s,title=%s,source_name=%s,source_url=%s,"
                    "normalized_url=%s,published_at=%s,category=%s,summary=%s,why_it_matters=%s,tags=%s::jsonb,fetched_at=%s,updated_at=%s WHERE id=%s",
                    (*values, row["id"]),
                )
                counts["updated_items"] += 1
            else:
                connection.execute(
                    "INSERT INTO ai_daily_items(external_id,fallback_key,title,source_name,source_url,normalized_url,published_at,category,summary,"
                    "why_it_matters,tags,fetched_at,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
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
    for key in ("published_at", "fetched_at", "created_at", "updated_at"):
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
