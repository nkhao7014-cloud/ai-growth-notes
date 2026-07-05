import unittest
from unittest.mock import patch

from services.weekly_report_service import build_weekly_report


class WeeklyReportServiceTests(unittest.TestCase):
    @patch.dict("os.environ", {"AI_PROVIDER": "mock"}, clear=False)
    def test_mock_report_contains_required_sections_and_frequent_tags(self):
        notes = [
            {"raw_text": "FastAPIを学習", "ai_summary": "整理 #AI #FastAPI", "created_at": "2026-07-05 10:00:00"},
            {"raw_text": "プロンプトを練習", "ai_summary": "整理 #AI #Prompt", "created_at": "2026-07-04 10:00:00"},
        ]

        report = build_weekly_report(notes)

        self.assertEqual(report["provider"], "mock")
        self.assertEqual(report["frequent_tags"][0], {"tag": "AI", "count": 2})
        self.assertTrue(report["learned_contents"])
        self.assertTrue(report["ai_summary"])
        self.assertTrue(report["next_week_suggestions"])

    def test_empty_week_returns_useful_mock_report_without_ai_call(self):
        report = build_weekly_report([])

        self.assertEqual(report["learned_contents"], [])
        self.assertEqual(report["frequent_tags"], [])
        self.assertEqual(report["provider"], "mock")


if __name__ == "__main__":
    unittest.main()
