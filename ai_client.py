import os
import re
from dotenv import load_dotenv
from google import genai

load_dotenv()

AI_PROVIDER = os.getenv("AI_PROVIDER", "mock")
AI_MODEL = os.getenv("AI_MODEL", "gemini-2.0-flash")


# ==========================
# 对外统一接口
# ==========================

def analyze_note(content: str) -> str:
    """
    返回AI整理后的文本
    """
    prompt = build_note_prompt(content)
    return generate_text(prompt)


def analyze_note_with_tags(content: str) -> dict:
    """
    返回结构化结果
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
请将下面的成长笔记整理成固定格式。

要求：

1. 提炼主题
2. 提取3~5个关键词
3. 生成标签（必须使用 #标签 格式）
4. 总结今天的收获
5. 给出下一步建议

成长笔记：

{content}

请严格按照下面格式输出：

主题：
关键词：
标签：
今日总结：
后续学习建议：
"""


# ==========================
# AI调用
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
主题：
AI Growth Notes

关键词：
AI、学习、成长

标签：
#AI
#学习
#成长

今日总结：
这是 Mock AI 自动整理后的结果。

系统已经将你的成长笔记整理成结构化内容。

后续学习建议：
继续坚持每天记录学习内容、工作经验和思考，慢慢形成自己的 AI 知识体系。
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
# 标签解析
# ==========================

def extract_tags(ai_text: str) -> list[str]:
    """
    从AI返回内容中提取标签

    #AI
    #Python
    #FastAPI
    """

    tags = re.findall(r"#([^\s#]+)", ai_text)

    # 去重
    return list(dict.fromkeys(tags))