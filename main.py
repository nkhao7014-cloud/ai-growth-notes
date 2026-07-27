from __future__ import annotations

import calendar
import os
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from ai_client import analyze_note_with_tags, extract_tags, normalize_tag, normalize_tags_in_text
from auth import (SecurityMiddleware, clear_failures, ensure_csrf, login_allowed, password_hash,
                  record_failure, safe_next, validate_settings, verify_csrf)
from database import database_health_check, initialize_database, transaction
from routers.ai_daily import router as ai_daily_router
from services.export_service import build_markdown
from services.weekly_report_service import build_weekly_report

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"

@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_settings(); initialize_database(); yield

app = FastAPI(title="AI Growth Notes", version="1.4.0", lifespan=lifespan)
app.add_middleware(SecurityMiddleware)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "missing-at-import"),
                   session_cookie="agn_session", max_age=int(os.getenv("SESSION_MAX_AGE", "604800")),
                   same_site="lax", https_only=is_production())
app.include_router(ai_daily_router)

class NoteInput(BaseModel): text: str
class FavoriteInput(BaseModel): is_favorite: bool

def format_notes(rows):
    return [{"id":r["id"],"raw_text":r["raw_text"],"ai_summary":normalize_tags_in_text(r["ai_summary"]),
             "tags":extract_tags(r["ai_summary"]),"created_at":r["created_at"].isoformat() if hasattr(r["created_at"],"isoformat") else str(r["created_at"] or ""),
             "is_favorite":bool(r["is_favorite"])} for r in rows]

def filter_notes_by_tag(notes, tag):
    selected=normalize_tag(tag)
    return notes if not selected else [n for n in notes if any(x.casefold()==selected.casefold() for x in n["tags"])]

def all_notes():
    with transaction() as c: rows=c.execute("SELECT id,raw_text,ai_summary,created_at,is_favorite FROM notes ORDER BY id DESC").fetchall()
    return format_notes(rows)

@app.get("/health")
def health():
    healthy = database_health_check()
    payload = {"status": "ok", "database": "ok"} if healthy else {
        "status": "unavailable",
        "database": "unavailable",
    }
    return JSONResponse(payload, status_code=200 if healthy else 503)

@app.get("/login",response_class=HTMLResponse)
def login_page(request:Request,next:str="/"):
    if request.session.get("authenticated"): return RedirectResponse(safe_next(next),303)
    return templates.TemplateResponse(request,"login.html",{"csrf_token":ensure_csrf(request),"next":safe_next(next),"error":None})

@app.post("/login",response_class=HTMLResponse)
def login(request:Request,username:str=Form(...),password:str=Form(...),csrf_token:str=Form(...),next:str=Form("/")):
    verify_csrf(request,csrf_token); key=request.client.host if request.client else "unknown"
    valid=False
    if login_allowed(key):
        try: valid=username==os.environ["APP_USERNAME"] and password_hash.verify(password,os.environ["APP_PASSWORD_HASH"])
        except Exception: valid=False
    if not valid:
        record_failure(key)
        return templates.TemplateResponse(request,"login.html",{"csrf_token":ensure_csrf(request),"next":safe_next(next),"error":"ユーザー名またはパスワードが正しくありません。"},status_code=401)
    clear_failures(key); request.session.clear(); request.session.update(authenticated=True,username=username,login_at=datetime.now().astimezone().isoformat()); ensure_csrf(request)
    return RedirectResponse(safe_next(next),303)

@app.post("/logout")
def logout(request:Request): request.session.clear(); return RedirectResponse("/login",303)

@app.post("/api/notes")
def create_note(note:NoteInput):
    result=analyze_note_with_tags(note.text)
    with transaction() as c: note_id=c.execute("INSERT INTO notes(raw_text,ai_summary) VALUES(%s,%s) RETURNING id",(note.text,result["summary"])).fetchone()["id"]
    return {"id":note_id,"summary":result["summary"],"tags":result["tags"]}

@app.put("/api/notes/{note_id}")
def update_note(note_id:int,note:NoteInput):
    text=note.text.strip()
    if not text: raise HTTPException(422,"Note text must not be empty")
    result=analyze_note_with_tags(text)
    with transaction() as c: row=c.execute("UPDATE notes SET raw_text=%s,ai_summary=%s WHERE id=%s RETURNING id",(text,result["summary"],note_id)).fetchone()
    if not row: raise HTTPException(404,"Note not found")
    return {"id":note_id,"summary":result["summary"],"tags":result["tags"]}

@app.delete("/api/notes/{note_id}")
def delete_note(note_id:int):
    with transaction() as c: row=c.execute("DELETE FROM notes WHERE id=%s RETURNING id",(note_id,)).fetchone()
    if not row: raise HTTPException(404,"Note not found")
    return {"deleted":True,"id":note_id}

@app.patch("/api/notes/{note_id}/favorite")
def set_favorite(note_id:int,favorite:FavoriteInput):
    with transaction() as c: row=c.execute("UPDATE notes SET is_favorite=%s WHERE id=%s RETURNING id",(favorite.is_favorite,note_id)).fetchone()
    if not row: raise HTTPException(404,"Note not found")
    return {"id":note_id,"is_favorite":favorite.is_favorite}

@app.get("/api/notes")
def list_notes(tag:str="",date:str=""):
    notes=filter_notes_by_tag(all_notes(),tag)
    return [n for n in notes if n["created_at"][:10]==date] if date.strip() else notes

