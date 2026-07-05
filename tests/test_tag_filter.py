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
                created_at TEXT,
                is_favorite INTEGER NOT NULL DEFAULT 0
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
    def test_timeline_groups_notes_by_date_and_labels_today(self, mock_datetime):
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 5, 15, 0)
        connection = sqlite3.connect(self.database_path)
        connection.execute(
            "INSERT INTO notes (raw_text, ai_summary, created_at) VALUES (?, ?, ?)",
            ("Yesterday note", "Summary", "2026-07-04 18:00:00"),
        )
        connection.commit()
        connection.close()

        timeline = main.get_timeline()

        self.assertEqual([group["date"] for group in timeline], ["2026-07-05", "2026-07-04"])
        self.assertEqual(timeline[0]["label"], "Today")
        self.assertEqual(len(timeline[0]["notes"]), 3)
        self.assertEqual(timeline[1]["label"], "2026-07-04")

    @patch("main.datetime")
    def test_stats_returns_note_and_tag_counts(self, mock_datetime):
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 5, 15, 0)

        stats = main.get_stats()

        self.assertEqual(stats["total_notes"], 3)
        self.assertEqual(stats["today_notes"], 3)
        self.assertEqual(stats["favorite_notes"], 0)
        self.assertEqual(stats["tag_count"], 4)
        self.assertEqual(stats["top_tags"][0], {"tag": "AI", "count": 2})
        self.assertEqual(len(stats["top_tags"]), 4)

    @patch("main.build_weekly_report")
    @patch("main.datetime")
    def test_weekly_report_uses_only_today_and_previous_six_days(
        self, mock_datetime, build_report
    ):
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 5, 15, 0)
        connection = sqlite3.connect(self.database_path)
        connection.executemany(
            "INSERT INTO notes (raw_text, ai_summary, created_at) VALUES (?, ?, ?)",
            [
                ("Within week", "Summary #Weekly", "2026-06-29 09:00:00"),
                ("Too old", "Summary #Old", "2026-06-28 23:59:59"),
                ("Future", "Summary #Future", "2026-07-06 00:00:00"),
            ],
        )
        connection.commit()
        connection.close()
        build_report.return_value = {
            "learned_contents": [], "frequent_tags": [], "ai_summary": "Summary",
            "next_week_suggestions": [], "provider": "mock",
        }

        report = main.get_weekly_report()

        self.assertEqual(report["period"], {"start": "2026-06-29", "end": "2026-07-05"})
        self.assertEqual(report["note_count"], 4)
        passed_notes = build_report.call_args.args[0]
        self.assertIn("Within week", [note["raw_text"] for note in passed_notes])
        self.assertNotIn("Too old", [note["raw_text"] for note in passed_notes])
        self.assertNotIn("Future", [note["raw_text"] for note in passed_notes])

    @patch("main.analyze_note_with_tags")
    def test_update_note_reanalyzes_and_saves_text(self, analyze):
        analyze.return_value = {"summary": "Updated #New", "tags": ["New"]}

        result = main.update_note(1, main.NoteInput(text="Updated text"))

        self.assertEqual(result["summary"], "Updated #New")
        analyze.assert_called_once_with("Updated text")
        connection = sqlite3.connect(self.database_path)
        row = connection.execute(
            "SELECT raw_text, ai_summary FROM notes WHERE id = 1"
        ).fetchone()
        connection.close()
        self.assertEqual(row, ("Updated text", "Updated #New"))

    def test_favorite_toggle_updates_note_and_stats(self):
        result = main.set_favorite(1, main.FavoriteInput(is_favorite=True))

        self.assertTrue(result["is_favorite"])
        self.assertTrue(main.list_notes()[2]["is_favorite"])
        self.assertEqual(main.get_stats()["favorite_notes"], 1)

    def test_delete_note_removes_it(self):
        result = main.delete_note(2)

        self.assertTrue(result["deleted"])
        self.assertEqual(len(main.list_notes()), 2)

    @patch("main.datetime")
    def test_markdown_export_is_downloadable_and_sorted_by_created_at(self, mock_datetime):
        mock_datetime.now.return_value = __import__("datetime").datetime(2026, 7, 5, 15, 30)
        main.set_favorite(1, main.FavoriteInput(is_favorite=True))

        response = main.export_markdown()
        markdown = response.body.decode("utf-8")

        self.assertEqual(response.media_type, "text/markdown")
        self.assertIn("attachment; filename=", response.headers["content-disposition"])
        self.assertLess(markdown.index("## AI prompt practice"), markdown.index("## Practiced Python"))
        self.assertLess(markdown.index("## Practiced Python"), markdown.index("## Learned FastAPI"))
        self.assertIn("- 作成日時: 2026-07-05 10:00:00", markdown)
        self.assertIn("- タグ: #AI #FastAPI", markdown)
        self.assertIn("- お気に入り: はい", markdown)
        self.assertIn("### 原文\n\nLearned FastAPI", markdown)
        self.assertIn("### AI整理結果\n\nSummary #AI #FastAPI", markdown)


if __name__ == "__main__":
    unittest.main()
