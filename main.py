import sqlite3
from collections import Counter
from datetime import datetime, timedelta
import calendar

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from ai_client import analyze_note_with_tags, extract_tags, normalize_tag, normalize_tags_in_text
from services.export_service import build_markdown
from services.weekly_report_service import build_weekly_report
from routers.ai_daily import router as ai_daily_router
import routers.ai_daily as ai_daily_routes
from services.ai_daily_service import init_ai_daily_db

load_dotenv()

app = FastAPI()

DB = "notes.db"


def init_db():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        raw_text TEXT,
        ai_summary TEXT,
        created_at TEXT
    )
    """)

    columns = {row[1] for row in cur.execute("PRAGMA table_info(notes)")}
    if "is_favorite" not in columns:
        cur.execute("ALTER TABLE notes ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")

    conn.commit()
    conn.close()
    init_ai_daily_db(DB)


init_db()

ai_daily_routes.DB = DB
app.include_router(ai_daily_router)


class NoteInput(BaseModel):
    text: str


class FavoriteInput(BaseModel):
    is_favorite: bool


@app.post("/api/notes")
def create_note(note: NoteInput):
    result = analyze_note_with_tags(note.text)

    ai_text = result["summary"]
    tags = result["tags"]

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO notes (
            raw_text,
            ai_summary,
            created_at
        )
        VALUES (?, ?, ?)
        """,
        (
            note.text,
            ai_text,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    note_id = cur.lastrowid

    conn.commit()
    conn.close()

    return {
        "id": note_id,
        "summary": ai_text,
        "tags": tags
    }


@app.put("/api/notes/{note_id}")
def update_note(note_id: int, note: NoteInput):
    text = note.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Note text must not be empty")

    conn = sqlite3.connect(DB)
    if not conn.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="Note not found")
    conn.close()

    result = analyze_note_with_tags(text)
    conn = sqlite3.connect(DB)
    conn.execute(
        "UPDATE notes SET raw_text = ?, ai_summary = ? WHERE id = ?",
        (text, result["summary"], note_id),
    )
    conn.commit()
    conn.close()
    return {"id": note_id, "summary": result["summary"], "tags": result["tags"]}


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int):
    conn = sqlite3.connect(DB)
    cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    deleted = cursor.rowcount
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"deleted": True, "id": note_id}


@app.patch("/api/notes/{note_id}/favorite")
def set_favorite(note_id: int, favorite: FavoriteInput):
    conn = sqlite3.connect(DB)
    cursor = conn.execute(
        "UPDATE notes SET is_favorite = ? WHERE id = ?",
        (int(favorite.is_favorite), note_id),
    )
    conn.commit()
    updated = cursor.rowcount
    conn.close()
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"id": note_id, "is_favorite": favorite.is_favorite}


@app.get("/api/notes")
def list_notes(tag: str = "", date: str = ""):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            raw_text,
            ai_summary,
            created_at,
            is_favorite
        FROM notes
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    notes = filter_notes_by_tag(format_notes(rows), tag)
    selected_date = date.strip()
    if selected_date:
        notes = [note for note in notes if (note["created_at"] or "")[:10] == selected_date]
    return notes


@app.get("/api/stats")
def get_stats():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM notes")
    total_notes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM notes WHERE is_favorite = 1")
    favorite_notes = cur.fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now().date() - timedelta(days=6)).isoformat()
    cur.execute(
        "SELECT COUNT(*) FROM notes WHERE substr(created_at, 1, 10) = ?",
        (today,),
    )
    today_notes = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM notes WHERE substr(created_at, 1, 10) BETWEEN ? AND ?",
        (week_start, today),
    )
    week_notes = cur.fetchone()[0]

    cur.execute("SELECT ai_summary FROM notes")
    summaries = cur.fetchall()
    conn.close()

    tag_counts = Counter(
        tag
        for (summary,) in summaries
        for tag in extract_tags(summary or "")
    )
    tag_distribution = sorted(
        tag_counts.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    )
    top_tags = tag_distribution[:5]

    return {
        "total_notes": total_notes,
        "today_notes": today_notes,
        "week_notes": week_notes,
        "favorite_notes": favorite_notes,
        "tag_count": len(tag_counts),
        "tag_occurrences": sum(tag_counts.values()),
        "tag_distribution": [
            {"tag": tag, "count": count}
            for tag, count in tag_distribution
        ],
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in top_tags
        ],
    }