@app.get("/api/stats")
def get_stats():
    notes=all_notes(); today=datetime.now().date(); start=today-timedelta(days=6)
    counts=Counter(t for n in notes for t in n["tags"]); distribution=sorted(counts.items(),key=lambda x:(-x[1],x[0].casefold()))
    return {"total_notes":len(notes),"today_notes":sum(n["created_at"][:10]==today.isoformat() for n in notes),
            "week_notes":sum(start.isoformat()<=n["created_at"][:10]<=today.isoformat() for n in notes),"favorite_notes":sum(n["is_favorite"] for n in notes),
            "tag_count":len(counts),"tag_occurrences":sum(counts.values()),"tag_distribution":[{"tag":t,"count":c} for t,c in distribution],"top_tags":[{"tag":t,"count":c} for t,c in distribution[:5]]}

@app.get("/api/calendar")
def get_calendar(year:int|None=None,month:int|None=None):
    now=datetime.now(); y=year or now.year; m=month or now.month
    if not 2000<=y<=2100 or not 1<=m<=12: raise HTTPException(422,"Invalid year or month")
    prefix=f"{y:04d}-{m:02d}"; result=[]
    with transaction() as c: rows=c.execute("SELECT created_at::date AS d,COUNT(*) AS count,COUNT(*) FILTER(WHERE is_favorite) AS favorite FROM notes WHERE to_char(created_at,'YYYY-MM')=%s GROUP BY d ORDER BY d",(prefix,)).fetchall()
    return [{"date":r["d"].isoformat(),"count":r["count"],"favorite":r["favorite"]} for r in rows]

def monthly_report(year=None,month=None):
    now=datetime.now(); y=year or now.year; m=month or now.month
    if not 2000<=y<=2100 or not 1<=m<=12: raise HTTPException(422,"Invalid year or month")
    start=f"{y:04d}-{m:02d}-01"; end=f"{y:04d}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}"
    notes=[n for n in all_notes() if start<=n["created_at"][:10]<=end]; dates=sorted({n["created_at"][:10] for n in notes}); tags=Counter(t for n in notes for t in n["tags"])
    return {"period":{"year":y,"month":m,"start":start,"end":end},"note_count":len(notes),"learning_days":len(dates),"continuous_days":calculate_continuous_days(dates),
            "new_tag_count":len(tags),"favorite_count":sum(n["is_favorite"] for n in notes),"learning_themes":[f"#{t} を中心にした学習" for t,_ in tags.most_common(3)],
            "favorite_notes":[{"id":n["id"],"text":n["raw_text"],"created_at":n["created_at"],"tags":n["tags"]} for n in notes if n["is_favorite"]][:5],
            "tag_analysis":[{"tag":t,"count":c} for t,c in tags.most_common(5)],"highlights":notes[:3],
            "ai_summary":f"今月は{len(notes)}件の学習記録を残しました。" if notes else "今月の学習記録はまだありません。",
            "recommended_actions":["最も多かったテーマを1つ選び、成果物としてまとめる"],"calendar":{"active_dates":dates,"counts":dict(Counter(n["created_at"][:10] for n in notes))}}

@app.get("/api/report/monthly")
def get_monthly_report(year:int|None=None,month:int|None=None): return monthly_report(year,month)
@app.get("/api/report/weekly")
def get_weekly_report():
    today=datetime.now().date(); start=today-timedelta(days=6); notes=[n for n in all_notes() if start.isoformat()<=n["created_at"][:10]<=today.isoformat()]
    return {"period":{"start":start.isoformat(),"end":today.isoformat()},"note_count":len(notes),**build_weekly_report(notes)}
@app.get("/api/search")
def search_notes(q:str="",tag:str=""):
    term=q.strip().casefold(); notes=all_notes(); notes=[n for n in notes if not term or term in (n["raw_text"] or "").casefold() or term in (n["ai_summary"] or "").casefold()]
    return filter_notes_by_tag(notes,tag)
@app.get("/api/timeline")
def timeline():
    groups=[]
    for note in sorted(all_notes(),key=lambda n:(n["created_at"],n["id"]),reverse=True):
        d=note["created_at"][:10]
        if not groups or groups[-1]["date"]!=d: groups.append({"date":d,"label":"Today" if d==datetime.now().date().isoformat() else d,"notes":[]})
        groups[-1]["notes"].append(note)
    return groups
@app.get("/api/export/markdown")
def export_markdown(): return Response(build_markdown(all_notes()).encode(),media_type="text/markdown",headers={"Content-Disposition":f'attachment; filename="ai-growth-notes-{datetime.now():%Y%m%d-%H%M%S}.md"'})
@app.get("/api/report/monthly/export")
def export_monthly(year:int|None=None,month:int|None=None):
    r=monthly_report(year,month); lines=[f"# AI Growth Notes Monthly Report {r['period']['year']}年{r['period']['month']}月","",r["ai_summary"]]
    return Response("\n".join(lines).encode(),media_type="text/markdown",headers={"Content-Disposition":f'attachment; filename="ai-growth-monthly-{r["period"]["year"]:04d}{r["period"]["month"]:02d}.md"'})

def calculate_continuous_days(values):
    if not values:return 0
    dates={datetime.strptime(x,"%Y-%m-%d").date() for x in values}; cursor=max(dates); count=0
    while cursor in dates: count+=1; cursor-=timedelta(days=1)
    return count

app.mount("/static",StaticFiles(directory=str(ROOT/"static")),name="static")
@app.get("/")
def home(): return FileResponse(ROOT/"static"/"index.html")
@app.get("/ai-daily")
def ai_daily(): return FileResponse(ROOT/"static"/"index.html")
