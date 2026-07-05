import unittest

from ai_client import extract_tags, normalize_tag, normalize_tags_in_text


class TagNormalizationTests(unittest.TestCase):
    def test_requested_chinese_tags_are_normalized_to_japanese(self):
        expected = {
            "学习": "学習",
            "成长": "成長",
            "AI学习": "AI学習",
            "学习记录": "学習記録",
            "成长记录": "成長記録",
        }
        for source, normalized in expected.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_tag(source), normalized)

    def test_extract_tags_deduplicates_after_normalization(self):
        self.assertEqual(extract_tags("#学习 #学習 #AI学习"), ["学習", "AI学習"])

    def test_only_hashtags_are_replaced_in_summary_text(self):
        self.assertEqual(
            normalize_tags_in_text("学习メモ #学习 #成长记录"),
            "学习メモ #学習 #成長記録",
        )


if __name__ == "__main__":
    unittest.main()
