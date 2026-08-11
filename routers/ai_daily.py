"""Authenticated AI Daily JSON API."""
from __future__ import annotations
import json, threading
from datetime import date
from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from database import transaction
from services.ai_daily_service import backfill_japanese_content, get_daily, refresh
from services.ai_daily_translation_service import translation_provider_status

router = APIRouter(prefix="/api/ai-daily", tags=["ai-daily"])
_refresh_lock = threading.Lock(); _last_refresh_failed = False

class ToggleInput(BaseModel): value: bool | None = None

def valid_date(value: str | None) -> str:
    try: return date.fromisoformat(value).isoformat() if value else date.today().isoformat()
    except ValueError as exc: raise HTTPException(422, "Invalid date") from exc

@router.get("")
def read_ai_daily(date_value: str | None = Query(None, alias="date")):
    result = get_daily(valid_date(date_value))
    if _last_refresh_failed and result["reading_list"]: result.update(using_saved_data=True, fetch_status="stale")
    return result

@router.post("/refresh")
def refresh_ai_daily(response: Response):
    global _last_refresh_failed
    if not _refresh_lock.acquire(False): raise HTTPException(409, "Refresh already in progress")
    try: result = refresh()
    finally: _refresh_lock.release()
    _last_refresh_failed = result["failed_feeds"] > 0
    if result["successful_feeds"] == 0: response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result

@router.post("/backfill-japanese")
def backfill_japanese(limit: int = Query(20, ge=1, le=50), dry_run: bool = Query(False)):
    return backfill_japanese_content(limit, dry_run=dry_run)

@router.get("/translation-status")
def translation_status():
    return translation_provider_status()

def _toggle(item_id: int, column: str, requested: bool | None):
    if column not in {"is_read", "is_favorite"}: raise HTTPException(400, "Invalid field")
    with transaction() as connection:
        row = connection.execute(f"SELECT {column} FROM ai_daily_items WHERE id=%s", (item_id,)).fetchone()
        if not row: raise HTTPException(404, "AI Daily item not found")
        value = not row[column] if requested is None else requested
        connection.execute(f"UPDATE ai_daily_items SET {column}=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s", (value,item_id))
    return {"id": item_id, column: value}

@router.patch("/items/{item_id}/read")
def toggle_read(item_id:int,payload:ToggleInput): return _toggle(item_id,"is_read",payload.value)
@router.patch("/items/{item_id}/favorite")
def toggle_favorite(item_id:int,payload:ToggleInput): return _toggle(item_id,"is_favorite",payload.value)

@router.post("/items/{item_id}/save-note",status_code=201)
def save_to_notes(item_id:int,response:Response):
    with transaction() as connection:
        item=connection.execute("SELECT * FROM ai_daily_items WHERE id=%s",(item_id,)).fetchone()
        if not item: raise HTTPException(404,"AI Daily item not found")
        if item["saved_note_id"] and connection.execute("SELECT 1 FROM notes WHERE id=%s",(item["saved_note_id"],)).fetchone():
            response.status_code=200; return {"item_id":item_id,"note_id":item["saved_note_id"],"already_saved":True}
        raw=f"AI Daily：{item['title']}\n\n## 要約\n\n{item['summary']}\n\n## なぜ重要か\n\n{item['why_it_matters']}\n\n## 出典\n\n情報元：{item['source_name']}\n元記事URL：{item['source_url']}"
        stored=item["tags"] if isinstance(item["tags"],list) else json.loads(item["tags"] or "[]")
        tags=list(dict.fromkeys(["AI Daily",item["category"],item["source_name"],*stored]))[:10]
        summary=item["summary"]+"\n\n"+" ".join(f"#{tag.replace(' ','_')}" for tag in tags)
        note_id=connection.execute("INSERT INTO notes(raw_text,ai_summary) VALUES(%s,%s) RETURNING id",(raw,summary)).fetchone()["id"]
        connection.execute("UPDATE ai_daily_items SET saved_note_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s",(note_id,item_id))
    return {"item_id":item_id,"note_id":note_id,"already_saved":False,"notes_url":f"/#note-{note_id}"}
