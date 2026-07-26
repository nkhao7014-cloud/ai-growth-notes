"""HTTP API for AI Daily."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from services.ai_daily_service import connect, get_daily, refresh

router = APIRouter(prefix="/api/ai-daily", tags=["ai-daily"])
DB = "notes.db"
_refresh_lock = threading.Lock()
_last_refresh_failed = False


class ToggleInput(BaseModel):
    value: bool | None = None


def valid_date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid date") from exc


@router.get("")
def read_ai_daily(date_value: str | None = Query(None, alias="date")):
    result = get_daily(DB, valid_date(date_value))
    if _last_refresh_failed and result["reading_list"]:
        result["using_saved_data"] = True
        result["fetch_status"] = "stale"
    return result


@router.post("/refresh")
def refresh_ai_daily(response: Response):
    global _last_refresh_failed
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Refresh already in progress")
    try:
        result = refresh(DB)
    finally:
        _refresh_lock.release()
    if result["successful_feeds"] == 0:
        _last_refresh_failed = True
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        _last_refresh_failed = result["failed_feeds"] > 0
    return result


def _toggle(item_id: int, column: str, requested: bool | None) -> dict:
    with connect(DB) as connection:
        row = connection.execute(f"SELECT {column} FROM ai_daily_items WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="AI Daily item not found")
        value = not bool(row[column]) if requested is None else requested
        connection.execute(f"UPDATE ai_daily_items SET {column}=?, updated_at=? WHERE id=?",
                           (int(value), datetime.now().astimezone().isoformat(timespec="seconds"), item_id))
    return {"id": item_id, column: value}


@router.patch("/items/{item_id}/read")
def toggle_read(item_id: int, payload: ToggleInput):
    return _toggle(item_id, "is_read", payload.value)


@router.patch("/items/{item_id}/favorite")
def toggle_favorite(item_id: int, payload: ToggleInput):
    return _toggle(item_id, "is_favorite", payload.value)


@router.post("/items/{item_id}/save-note", status_code=201)
def save_to_notes(item_id: int, response: Response):
    with connect(DB) as connection:
        item = connection.execute("SELECT * FROM ai_daily_items WHERE id=?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="AI Daily item not found")
        if item["saved_note_id"] and connection.execute("SELECT 1 FROM notes WHERE id=?", (item["saved_note_id"],)).fetchone():
            response.status_code = 200
            return {"item_id": item_id, "note_id": item["saved_note_id"], "already_saved": True}
        raw_text = (f"AI Daily：{item['title']}\n\n## 要約\n\n{item['summary']}\n\n## なぜ重要か\n\n"
                    f"{item['why_it_matters']}\n\n## 自分の気づき\n\nここに自分の考えを記録してください。\n\n"
                    f"## 出典\n\n情報元：{item['source_name']}\n公開日：{item['published_at'] or '不明'}\n元記事URL：{item['source_url']}")
        tags = ["AI Daily", item["category"], item["source_name"], *json.loads(item["tags"] or "[]")]
        tags = list(dict.fromkeys(str(tag).strip() for tag in tags if str(tag).strip()))[:10]
        ai_summary = item["summary"] + "\n\n" + " ".join(f"#{tag.replace(' ', '_')}" for tag in tags)
        cursor = connection.execute("INSERT INTO notes (raw_text, ai_summary, created_at) VALUES (?, ?, ?)",
                                    (raw_text, ai_summary, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        note_id = cursor.lastrowid
        connection.execute("UPDATE ai_daily_items SET saved_note_id=?, updated_at=? WHERE id=?",
                           (note_id, datetime.now().astimezone().isoformat(timespec="seconds"), item_id))
    return {"item_id": item_id, "note_id": note_id, "already_saved": False, "notes_url": f"/#note-{note_id}"}
