import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import main


class AiDailyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.root = Path(__file__).resolve().parents[1]

    def test_ai_daily_route_serves_the_application_shell(self):
        response = self.client.get("/ai-daily")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="ai-dailyView"', response.text)
        self.assertIn('/static/ai-daily.js', response.text)

    def test_ai_daily_fragment_contains_all_sprint_one_sections(self):
        content = (self.root / "static" / "ai-daily-content.html").read_text(encoding="utf-8")

        for heading in (
            "AI Daily",
            "Today's Highlights",
            "Today's Learning",
            "Today's Practice",
            "Reading List",
        ):
            self.assertIn(heading, content)
        self.assertEqual(content.count('class="ai-news-card"'), 5)

    def test_navigation_and_dashboard_entry_are_injected(self):
        script = (self.root / "static" / "ai-daily.js").read_text(encoding="utf-8")

        self.assertIn('dataset.view = "ai-daily"', script)
        self.assertIn("Open AI Daily", script)
        self.assertIn('location.pathname === "/ai-daily"', script)


if __name__ == "__main__":
    unittest.main()
