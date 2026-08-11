"""Bounded PostgreSQL retrieval for the user's learning knowledge."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterable

from database import transaction

ALLOWED_SOURCES = {"notes", "ai_daily", "reports"}
MAX_LIMIT = 20
_STOP_WORDS = {
    "について", "まとめて", "ください", "教えて", "最近", "過去", "自分", "ノート",
    "学び", "学ん", "学習", "何を", "今週", "今月", "振り返って", "次に", "すべき",
}


def _keywords(query: str) -> list[str]:
    if re.search(r"何を学|学習傾向|一番多いテーマ|よく出てくるタグ|今週の学習|今月の学習|成長を振り返|次に何を", query):
        return []
    separated = re.sub(r"(について|に関する|を|は|が|の|で|から|してください|まとめて)", " ", query)
    values = re.findall(r"[A-Za-z0-9][A-Za-z0-9_.+#-]*|[一-龥ァ-ヶー]{2,}", separated)
    result: list[str] = []
    for value in values:
        cleaned = value.strip("#").casefold()
        if cleaned and cleaned not in _STOP_WORDS and cleaned not in result:
            result.append(cleaned)
    return result[:6]


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value or "")


def _tags(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value[:10]]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed[:10]]
        except json.JSONDecodeError:
            return re.findall(r"#([^\s#]+)", value)[:10]
    return []


def _where(keywords: list[str], date_from: date | None, date_to: date | None, fields: Iterable[str], date_field: str):
    clauses, params = [], []
    if keywords:
        clauses.append("(" + " OR ".join(f"{field} ILIKE %s" for word in keywords for field in fields) + ")")
        params.extend(f"%{word}%" for word in keywords for _ in fields)
    if date_from:
        clauses.append(f"{date_field}::date >= %s")
        params.append(date_from)
    if date_to:
        clauses.append(f"{date_field}::date <= %s")
        params.append(date_to)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def search_user_knowledge(
    query: str,
    limit: int = 10,
    date_from: date | None = None,
    date_to: date | None = None,
    sources: list[str] | None = None,
) -> list[dict]:
    """Return a small, normalized set of records. Callers never write SQL."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    selected = set(sources or ALLOWED_SOURCES)
    invalid = selected - ALLOWED_SOURCES
    if invalid:
        raise ValueError("Unsupported source: " + ", ".join(sorted(invalid)))
    words = _keywords(query)
    rows: list[dict] = []
    per_source = min(MAX_LIMIT, max(limit * 2, 10))
    with transaction() as connection:
        if "notes" in selected:
            where, params = _where(words, date_from, date_to, ("raw_text", "ai_summary"), "created_at")
            found = connection.execute(
                "SELECT id,raw_text,ai_summary,created_at FROM notes" + where +
                " ORDER BY created_at DESC,id DESC LIMIT %s", (*params, per_source),
            ).fetchall()
            for row in found:
                rows.append({"id": row["id"], "source_type": "note", "date": _iso(row["created_at"]),
                             "title": (row["raw_text"] or "Note").splitlines()[0][:120],
                             "content": (row["ai_summary"] or row["raw_text"] or "")[:1400],
                             "preview": (row["raw_text"] or row["ai_summary"] or "")[:240],
                             "tags": re.findall(r"#([^\s#]+)", row["ai_summary"] or "")[:10]})
        if "ai_daily" in selected:
            where, params = _where(words, date_from, date_to,
                                    ("title", "summary", "why_it_matters", "title_ja", "summary_ja",
                                     "why_it_matters_ja", "key_points_ja::text", "category", "tags::text"),
                                    "COALESCE(published_at,created_at)")
            found = connection.execute(
                "SELECT id,title,summary,why_it_matters,title_ja,summary_ja,why_it_matters_ja,key_points_ja,"
                "tags,COALESCE(published_at,created_at) AS knowledge_date "
                "FROM ai_daily_items" + where + " ORDER BY knowledge_date DESC,id DESC LIMIT %s",
                (*params, per_source),
            ).fetchall()
            for row in found:
                title = row.get("title_ja") or row["title"]
                summary = row.get("summary_ja") or row["summary"]
                why = row.get("why_it_matters_ja") or row["why_it_matters"]
                points = _tags(row.get("key_points_ja"))
                content = "\n".join([summary, why, *points])
                rows.append({"id": row["id"], "source_type": "ai_daily", "date": _iso(row["knowledge_date"]),
                             "title": title[:120], "content": content[:1400],
                             "preview": summary[:240], "tags": _tags(row["tags"])})
        if "reports" in selected:
            where, params = _where(words, date_from, date_to,
                                    ("learning_topic", "learning_reason", "growth_notes_relation", "learning_points::text"),
                                    "edition_date")
            found = connection.execute(
                "SELECT id,edition_date,learning_topic,learning_reason,learning_points FROM ai_daily_editions" +
                where + " ORDER BY edition_date DESC,id DESC LIMIT %s", (*params, per_source),
            ).fetchall()
            for row in found:
                rows.append({"id": row["id"], "source_type": "report", "date": _iso(row["edition_date"]),
                             "title": row["learning_topic"][:120],
                             "content": (row["learning_reason"] + "\n" + str(row["learning_points"]))[:1400],
                             "preview": row["learning_reason"][:240], "tags": []})
    rows.sort(key=lambda item: item["date"], reverse=True)
    return rows[:limit]
