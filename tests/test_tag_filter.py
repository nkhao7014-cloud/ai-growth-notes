import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class TagFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "notes.db"
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            """CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT,
                ai_summary TEXT,
                created_at TEXT
            )"""
        )
        connection.executemany(
            "INSERT INTO notes (raw_text, ai_summary, created_at) VALUES (?, ?, ?)",
            [
                ("Learned FastAPI", "Summary #AI #FastAPI", "2026-07-05 10:00:00"),
                ("Practiced Python", "Summary #Python", "2026-07-05 11:00:00"),
                ("AI prompt practice", "Summary #AI #Prompt", "2026-07-05 12:00:00"),
            ],
        )
        connection.commit()
        connection.close()
        self.database_patch = patch.object(main, "DB", str(self.database_path))
        self.database_patch.start()

    def tearDown(self):
        self.database_patch.stop()
        self.temporary_directory.cleanup()

    def test_list_notes_filters_by_exact_tag_case_insensitively(self):
        notes = main.list_notes(tag="#ai")

        self.assertEqual(
            [note["raw_text"] for note in notes],
            ["AI prompt practice", "Learned FastAPI"],
        )

    def test_search_and_tag_filter_work_together(self):
        notes = main.search_notes(q="FastAPI", tag="AI")

        self.assertEqual([note["raw_text"] for note in notes], ["Learned FastAPI"])

    def test_empty_tag_preserves_existing_list_behavior(self):
        self.assertEqual(len(main.list_notes(tag="")), 3)

    @patch("main.datetime")
    def test_stats_returns_note_and_tag_counts(self, mock_datetime):
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 5, 15, 0)

        stats = main.get_stats()

        self.assertEqual(stats["total_notes"], 3)
        self.assertEqual(stats["today_notes"], 3)
        self.assertEqual(stats["tag_count"], 4)
        self.assertEqual(stats["top_tags"][0], {"tag": "AI", "count": 2})
        self.assertEqual(len(stats["top_tags"]), 4)


if __name__ == "__main__":
    unittest.main()
