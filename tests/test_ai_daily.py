import hashlib
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from services.ai_daily_feed_service import (
    clean_text,
    normalize_url,
    normalized_url_or_fallback,
    parse_feed,
)
from services.ai_daily_service import save_items


RSS = b'''<?xml version="1.0"?><rss><channel><item><title>AI &amp; API update</title>
<link>https://example.com/posts/update/?utm_source=rss</link><guid>entry-1</guid>
<pubDate>Sun, 26 Jul 2026 10:00:00 GMT</pubDate><description><![CDATA[<p>Short <b>official</b> summary.</p>]]></description>
</item></channel></rss>'''


class FakeResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    def execute(self, sql, values=()):
        self.calls.append((sql, values))
        if sql.startswith("SELECT id FROM ai_daily_items"):
            return FakeResult(self.existing)
        return FakeResult()


class AiDailyTests(unittest.TestCase):
    def sample(self):
        return parse_feed(
            RSS,
            {"name": "Official", "url": "https://example.com/feed.xml", "default_category": "Developer Tools"},
        )[0]

    def save_with_connection(self, item, existing=None):
        connection = FakeConnection(existing)

        @contextmanager
        def fake_transaction():
            yield connection

        with patch("services.ai_daily_service.transaction", fake_transaction):
            result = save_items([item])
        return result, connection.calls

    def test_url_validation_and_normalization(self):
        self.assertEqual(
            normalize_url("HTTPS://Example.COM:443/a/?utm_source=x&b=2#part"),
            "https://example.com/a?b=2",
        )
        self.assertIsNone(normalize_url("javascript:alert(1)"))
        self.assertIsNone(normalize_url("file:///tmp/a"))

    def test_invalid_or_empty_url_has_stable_non_null_fallback(self):
        expected = "urn:ai-daily:fallback:" + hashlib.sha256(b"dedup-key").hexdigest()
        self.assertEqual(normalized_url_or_fallback("", "dedup-key"), expected)
        self.assertEqual(normalized_url_or_fallback("javascript:alert(1)", "dedup-key"), expected)

    def test_feed_normalization_strips_html_and_tracking(self):
        item = self.sample()
        self.assertEqual(item["title"], "AI & API update")
        self.assertEqual(item["summary"], "Short official summary.")
        self.assertEqual(item["normalized_url"], "https://example.com/posts/update")
        self.assertEqual(len(clean_text("x" * 20, 10)), 10)

    def test_insert_saves_normalized_url_and_matches_placeholder_count(self):
        item = self.sample()
        item["source_url"] = "HTTPS://Example.COM:443/posts/update/?utm_source=rss#part"
        result, calls = self.save_with_connection(item)
        sql, values = calls[-1]
        self.assertEqual(result["new_items"], 1)
        self.assertIn("source_url,normalized_url,published_at", sql)
        self.assertEqual(values[5], "https://example.com/posts/update")
        self.assertEqual(sql.count("%s"), len(values))

    def test_update_saves_fallback_url_without_resetting_user_state(self):
        item = self.sample()
        item["source_url"] = "not a URL"
        result, calls = self.save_with_connection(item, {"id": 42})
        sql, values = calls[-1]
        expected = normalized_url_or_fallback(item["source_url"], item["fallback_key"])
        self.assertEqual(result["updated_items"], 1)
        self.assertIn("normalized_url=%s", sql)
        self.assertNotIn("is_read", sql)
        self.assertNotIn("is_favorite", sql)
        self.assertEqual(values[5], expected)
        self.assertEqual(values[-1], 42)
        self.assertEqual(sql.count("%s"), len(values))

    def test_frontend_uses_api_and_safe_text_assignment(self):
        script = (Path(__file__).parents[1] / "static" / "ai-daily.js").read_text(encoding="utf-8")
        self.assertIn('request("/api/ai-daily")', script)
        self.assertIn("textContent", script)


if __name__ == "__main__":
    unittest.main()
