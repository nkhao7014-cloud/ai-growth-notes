import sqlite3
from collections import Counter
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from ai_client import analyze_note_with_tags, extract_tags
from services.export_service import build_markdown

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


init_db()


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
def list_notes(tag: str = ""):
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

    return filter_notes_by_tag(format_notes(rows), tag)


@app.get("/api/stats")
def get_stats():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM notes")
    total_notes = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM notes WHERE is_favorite = 1")
    favorite_notes = cur.fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute(
        "SELECT COUNT(*) FROM notes WHERE substr(created_at, 1, 10) = ?",
        (today,),
    )
    today_notes = cur.fetchone()[0]

    cur.execute("SELECT ai_summary FROM notes")
    summaries = cur.fetchall()
    conn.close()

    tag_counts = Counter(
        tag
        for (summary,) in summaries
        for tag in extract_tags(summary or "")
    )
    top_tags = sorted(
        tag_counts.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    )[:5]

    return {
        "total_notes": total_notes,
        "today_notes": today_notes,
        "favorite_notes": favorite_notes,
        "tag_count": len(tag_counts),
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in top_tags
        ],
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


def format_notes(rows):
    return [
        {
            "id": row[0],
            "raw_text": row[1],
            "ai_summary": row[2],
            "tags": extract_tags(row[2]),
            "created_at": row[3],
            "is_favorite": bool(row[4])
        }
        for row in rows
    ]


def filter_notes_by_tag(notes, tag):
    selected_tag = tag.strip().lstrip("#")

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
