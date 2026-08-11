from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from services.retrieval_service import _keywords, search_user_knowledge


class Result:
    def __init__(self, rows): self.rows = rows
    def fetchall(self): return self.rows


class Connection:
    def __init__(self, results): self.results, self.calls = list(results), []
    def execute(self, sql, values=()):
        self.calls.append((sql, values))
        return Result(self.results.pop(0))


def run(results, **kwargs):
    connection = Connection(results)
    @contextmanager
    def tx(): yield connection
    with patch("services.retrieval_service.transaction", tx):
        value = search_user_knowledge("AI Agent", **kwargs)
    return value, connection


def note(note_id=1):
    return {"id": note_id, "raw_text": "AI Agent workflow", "ai_summary": "要約 #AI #Agent",
            "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc)}


def daily(item_id=2):
    return {"id": item_id, "title": "Agent update", "summary": "summary", "why_it_matters": "why",
            "title_ja": None, "summary_ja": None, "why_it_matters_ja": None, "key_points_ja": None,
            "tags": ["AI"], "knowledge_date": datetime(2026, 8, 2, tzinfo=timezone.utc)}


def test_query_search_normalizes_notes():
    values, connection = run([[note()]], sources=["notes"], limit=5)
    assert values[0]["source_type"] == "note"
    assert values[0]["tags"] == ["AI", "Agent"]
    assert "raw_text ILIKE" in connection.calls[0][0]


def test_tag_text_is_part_of_note_search():
    _, connection = run([[note()]], sources=["notes"])
    assert any("%ai%" == value for value in connection.calls[0][1])


def test_date_filters_are_parameterized():
    _, connection = run([[]], sources=["notes"], date_from=date(2026, 8, 1), date_to=date(2026, 8, 8))
    sql, params = connection.calls[0]
    assert "created_at::date >= %s" in sql and "created_at::date <= %s" in sql
    assert date(2026, 8, 1) in params and date(2026, 8, 8) in params


def test_source_filter_only_queries_selected_source():
    values, connection = run([[daily()]], sources=["ai_daily"])
    assert len(connection.calls) == 1
    assert "ai_daily_items" in connection.calls[0][0]
    assert values[0]["source_type"] == "ai_daily"


def test_ai_daily_retrieval_prefers_japanese_content():
    row = {**daily(), "title_ja": "Agentの最新情報", "summary_ja": "日本語要約",
           "why_it_matters_ja": "日本語の重要性", "key_points_ja": ["主要点"]}
    values, _ = run([[row]], sources=["ai_daily"])
    assert values[0]["title"] == "Agentの最新情報"
    assert values[0]["preview"] == "日本語要約"
    assert "主要点" in values[0]["content"]


def test_empty_result():
    values, _ = run([[]], sources=["notes"])
    assert values == []


def test_limit_is_enforced_after_merge():
    values, _ = run([[note(1), note(2), note(3)]], sources=["notes"], limit=2)
    assert len(values) == 2


def test_invalid_source_is_rejected_before_database_access():
    with pytest.raises(ValueError):
        search_user_knowledge("x", sources=["web"])


def test_generic_reflection_question_uses_recent_records_without_literal_full_sentence_search():
    assert _keywords("最近何を学んでいますか？") == []


def test_topic_question_extracts_latin_topic_terms():
    assert _keywords("AI Agentについて過去のノートをまとめてください。")[:2] == ["ai", "agent"]
