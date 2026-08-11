"""Japanese translation for AI Daily while preserving the original fields."""
from __future__ import annotations

import json
import os
import re

from ai_client import generate_text

TRANSLATION_KEYS = ("title_ja", "summary_ja", "why_it_matters_ja")
JAPANESE_PATTERN = re.compile(r"[ぁ-んァ-ヶ一-龥々]")


def is_japanese_article(item: dict) -> bool:
    """Detect the source language from title/summary, not generated why text."""
    source = f"{item.get('title') or ''} {item.get('summary') or ''}"
    return len(JAPANESE_PATTERN.findall(source)) >= 3


def translation_provider_status() -> dict:
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    model = os.getenv("AI_MODEL", "").strip() or None
    key_configured = bool(os.getenv("GEMINI_API_KEY", "").strip()) if provider == "gemini" else provider != "mock"
    return {"provider": provider, "model": model, "api_key_configured": key_configured,
            "available": provider != "mock" and key_configured}


def translation_succeeded(item: dict, translated: dict) -> bool:
    if is_japanese_article(item):
        return True
    text = f"{translated.get('title_ja') or ''} {translated.get('summary_ja') or ''}"
    return len(JAPANESE_PATTERN.findall(text)) >= 3


def _fallback_points(item: dict) -> list[str]:
    summary = str(item.get("summary") or "").strip()
    if not summary:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[。.!?！？])\s*", summary) if part.strip()]
    return parts[:3] or [summary[:240]]


def _fallback(item: dict) -> dict[str, object]:
    return {
        "title_ja": str(item.get("title") or ""),
        "summary_ja": str(item.get("summary") or ""),
        "why_it_matters_ja": str(item.get("why_it_matters") or ""),
        "key_points_ja": _fallback_points(item),
    }


def _extract_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("~~~"):
        text = text.split("\n", 1)[1].rsplit("~~~", 1)[0].strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def translate_ai_daily_item(item: dict) -> dict[str, object]:
    """Translate all three display fields in one AI call; always return safe values."""
    fallback = _fallback(item)
    if is_japanese_article(item):
        return fallback
    prompt = f"""あなたはAI・テクノロジーニュース専門の日本語編集者です。

以下の記事情報を、意味を変えず自然で読みやすい日本語にしてください。

ルール:
- 直訳調にしない
- AI/LLM/API/RAG/GPT/OpenAI/Claude/Gemini など一般的な技術用語は無理に日本語化しない
- 会社名・サービス名・製品名は原則そのまま
- 誇張しない
- 原文にない情報を追加しない
- summary_ja は2～4文程度の簡潔なニュース要約にする
- why_it_matters_ja は「なぜ重要なのか」が理解しやすい1～3文程度にする
- key_points_ja は最大3～5項目の短い箇条書き要素にする
- マーケティング表現を事実として強調しない
- 推測しない
- 記事全文を再現せず、与えられた短い記事情報だけを整理する
- JSON 以外は出力しない

記事情報:
<ARTICLE_DATA>
title: {fallback["title_ja"][:500]}
summary: {fallback["summary_ja"][:2000]}
why_it_matters: {fallback["why_it_matters_ja"][:1200]}
</ARTICLE_DATA>

{{
  "title_ja": "...",
  "summary_ja": "...",
  "why_it_matters_ja": "...",
  "key_points_ja": ["...", "...", "..."]
}}"""
    try:
        parsed = _extract_json(generate_text(prompt))
        result = {key: parsed.get(key) for key in TRANSLATION_KEYS}
        if not all(isinstance(value, str) and value.strip() for value in result.values()):
            raise ValueError("Translation response is missing required text fields")
        points = parsed.get("key_points_ja")
        if not isinstance(points, list):
            raise ValueError("Translation response is missing key_points_ja")
        cleaned_points = [str(point).strip() for point in points[:5] if str(point).strip()]
        if not cleaned_points:
            raise ValueError("Translation response has no key points")
        return {**{key: result[key].strip() for key in TRANSLATION_KEYS},
                "key_points_ja": cleaned_points}
    except Exception:
        return fallback


def translation_needed(item: dict, existing: dict | None) -> bool:
    if not existing:
        return True
    if not all(existing.get(key) for key in (*TRANSLATION_KEYS, "key_points_ja")):
        return True
    if not is_japanese_article(item):
        if (existing.get("title_ja") or "") == (item.get("title") or "") and (
                existing.get("summary_ja") or "") == (item.get("summary") or ""):
            return True
        if not translation_succeeded(item, existing):
            return True
    return any((existing.get(key) or "") != (item.get(key) or "")
               for key in ("title", "summary", "why_it_matters"))
