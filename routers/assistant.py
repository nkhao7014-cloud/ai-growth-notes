"""Authenticated Ask My Notes API."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from services.assistant_service import answer_question
from services.retrieval_service import search_user_knowledge

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


class AskInput(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    date_from: date | None = None
    date_to: date | None = None
    sources: list[Literal["notes", "ai_daily", "reports"]] = Field(default_factory=lambda: ["notes", "ai_daily", "reports"], min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_values(self):
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("question must not be blank")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        self.sources = list(dict.fromkeys(self.sources))
        return self


@router.post("/ask")
def ask(payload: AskInput):
    date_from, date_to = payload.date_from, payload.date_to
    today = date.today()
    if not date_from and not date_to:
        if "今週" in payload.question:
            date_from, date_to = today - timedelta(days=6), today
        elif "今月" in payload.question:
            date_from, date_to = today.replace(day=1), today
    records = search_user_knowledge(payload.question, limit=10, date_from=date_from,
                                    date_to=date_to, sources=payload.sources)
    result = answer_question(payload.question, records)
    return {**result, "retrieval_count": len(records)}


@router.get("/suggestions")
def suggestions():
    return {"suggestions": ["今週何を学びましたか？", "最近一番多いテーマは？", "AI Agentについてまとめて",
                            "次に何を学ぶべき？", "今月の成長を振り返って"]}