@app.get("/api/calendar")
def get_calendar(year: int | None = None, month: int | None = None):
    now = datetime.now()
    calendar_year = year or now.year
    calendar_month = month or now.month
    if calendar_year < 2000 or calendar_year > 2100 or calendar_month < 1 or calendar_month > 12:
        raise HTTPException(status_code=422, detail="Invalid year or month")

    month_prefix = f"{calendar_year:04d}-{calendar_month:02d}"
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT substr(created_at, 1, 10) AS note_date,
               COUNT(*) AS note_count,
               SUM(CASE WHEN is_favorite = 1 THEN 1 ELSE 0 END) AS favorite_count
        FROM notes
        WHERE substr(created_at, 1, 7) = ?
        GROUP BY substr(created_at, 1, 10)
        ORDER BY note_date
        """,
        (month_prefix,),
    ).fetchall()
    conn.close()
    return [
        {"date": row[0], "count": row[1], "favorite": row[2] or 0}
        for row in rows
    ]


@app.get("/api/report/monthly")
def get_monthly_report(year: int | None = None, month: int | None = None):
    now = datetime.now()
    report_year = year or now.year
    report_month = month or now.month
    if report_year < 2000 or report_year > 2100 or report_month < 1 or report_month > 12:
        raise HTTPException(status_code=422, detail="Invalid year or month")

    last_day = calendar.monthrange(report_year, report_month)[1]
    start_date = f"{report_year:04d}-{report_month:02d}-01"
    end_date = f"{report_year:04d}-{report_month:02d}-{last_day:02d}"
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT id, raw_text, ai_summary, created_at, is_favorite
        FROM notes
        WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY created_at DESC, id DESC
        """,
        (start_date, end_date),
    ).fetchall()
    conn.close()

    notes = format_notes(rows)
    active_dates = sorted({(note["created_at"] or "")[:10] for note in notes if note["created_at"]})
    tag_counts = Counter(tag for note in notes for tag in note["tags"])
    top_tags = tag_counts.most_common(5)
    learning_themes = [
        f"#{tag} を中心にした学習"
        for tag, _ in top_tags[:3]
    ]
    favorite_notes = [
        {
            "id": note["id"],
            "text": note["raw_text"],
            "created_at": note["created_at"],
            "tags": note["tags"],
        }
        for note in notes
        if note["is_favorite"]
    ][:5]
    continuous_days = calculate_continuous_days(active_dates)
    highlights = [
        {
            "id": note["id"],
            "text": note["raw_text"],
            "created_at": note["created_at"],
            "is_favorite": note["is_favorite"],
        }
        for note in sorted(notes, key=lambda item: (not item["is_favorite"], item["created_at"] or ""))[:3]
    ]
    top_topics = ", ".join(f"#{tag}" for tag, _ in tag_counts.most_common(3))
    if notes:
        ai_summary = (
            f"今月は{len(notes)}件の学習記録を、{len(active_dates)}日間にわたって残しました。"
            + (f" 特に{top_topics}への関心が高まりました。" if top_topics else " 継続的な振り返りができています。")
        )
        suggestions = [
            "最も多かったテーマを1つ選び、成果物としてまとめる",
            "学習した翌日に短い復習ノートを追加する",
            "お気に入りノートを見直し、次の具体的な行動を決める",
        ]
    else:
        ai_summary = "今月の学習記録はまだありません。最初の小さな気づきを残してみましょう。"
        suggestions = ["1日1件、学んだことや気づきを短く記録する"]

    return {
        "period": {"year": report_year, "month": report_month, "start": start_date, "end": end_date},
        "note_count": len(notes),
        "learning_days": len(active_dates),
        "continuous_days": continuous_days,
        "new_tag_count": len(tag_counts),
        "favorite_count": sum(1 for note in notes if note["is_favorite"]),
        "learning_themes": learning_themes,
        "favorite_notes": favorite_notes,
        "tag_analysis": [
            {"tag": tag, "count": count}
            for tag, count in top_tags
        ],
        "highlights": highlights,
        "ai_summary": ai_summary,
        "recommended_actions": suggestions,
        "calendar": {"active_dates": active_dates, "counts": dict(Counter((note["created_at"] or "")[:10] for note in notes))},
    }


