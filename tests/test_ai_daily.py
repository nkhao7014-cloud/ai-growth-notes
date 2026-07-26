import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
import routers.ai_daily as routes
from services.ai_daily_feed_service import clean_text, normalize_url, parse_feed
from services.ai_daily_service import get_daily, init_ai_daily_db, save_items


RSS = b'''<?xml version="1.0"?><rss><channel><item><title>AI &amp; API update</title>
<link>https://example.com/posts/update/?utm_source=rss</link><guid>entry-1</guid>
<pubDate>Sun, 26 Jul 2026 10:00:00 GMT</pubDate><description><![CDATA[<p>Short <b>official</b> summary.</p>]]></description>
</item></channel></rss>'''


class AiDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "notes.db"
        connection = sqlite3.connect(self.db)
        connection.execute("""CREATE TABLE notes (id INTEGER PRIMARY KEY AUTOINCREMENT, raw_text TEXT,
                           ai_summary TEXT, created_at TEXT, is_favorite INTEGER NOT NULL DEFAULT 0)""")
        connection.commit()
        connection.close()
        init_ai_daily_db(self.db)
        self.db_patch = patch.object(routes, "DB", str(self.db))
        self.db_patch.start()
        routes._last_refresh_failed = False
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.db_patch.stop()
        self.temp.cleanup()

    def sample(self):
        return parse_feed(RSS, {"name": "Official", "url": "https://example.com/feed.xml", "default_category": "Developer Tools"})[0]

    def test_ai_daily_route_serves_application_shell(self):
        response = self.client.get("/ai-daily")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="ai-dailyView"', response.text)

    def test_fragment_has_loading_empty_error_and_complete_sections(self):
        content = (Path(__file__).parents[1] / "static" / "ai-daily-content.html").read_text(encoding="utf-8")
        for value in ("Today's Highlights", "Reading List", "aiDailyLoading", "aiDailyEmpty", "aiDailyError", "aiLearning", "aiPractice"):
            self.assertIn(value, content)

    def test_frontend_uses_api_and_text_content_for_external_values(self):
        script = (Path(__file__).parents[1] / "static" / "ai-daily.js").read_text(encoding="utf-8")
        self.assertIn('request("/api/ai-daily")', script)
        self.assertIn("textContent", script)
        self.assertIn("if(refreshing)return", script)
        self.assertNotIn("innerHTML=item", script)

    def test_url_validation_and_normalization(self):
        self.assertEqual(normalize_url("HTTPS://Example.COM:443/a/?utm_source=x&b=2#part"), "https://example.com/a?b=2")
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("file:///tmp/a"))

    def test_feed_normalization_strips_html_and_limits_text(self):
        item = self.sample()
        self.assertEqual(item["title"], "AI & API update")
        self.assertEqual(item["summary"], "Short official summary.")
        self.assertEqual(item["normalized_url"], "https://example.com/posts/update")
        self.assertEqual(clean_text("x" * 20, 10), "xxxxxxxxx…")

    def test_duplicate_save_updates_without_resetting_user_state(self):
        item = self.sample()
        save_items(self.db, [item])
        connection = sqlite3.connect(self.db)
        connection.execute("UPDATE ai_daily_items SET is_read=1, is_favorite=1")
        connection.commit()
        connection.close()
        item["summary"] = "Changed"
        result = save_items(self.db, [item])
        self.assertEqual(result["updated_items"], 1)
        connection = sqlite3.connect(self.db)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM ai_daily_items").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT summary,is_read,is_favorite FROM ai_daily_items").fetchone(), ("Changed", 1, 1))
        connection.close()

    def test_get_api_returns_saved_data_and_rule_fallback(self):
        save_items(self.db, [self.sample()])
        response = self.client.get("/api/ai-daily?date=2026-07-26")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["highlights"]), 1)
        self.assertTrue(body["learning"]["topic"])
        self.assertTrue(body["practice"]["description"])

    def test_read_and_favorite_toggle(self):
        save_items(self.db, [self.sample()])
        item_id = get_daily(self.db, "2026-07-26")["reading_list"][0]["id"]
        self.assertTrue(self.client.patch(f"/api/ai-daily/items/{item_id}/read", json={"value": True}).json()["is_read"])
        self.assertTrue(self.client.patch(f"/api/ai-daily/items/{item_id}/favorite", json={"value": True}).json()["is_favorite"])

    def test_save_note_is_idempotent_and_uses_existing_notes_table(self):
        save_items(self.db, [self.sample()])
        item_id = get_daily(self.db, "2026-07-26")["reading_list"][0]["id"]
        first = self.client.post(f"/api/ai-daily/items/{item_id}/save-note")
        second = self.client.post(f"/api/ai-daily/items/{item_id}/save-note")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already_saved"])
        connection = sqlite3.connect(self.db)
        text = connection.execute("SELECT raw_text FROM notes").fetchone()[0]
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0], 1)
        connection.close()
        self.assertIn("## 自分の気づき", text)
        self.assertIn("https://example.com/posts/update", text)

    @patch("services.ai_daily_service.fetch_feed")
    def test_refresh_continues_when_one_feed_fails(self, mocked):
        mocked.side_effect = [[self.sample()], OSError("offline"), [], [], []]
        response = self.client.post("/api/ai-daily/refresh")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["successful_feeds"], 4)
        self.assertEqual(response.json()["failed_feeds"], 1)
        self.assertEqual(response.json()["new_items"], 1)

    @patch("services.ai_daily_service.fetch_feed", side_effect=OSError("offline"))
    def test_total_feed_failure_keeps_saved_data_available(self, _mocked):
        save_items(self.db, [self.sample()])
        self.assertEqual(self.client.post("/api/ai-daily/refresh").status_code, 503)
        body = self.client.get("/api/ai-daily?date=2026-07-26").json()
        self.assertEqual(len(body["reading_list"]), 1)
        self.assertTrue(body["using_saved_data"])
        self.assertEqual(body["fetch_status"], "stale")


if __name__ == "__main__":
    unittest.main()
