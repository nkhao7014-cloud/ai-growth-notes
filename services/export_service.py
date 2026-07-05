"""Markdown export formatting for growth notes."""

from datetime import datetime


def build_markdown(notes: list[dict], exported_at: datetime | None = None) -> str:
    """Build one UTF-8 Markdown document from notes in the supplied order."""
    exported_at = exported_at or datetime.now()
    lines = [
        "# AI Growth Notes",
        "",
        f"エクスポート日時: {exported_at.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    if not notes:
        lines.extend(["ノートはありません。", ""])

    for note in notes:
        tags = " ".join(f"#{tag}" for tag in note.get("tags", [])) or "なし"
        lines.extend([
            f"## {make_title(note.get('raw_text'))}",
            "",
            f"- 作成日時: {note.get('created_at') or '不明'}",
            f"- タグ: {tags}",
            f"- お気に入り: {'はい' if note.get('is_favorite') else 'いいえ'}",
            "",
            "### 原文",
            "",
            note.get("raw_text") or "",
            "",
            "### AI整理結果",
            "",
            note.get("ai_summary") or "",
            "",
            "---",
            "",
        ])

    return "\n".join(lines)


def make_title(raw_text: str | None, max_length: int = 60) -> str:
    """Derive a stable heading without requiring a database title column."""
    first_line = next(
        (line.strip() for line in (raw_text or "").splitlines() if line.strip()),
        "無題",
    )
    # Prevent note text from changing the heading level in the exported document.
    title = first_line.lstrip("#").strip() or "無題"
    return title if len(title) <= max_length else f"{title[:max_length - 1]}…"