@app.get("/api/report/weekly")
def get_weekly_report():
    today = datetime.now().date()
    start_date = today - timedelta(days=6)
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT raw_text, ai_summary, created_at
        FROM notes
        WHERE substr(created_at, 1, 10) BETWEEN ? AND ?
        ORDER BY created_at DESC, id DESC
        """,
        (start_date.isoformat(), today.isoformat()),
    ).fetchall()
    conn.close()

    notes = [
        {"raw_text": row[0], "ai_summary": row[1], "created_at": row[2]}
        for row in rows
    ]
    report = build_weekly_report(notes)
    return {
        "period": {"start": start_date.isoformat(), "end": today.isoformat()},
        "note_count": len(notes),
        **report,
    }


@app.get("/api/search")
def search_notes(q: str = "", tag: str = ""):
    keyword = q.strip()

    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    if keyword:
        search_word = f"%{keyword}%"

        cur.execute("""
            SELECT
                id,
                raw_text,
                ai_summary,
                created_at,
                is_favorite
            FROM notes
            WHERE raw_text LIKE ?
               OR ai_summary LIKE ?
            ORDER BY id DESC
        """, (search_word, search_word))
    else:
        cur.execute("""
            SELECT
                id,
                raw_text,
                ai_summary,
                created_at,
                is_favorite
            FROM notes
            ORDER BY id DESC
        """)

    rows = cur.fetchall()
    conn.close()

    return filter_notes_by_tag(format_notes(rows), tag)


@app.get("/api/timeline")
def get_timeline():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT id, raw_text, ai_summary, created_at, is_favorite
        FROM notes
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    groups = []
    for note in format_notes(rows):
        date = (note["created_at"] or "")[:10] or "日付なし"
        if not groups or groups[-1]["date"] != date:
            groups.append({
                "date": date,
                "label": "Today" if date == today else date,
                "notes": [],
            })
        groups[-1]["notes"].append(note)

    return groups


@app.get("/api/export/markdown")
def export_markdown():
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        """
        SELECT id, raw_text, ai_summary, created_at, is_favorite
        FROM notes
        ORDER BY created_at DESC, id DESC
        """
    ).fetchall()
    conn.close()

    content = build_markdown(format_notes(rows))
    filename = f"ai-growth-notes-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/report/monthly/export")
def export_monthly_report_markdown(year: int | None = None, month: int | None = None):
    report = get_monthly_report(year=year, month=month)
    content = build_monthly_report_markdown(report)
    filename = (
        f"ai-growth-monthly-report-"
        f"{report['period']['year']:04d}{report['period']['month']:02d}.md"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def calculate_continuous_days(active_dates: list[str]) -> int:
    if not active_dates:
        return 0

    date_set = {datetime.strptime(date, "%Y-%m-%d").date() for date in active_dates}
    cursor = max(date_set)
    days = 0
    while cursor in date_set:
        days += 1
        cursor -= timedelta(days=1)
    return days


def build_monthly_report_markdown(report: dict) -> str:
    period = report["period"]
    lines = [
        f"# AI Growth Notes Monthly Report {period['year']}年{period['month']}月",
        "",
        f"対象期間: {period['start']} - {period['end']}",
        "",
        "## 今月の総括",
        "",
        report.get("ai_summary") or "データがありません",
        "",
        "## 今月の学習テーマ",
        "",
        *markdown_list(report.get("learning_themes", [])),
        "",
        "## よく使われたタグ Top 5",
        "",
        *markdown_list([f"#{item['tag']}: {item['count']}件" for item in report.get("tag_analysis", [])]),
        "",
        "## お気に入りノート",
        "",
        *markdown_list([
            f"{note.get('created_at', '')} {note.get('text', '')}"
            for note in report.get("favorite_notes", [])
        ]),
        "",
        "## 継続日数",
        "",
        f"{report.get('continuous_days', 0)}日",
        "",
        "## 来月へのおすすめアクション",
        "",
        *markdown_list(report.get("recommended_actions", [])),
        "",
    ]
    return "\n".join(lines)


def markdown_list(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["- データがありません"]


def format_notes(rows):
    return [
        {
            "id": row[0],
            "raw_text": row[1],
            "ai_summary": normalize_tags_in_text(row[2]),
            "tags": extract_tags(row[2]),
            "created_at": row[3],
            "is_favorite": bool(row[4])
        }
        for row in rows
    ]


def filter_notes_by_tag(notes, tag):
    selected_tag = normalize_tag(tag)

    if not selected_tag:
        return notes

    return [
        note for note in notes
        if any(note_tag.casefold() == selected_tag.casefold() for note_tag in note["tags"])
    ]


app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.get("/ai-daily")
def ai_daily():
    """Serve the SPA with AI Daily selected by its client-side router."""
    return FileResponse("static/index.html")
