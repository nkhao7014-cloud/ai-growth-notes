import json
import os
from collections import Counter

from google import genai

from ai_client import AI_MODEL, extract_tags


def build_weekly_report(notes: list[dict]) -> dict:
    tag_counts = Counter(
        tag for note in notes for tag in extract_tags(note.get("ai_summary") or "")
    )
    frequent_tags = [
        {"tag": tag, "count": count}
        for tag, count in sorted(
            tag_counts.items(), key=lambda item: (-item[1], item[0].casefold())
        )[:5]
    ]
    if not notes:
        return {
            "learned_contents": [],
            "frequent_tags": [],
            "ai_summary": "今週の学習記録はまだありません。小さな気づきから記録してみましょう。",
            "next_week_suggestions": ["学んだことを1日1件記録してみる"],
            "provider": "mock",
        }

    prompt = _build_prompt(notes, frequent_tags)
    if os.getenv("AI_PROVIDER", "mock").lower() == "gemini" and os.getenv("GEMINI_API_KEY"):
        try:
            result = _generate_by_gemini(prompt)
            result["provider"] = "gemini"
            result["frequent_tags"] = frequent_tags
            return result
        except Exception as error:
            print("Weekly Report Gemini Error:", error)

    result = _generate_by_mock(notes)
    result["provider"] = "mock"
    result["frequent_tags"] = frequent_tags
    return result


def _build_prompt(notes: list[dict], frequent_tags: list[dict]) -> str:
    note_text = "\n\n".join(
        f"- {note['created_at']}\n  原文: {note['raw_text']}\n  AI整理: {note['ai_summary']}"
        for note in notes
    )
    tags = ", ".join(f"#{item['tag']}({item['count']})" for item in frequent_tags) or "なし"
    return f"""以下は直近1週間の学習記録です。日本語で週次レポートを作成してください。
学習記録:
{note_text}

頻出タグ: {tags}

次のJSONだけを出力してください。Markdownのコードフェンスは不要です。
{{
  "learned_contents": ["今週学習した内容（簡潔な箇条書き）"],
  "ai_summary": "学習の傾向、進捗、つながりを踏まえた総括",
  "next_week_suggestions": ["具体的で実行可能な来週の学習提案"]
}}
"""


def _generate_by_gemini(prompt: str) -> dict:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    response = client.models.generate_content(model=AI_MODEL, contents=prompt)
    text = (response.text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return _validate_result(json.loads(text))


def _validate_result(result: dict) -> dict:
    learned = result.get("learned_contents")
    suggestions = result.get("next_week_suggestions")
    summary = result.get("ai_summary")
    if not isinstance(learned, list) or not isinstance(suggestions, list) or not isinstance(summary, str):
        raise ValueError("Gemini returned an invalid weekly report")
    return {
        "learned_contents": [str(item) for item in learned],
        "ai_summary": summary,
        "next_week_suggestions": [str(item) for item in suggestions],
    }


def _generate_by_mock(notes: list[dict]) -> dict:
    learned = []
    for note in notes[:5]:
        text = (note.get("raw_text") or "").strip().replace("\n", " ")
        if text:
            learned.append(text if len(text) <= 100 else text[:97] + "...")
    return {
        "learned_contents": learned,
        "ai_summary": f"今週は{len(notes)}件の学習記録を残しました。記録を振り返り、理解した内容を次の実践につなげていきましょう。",
        "next_week_suggestions": [
            "頻出テーマを1つ選び、小さな成果物を作って理解を確認する",
            "学習後に要点と疑問点を記録し、週末に振り返る",
        ],
    }
