"""Translate one bounded batch of existing AI Daily rows.

Usage:
    python scripts/backfill_ai_daily_japanese.py --limit 20
Run repeatedly until processed_items is 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from database import initialize_database
from services.ai_daily_service import backfill_japanese_content


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Japanese AI Daily content")
    parser.add_argument("--limit", type=int, default=20, choices=range(1, 51),
                        metavar="1-50", help="maximum rows processed in this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="show candidate count without calling AI or updating rows")
    args = parser.parse_args()
    initialize_database()
    print(json.dumps(backfill_japanese_content(args.limit, dry_run=args.dry_run), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
