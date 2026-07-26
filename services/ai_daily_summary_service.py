"""Optional, bounded AI enrichment with a deterministic fallback."""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from ai_client import generate_by_gemini
from services.ai_daily_feed_service import clean_text

AI_TIMEOUT_SECONDS = 12
MAX_AI_ITEMS_PER_REFRESH = 3


def ai_available() -> bool:
    return os.getenv("AI_PROVIDER", "mock").lower() == "gemini" and bool(os.getenv("GEMINI_API_KEY"))


def enrich_item(item: dict) -> dict:
    if not ai_available():
        return item
    prompt = f'''次の公式AIニュースを日本語で整理してください。記事全文はありません。
タイトル: {item["title"][:300]}
概要: {item["summary"][:1000]}
JSONのみを返してください:
{{"summary":"160文字以内", "why_it_matters":"160文字以内", "category":"40文字以内", "tags":["タグを最大5個"]}}'''
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(generate_by_gemini, prompt)
    try:
        raw = future.result(timeout=AI_TIMEOUT_SECONDS).strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw)
        summary = clean_text(result.get("summary"), 400)
        why = clean_text(result.get("why_it_matters"), 400)
        category = clean_text(result.get("category"), 80)
        tags = result.get("tags")
        if not summary or not why or not category or not isinstance(tags, list):
            raise ValueError("Invalid AI Daily response")
        enriched = dict(item)
        enriched.update(summary=summary, why_it_matters=why, category=category,
                        ai_tags=[clean_text(str(tag), 50) for tag in tags[:5] if clean_text(str(tag), 50)])
        return enriched
    except (TimeoutError, ValueError, TypeError, json.JSONDecodeError):
        future.cancel()
        return item
    except Exception:
        return item
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
