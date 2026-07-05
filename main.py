import sqlite3
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from ai_client import analyze_note_with_tags, extract_tags

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

    conn.commit()
    conn.close()


init_db()


class NoteInput(BaseModel):
    text: str


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


@app.get("/api/notes")
def list_notes(tag: str = ""):
    conn = sqlite3.connect(DB)
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            raw_text,
            ai_summary,
            created_at
        FROM notes
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    return filter_notes_by_tag(format_notes(rows), tag)


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
                created_at
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
                created_at
            FROM notes
            ORDER BY id DESC
        """)

    rows = cur.fetchall()
    conn.close()

    return filter_notes_by_tag(format_notes(rows), tag)


def format_notes(rows):
    return [
        {
            "id": row[0],
            "raw_text": row[1],
            "ai_summary": row[2],
            "tags": extract_tags(row[2]),
            "created_at": row[3]
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
