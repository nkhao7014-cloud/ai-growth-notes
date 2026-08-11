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
from services.ai_daily_service import get_daily, item_row, save_items
from services.ai_daily_service import backfill_japanese_content
from services.ai_daily_translation_service import translate_ai_daily_item


RSS = b'''<?xml version="1.0"?><rss><channel><item><title>AI &amp; API update</title>
<link>https://example.com/posts/update/?utm_source=rss</link><guid>entry-1</guid>
<pubDate>Sun, 26 Jul 2026 10:00:00 GMT</pubDate><description><![CDATA[<p>Short <b>official</b> summary.</p>]]></description>
</item></channel></rss>'''


class FakeResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, existing=None):
        self.existing = existing
        self.calls = []

    def execute(self, sql, values=()):
        self.calls.append((sql, values))
        if sql.startswith("SELECT id,title,summary,why_it_matters"):
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

    @patch("services.ai_daily_service.translate_ai_daily_item")
    def test_new_item_saves_japanese_fields_in_one_translation_call(self, translate):
        translate.return_value = {
            "title_ja": "AIとAPIの最新情報",
            "summary_ja": "公式の短い要約です。",
            "why_it_matters_ja": "開発者にとって重要です。",
            "key_points_ja": ["変更点", "開発者への影響"],
        }
        item = self.sample()
        item["why_it_matters"] = "Important to developers."

        result, calls = self.save_with_connection(item)

        self.assertEqual(translate.call_count, 1)
        self.assertEqual(result["translated_items"], 1)
        sql, values = calls[-1]
        self.assertIn("title_ja,summary_ja,why_it_matters_ja,key_points_ja,translated_at", sql)
        self.assertEqual(values[10:13], (
            "AIとAPIの最新情報", "公式の短い要約です。", "開発者にとって重要です。",
        ))

    @patch("services.ai_daily_service.translate_ai_daily_item")
    def test_unchanged_translated_item_skips_ai_call(self, translate):
        item = self.sample()
        item["why_it_matters"] = "Important."
        existing = {
            "id": 42, "title": item["title"], "summary": item["summary"],
            "why_it_matters": item["why_it_matters"], "title_ja": "日本語タイトル",
            "summary_ja": "日本語要約", "why_it_matters_ja": "日本語の重要性",
            "key_points_ja": ["ポイント"],
            "translated_at": "2026-08-01T00:00:00+00:00",
        }

        result, calls = self.save_with_connection(item, existing)

        translate.assert_not_called()
        self.assertEqual(result["translated_items"], 0)
        self.assertEqual(calls[-1][1][10:13], ("日本語タイトル", "日本語要約", "日本語の重要性"))

    @patch("services.ai_daily_translation_service.generate_text", side_effect=RuntimeError("AI failed"))
    def test_translation_failure_falls_back_to_original(self, _generate):
        item = {"title": "English title", "summary": "English summary",
                "why_it_matters": "English reason"}
        self.assertEqual(translate_ai_daily_item(item), {
            "title_ja": "English title", "summary_ja": "English summary",
            "why_it_matters_ja": "English reason",
            "key_points_ja": ["English summary"],
        })

    @patch("services.ai_daily_translation_service.generate_text", side_effect=RuntimeError("AI failed"))
    def test_translation_failure_does_not_fail_item_save(self, _generate):
        item = self.sample()
        item["why_it_matters"] = "Original reason"
        result, calls = self.save_with_connection(item)
        self.assertEqual(result["new_items"], 1)
        self.assertEqual(calls[-1][1][10:13], (
            item["title"], item["summary"], item["why_it_matters"],
        ))

    @patch("services.ai_daily_translation_service.generate_text", return_value="not json")
    def test_invalid_translation_json_falls_back_without_raising(self, _generate):
        item = {"title": "Title", "summary": "Summary", "why_it_matters": "Why"}
        self.assertEqual(translate_ai_daily_item(item)["title_ja"], "Title")

    @patch("services.ai_daily_translation_service.generate_text")
    def test_translation_parses_json_and_uses_one_ai_call(self, generate):
        generate.return_value = '{"title_ja":"題名","summary_ja":"要約","why_it_matters_ja":"重要","key_points_ja":["点1","点2"]}'
        result = translate_ai_daily_item({
            "title": "Title", "summary": "Summary", "why_it_matters": "Why",
        })
        self.assertEqual(result["summary_ja"], "要約")
        self.assertEqual(generate.call_count, 1)

    @patch("services.ai_daily_translation_service.generate_text")
    def test_japanese_article_skips_ai_translation(self, generate):
        result = translate_ai_daily_item({
            "title": "新しいAIモデルを発表",
            "summary": "開発者向けの新機能が公開されました。",
            "why_it_matters": "AI開発に影響します。",
        })
        generate.assert_not_called()
        self.assertEqual(result["title_ja"], "新しいAIモデルを発表")
        self.assertTrue(result["key_points_ja"])

    def test_api_row_keeps_original_and_japanese_fields(self):
        row = {
            "id": 1, "title": "Title", "summary": "Summary", "why_it_matters": "Why",
            "title_ja": "題名", "summary_ja": "要約", "why_it_matters_ja": "重要",
            "key_points_ja": '["点1"]',
            "translated_at": None, "tags": "[]",
        }
        result = item_row(row)
        self.assertEqual(result["title"], "Title")
        self.assertEqual(result["title_ja"], "題名")
        self.assertEqual(result["summary_ja"], "要約")
        self.assertEqual(result["why_it_matters_ja"], "重要")
        self.assertEqual(result["key_points_ja"], ["点1"])

    @patch("services.ai_daily_service.ensure_edition", return_value={"learning": {}, "practice": {}})
    def test_get_daily_returns_japanese_fields(self, _edition):
        row = {
            "id": 1, "title": "Title", "summary": "Summary", "why_it_matters": "Why",
            "title_ja": "題名", "summary_ja": "要約", "why_it_matters_ja": "重要",
            "key_points_ja": ["点1"],
            "translated_at": None, "tags": [],
            "published_at": None, "fetched_at": None, "created_at": None, "updated_at": None,
        }
        class DailyConnection:
            def execute(self, sql, values=()):
                if sql.startswith("SELECT * FROM ai_daily_items"):
                    return FakeResult(rows=[row])
                return FakeResult({"value": None})
        @contextmanager
        def fake_transaction():
            yield DailyConnection()
        with patch("services.ai_daily_service.transaction", fake_transaction):
            result = get_daily("2026-08-11")
        self.assertEqual(result["reading_list"][0]["title_ja"], "題名")
        self.assertEqual(result["highlights"][0]["summary_ja"], "要約")
        self.assertEqual(result["highlights"][0]["key_points_ja"], ["点1"])

    def test_frontend_prefers_japanese_and_preserves_source_link(self):
        script = (Path(__file__).parents[1] / "static" / "ai-daily.js").read_text(encoding="utf-8")
        self.assertIn("item.title_ja||item.title", script)
        self.assertIn("item.summary_ja||item.summary", script)
        self.assertIn("item.why_it_matters_ja||item.why_it_matters", script)
        self.assertIn("item.key_points_ja", script)
        self.assertIn("a.href=item.source_url", script)

    def test_schema_has_non_destructive_translation_migration(self):
        schema = (Path(__file__).parents[1] / "database.py").read_text(encoding="utf-8")
        for column in ("title_ja TEXT", "summary_ja TEXT", "why_it_matters_ja TEXT", "key_points_ja JSONB",
                       "translated_at TIMESTAMPTZ"):
            self.assertIn(f"ADD COLUMN IF NOT EXISTS {column}", schema)

    @patch("services.ai_daily_service.translation_provider_status",
           return_value={"available": True})
    @patch("services.ai_daily_service.translate_ai_daily_item")
    def test_existing_article_backfill_is_bounded_and_repeatable(self, translate, _status):
        translate.return_value = {
            "title_ja": "題名", "summary_ja": "要約",
            "why_it_matters_ja": "重要", "key_points_ja": ["点1"],
        }
        rows = [{"id": 7, "title": "Title", "summary": "Summary", "why_it_matters": "Why"}]
        calls = []
        class BackfillConnection:
            def __init__(self, select=False): self.select = select
            def execute(self, sql, values=()):
                calls.append((sql, values))
                return FakeResult(rows=rows if sql.startswith("SELECT id,title") else [])
        transactions = iter([BackfillConnection(True), BackfillConnection()])
        @contextmanager
        def fake_transaction():
            yield next(transactions)
        with patch("services.ai_daily_service.transaction", fake_transaction):
            result = backfill_japanese_content(limit=1)
        self.assertEqual(result["processed_items"], 1)
        self.assertEqual(translate.call_count, 1)
        self.assertIn("key_points_ja=%s::jsonb", calls[-1][0])
        self.assertNotIn("is_read", calls[-1][0])
        self.assertNotIn("is_favorite", calls[-1][0])
        self.assertNotIn("saved_note_id", calls[-1][0])
        self.assertNotIn("source_url", calls[-1][0])

    def test_backfill_dry_run_does_not_call_ai_or_update(self):
        rows = [{"id": 7, "title": "Title", "summary": "Summary", "why_it_matters": "Why"}]
        calls = []
        class Connection:
            def execute(self, sql, values=()):
                calls.append(sql)
                return FakeResult(rows=rows)
        @contextmanager
        def fake_transaction():
            yield Connection()
        with patch("services.ai_daily_service.transaction", fake_transaction), \
             patch("services.ai_daily_service.translate_ai_daily_item") as translate:
            result = backfill_japanese_content(limit=20, dry_run=True)
        translate.assert_not_called()
        self.assertEqual(result["candidate_items"], 1)
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(calls), 1)

    @patch.dict("os.environ", {"AI_PROVIDER": "mock", "AI_MODEL": "test-model",
                               "GEMINI_API_KEY": "must-not-be-returned"}, clear=False)
    def test_translation_status_is_safe_and_marks_mock_unavailable(self):
        from services.ai_daily_translation_service import translation_provider_status
        result = translation_provider_status()
        self.assertEqual(result["provider"], "mock")
        self.assertEqual(result["model"], "test-model")
        self.assertFalse(result["available"])
        self.assertNotIn("must-not-be-returned", str(result))

    @patch("services.ai_daily_translation_service.generate_text")
    def test_github_copilot_java_article_reaches_api_as_japanese(self, generate):
        original_title = "Using the GitHub Copilot SDK for Java"
        original_summary = "Enterprise Java developers have a new superpower through the Copilot SDK."
        generate.return_value = """{
          "title_ja": "Java向けGitHub Copilot SDKの活用方法",
          "summary_ja": "GitHubは、Java開発者がGitHub CopilotをJavaコードから活用できるSDKについて紹介しました。アノテーションやVirtual Threadsなど、Javaらしい実装方法からCopilotを利用できます。",
          "why_it_matters_ja": "Javaの既存システムにもAI支援を統合しやすくなります。",
          "key_points_ja": ["Java向けSDK", "アノテーション対応", "Virtual Threadsの活用"]
        }"""
        item = self.sample()
        item.update(title=original_title, summary=original_summary,
                    why_it_matters="The SDK helps enterprise Java teams.",
                    source_url="https://github.blog/example/copilot-sdk-java")

        result, calls = self.save_with_connection(item)

        self.assertEqual(result["new_items"], 1)
        values = calls[-1][1]
        api_item = item_row({
            "id": 99, "title": values[2], "source_name": values[3],
            "source_url": values[4], "normalized_url": values[5],
            "published_at": values[6], "category": values[7], "summary": values[8],
            "why_it_matters": values[9], "title_ja": values[10],
            "summary_ja": values[11], "why_it_matters_ja": values[12],
            "key_points_ja": values[13], "translated_at": values[14],
            "tags": values[15], "fetched_at": values[16],
            "updated_at": values[17], "created_at": values[18],
        })
        self.assertEqual(api_item["title"], original_title)
        self.assertEqual(api_item["title_ja"], "Java向けGitHub Copilot SDKの活用方法")
        self.assertTrue(api_item["summary_ja"].startswith("GitHubは、Java開発者"))
        self.assertEqual(api_item["source_url"], item["source_url"])
        script = (Path(__file__).parents[1] / "static" / "ai-daily.js").read_text(encoding="utf-8")
        self.assertIn("return item.title_ja||item.title", script)
        self.assertIn("return item.summary_ja||item.summary", script)


if __name__ == "__main__":
    unittest.main()
