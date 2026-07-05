import os
import re
from dotenv import load_dotenv
from google import genai

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")


# ==========================
# 外部向け共通インターフェース
# ==========================

def analyze_note(content: str) -> str:
    """
    AIで整理したテキストを返す
    """
    prompt = build_note_prompt(content)
    return generate_text(prompt)


def analyze_note_with_tags(content: str) -> dict:
    """
    構造化された結果を返す
    """
    ai_text = analyze_note(content)

    return {
        "summary": ai_text,
        "tags": extract_tags(ai_text)
    }


# ==========================
# Prompt
# ==========================

def build_note_prompt(content: str) -> str:
    return f"""
以下の成長ノートを指定された形式に整理してください。

要件：

1. テーマを要約する
2. キーワードを3〜5個抽出する
3. タグを生成する（必ず #タグ の形式を使用する）
4. 今日の学びをまとめる
5. 次のステップを提案する

成長ノート：

{content}

必ず以下の形式で出力してください：

テーマ：
キーワード：
タグ：
今日のまとめ：
今後の学習提案：
"""


# ==========================
# AI呼び出し
# ==========================

def generate_text(prompt: str) -> str:

    if AI_PROVIDER == "mock":
        return generate_by_mock(prompt)

    if AI_PROVIDER == "gemini":
        try:
            return generate_by_gemini(prompt)
        except Exception as e:
            print("Gemini Error:", e)
            return generate_by_mock(prompt)

    return generate_by_mock(prompt)


# ==========================
# Mock AI
# ==========================

def generate_by_mock(prompt: str) -> str:

    return """
テーマ：
AI Growth Notes

キーワード：
AI、学習、成長

タグ：
#AI
#学習
#成長

今日のまとめ：
これは Mock AI が自動整理した結果です。

成長ノートを構造化された内容に整理しました。

今後の学習提案：
学習内容、仕事の経験、考えたことを毎日記録し、自分自身の AI 知識体系を少しずつ築いていきましょう。
"""


# ==========================
# Gemini
# ==========================

def generate_by_gemini(prompt: str) -> str:

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=AI_MODEL,
        contents=prompt
    )

    return response.text


# ==========================
# タグ解析
# ==========================

def extract_tags(ai_text: str) -> list[str]:
    """
    AIの応答からタグを抽出する

    #AI
    #Python
    #FastAPI
    """

    tags = re.findall(r"#([^\s#]+)", ai_text)

    # 重複を除去
    return list(dict.fromkeys(tags))
