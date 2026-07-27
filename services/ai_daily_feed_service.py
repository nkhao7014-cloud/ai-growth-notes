"""Fetch and normalize small excerpts from official AI-related RSS/Atom feeds."""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree


AI_DAILY_FEEDS = (
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "default_category": "AI Product"},
    {"name": "Google AI", "url": "https://blog.google/technology/ai/rss/", "default_category": "AI Product"},
    {"name": "AWS Machine Learning Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "default_category": "Machine Learning"},
    {"name": "GitHub AI & ML", "url": "https://github.blog/ai-and-ml/feed/", "default_category": "Developer Tools"},
    {"name": "FastAPI Releases", "url": "https://github.com/fastapi/fastapi/releases.atom", "default_category": "FastAPI"},
)

FETCH_TIMEOUT_SECONDS = 10
MAX_ITEMS_PER_FEED = 12
MAX_RESPONSE_BYTES = 2_000_000
USER_AGENT = "AI-Growth-Notes/1.3 (+local RSS reader)"
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: str | None, limit: int) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html.unescape(value or ""))
        text = " ".join(parser.parts)
    except Exception:
        text = value or ""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def normalize_url(value: str | None, base_url: str | None = None) -> str | None:
    if not value:
        return None
    candidate = urljoin(base_url or "", html.unescape(value).strip())
    try:
        parts = urlsplit(candidate)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname.encode("idna").decode("ascii").lower()
        port = parts.port
        netloc = host if not port or (parts.scheme == "http" and port == 80) or (parts.scheme == "https" and port == 443) else f"{host}:{port}"
        query = urlencode(sorted(
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
        ))
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit((parts.scheme.lower(), netloc, path, query, ""))
    except (ValueError, UnicodeError):
        return None


def normalized_url_or_fallback(source_url: str | None, fallback_value: str) -> str:
    """Return a canonical web URL or a deterministic non-web deduplication URL."""
    normalized = normalize_url(source_url)
    if normalized:
        return normalized
    digest = hashlib.sha256(str(fallback_value).encode("utf-8")).hexdigest()
    return f"urn:ai-daily:fallback:{digest}"


def parse_datetime(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def _child_text(element: ElementTree.Element, names: tuple[str, ...]) -> str:
    for child in element:
        local_name = child.tag.rsplit("}", 1)[-1].lower()
        if local_name in names and (child.text or "").strip():
            return child.text or ""
    return ""


def _entry_link(entry: ElementTree.Element) -> str:
    for child in entry:
        if child.tag.rsplit("}", 1)[-1].lower() != "link":
            continue
        href = child.attrib.get("href")
        relation = child.attrib.get("rel", "alternate")
        if href and relation in {"alternate", ""}:
            return href
        if child.text:
            return child.text
    return ""


def fallback_key(source_name: str, title: str, published_at: str | None) -> str:
    raw = "\x1f".join((source_name.casefold(), title.casefold(), published_at or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_feed(payload: bytes, feed: dict) -> list[dict]:
    root = ElementTree.fromstring(payload)
    entries = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}]
    normalized: list[dict] = []
    for entry in entries[:MAX_ITEMS_PER_FEED]:
        title = clean_text(_child_text(entry, ("title",)), 300)
        raw_url = _entry_link(entry)
        url = normalize_url(raw_url, feed["url"])
        if not title or not url:
            continue
        external_id = clean_text(_child_text(entry, ("guid", "id")), 500) or None
        published_at = parse_datetime(_child_text(entry, ("pubdate", "published", "updated", "date")))
        summary = clean_text(_child_text(entry, ("description", "summary", "content", "encoded")), 1000) or title
        category = clean_text(_child_text(entry, ("category",)), 80) or feed["default_category"]
        normalized.append({
            "external_id": external_id,
            "title": title,
            "source_name": feed["name"],
            "source_url": url,
            "normalized_url": url,
            "published_at": published_at,
            "category": category,
            "summary": summary,
            "fallback_key": fallback_key(feed["name"], title, published_at),
        })
    return normalized


def fetch_feed(feed: dict) -> list[dict]:
    request = Request(feed["url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_RESPONSE_BYTES:
            raise ValueError("Feed response is too large")
        payload = response.read(MAX_RESPONSE_BYTES + 1)
    if len(payload) > MAX_RESPONSE_BYTES:
        raise ValueError("Feed response is too large")
    return parse_feed(payload, feed)
