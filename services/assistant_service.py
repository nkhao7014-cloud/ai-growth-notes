"""Grounded answer generation with timeout and retrieval-only fallback."""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path

from ai_client import generate_by_gemini

ROOT = Path(__file__).resolve().parents[1]
AI_TIMEOUT_SECONDS = int(os.getenv("ASSISTANT_AI_TIMEOUT_SECONDS", "15"))
MAX_CONTEXT_ITEMS = 8


def ai_available() -> bool:
    return os.getenv("AI_PROVIDER", "mock").strip().lower() == "gemini" and bool(os.getenv("GEMINI_API_KEY", "").strip())


def _context(records: list[dict]) -> tuple[str, dict[str, dict]]:
    mapping, blocks = {}, []
    for index, item in enumerate(records[:MAX_CONTEXT_ITEMS], 1):
        key = f"N{index}"
        mapping[key] = item
        blocks.append(f"[{key}] source={item['source_type']} id={item['id']} date={item['date']}\n"
                      f"title: {item['title']}\ntags: {', '.join(item['tags'])}\ncontent: {item['content']}")
    return "\n\n".join(blocks), mapping


def _references(answer: str, mapping: dict[str, dict], fallback_all: bool = False) -> list[dict]:
    keys = list(dict.fromkeys(re.findall(r"\[(N\d+)\]", answer)))
    if fallback_all:
        keys = list(mapping)
    result = []
    for key in keys:
        item = mapping.get(key)
        if item:
            result.append({"type": item["source_type"], "id": item["id"], "date": item["date"],
                           "title": item["title"], "preview": item["preview"]})
    return result


def answer_question(question: str, records: list[dict]) -> dict:
    context, mapping = _context(records)
    if not records:
        return {"answer": "関連する学習記録が見つかりませんでした。記録にない内容を推測せずに回答を控えます。キーワードや期間を変えて試してください。",
                "references": [], "provider": "none", "ai_available": ai_available()}
    if not ai_available():
        answer = "AI回答は現在利用できません。関連する学習記録を下の「参照した記録」に表示しました。"
        return {"answer": answer, "references": _references(answer, mapping, fallback_all=True),
                "provider": "retrieval", "ai_available": False}
    template = (ROOT / "prompts" / "assistant.txt").read_text(encoding="utf-8")
    prompt = template.format(context=context, question=question)
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(generate_by_gemini, prompt)
    try:
        answer = (future.result(timeout=AI_TIMEOUT_SECONDS) or "").strip()
        if not answer:
            raise ValueError("empty AI response")
        return {"answer": answer, "references": _references(answer, mapping),
                "provider": "gemini", "ai_available": True}
    except TimeoutError:
        future.cancel()
        return {"answer": "AI回答が時間内に完了しませんでした。関連する学習記録は取得できています。",
                "references": _references("", mapping, fallback_all=True), "provider": "retrieval", "ai_available": True}
    except Exception:
        return {"answer": "AI回答を生成できませんでした。関連する学習記録は取得できています。",
                "references": _references("", mapping, fallback_all=True), "provider": "retrieval", "ai_available": True}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
