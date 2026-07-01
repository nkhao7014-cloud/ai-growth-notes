import sqlite3
from datetime import datetime

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from ai_client import analyze_note_with_tags

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

    # AI 自动整理
    result = analyze_note_with_tags(note.text)

    ai_text = result["summary"]
    tags = result["tags"]

    # 保存数据库
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
def list_notes():

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

    notes = []

    for row in rows:

        tags = []

        try:
            from ai_client import extract_tags
            tags = extract_tags(row[2])
        except Exception:
            pass

        notes.append(
            {
                "id": row[0],
                "raw_text": row[1],
                "ai_summary": row[2],
                "tags": tags,
                "created_at": row[3]
            }
        )

    return notes


app.mount(
    "/static",
    StaticFiles(directory="static"),
    name="static"
)


@app.get("/")
def home():
    return FileResponse("static/index.html")