"""
Posts an alert to Slack for each Krea campaign video that crosses
VIRAL_THRESHOLD views, for videos posted on or after ALERT_START_DATE
(Pacific time). Already-alerted post IDs are tracked in alerted_posts.json
so each video only alerts once.

Usage:
    python viral_alerts.py
"""

import os
import json
import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

from mcp_client import get_session
from launchpoint_client import CAMPAIGN_ID, EXCLUDED_CREATOR_NAMES, _mcp_json
from slack_reporter import _abbreviate

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
ALERT_START_DATE = datetime.date.fromisoformat(os.environ.get("ALERT_START_DATE", "").strip() or "2026-10-05")
VIRAL_THRESHOLD = int(os.environ.get("VIRAL_THRESHOLD", "").strip() or 100_000)
PACIFIC = ZoneInfo("America/Los_Angeles")

ALERTED_POSTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerted_posts.json")


def _load_alerted() -> set:
    try:
        with open(ALERTED_POSTS_PATH) as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()


def _save_alerted(ids: set) -> None:
    with open(ALERTED_POSTS_PATH, "w") as f:
        json.dump(sorted(ids), f, indent=2)
        f.write("\n")


def _fetch_posts_since(session, start_date: datetime.date) -> list:
    """
    list_posts' from_date filters on publish date, but appears to compare in
    UTC — a post made the evening before start_date in Pacific is already
    start_date in UTC. Ask for one extra day and apply the exact Pacific
    cutoff against uploadedAt ourselves.
    """
    from_date = (start_date - datetime.timedelta(days=1)).isoformat()
    posts = []
    page = 1
    while True:
        payload = _mcp_json(session.call_tool(
            "list_posts",
            {"program_ids": [CAMPAIGN_ID], "from_date": from_date, "limit": 500, "page": page},
        ))
        rows = payload.get("data", [])
        posts.extend(rows)
        if not rows or page >= payload.get("totalPages", 1):
            break
        page += 1
    return posts


def _send_alert(post: dict) -> None:
    text = f"🚀 {post['contractorName']} just hit {_abbreviate(post['views'])} views 🚀\n{post['url']}"
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": text, "unfurl_links": True, "unfurl_media": True},
        timeout=15,
    )
    resp.raise_for_status()


def run() -> None:
    cutoff_ms = int(datetime.datetime.combine(ALERT_START_DATE, datetime.time(), PACIFIC).timestamp() * 1000)
    print(f"Checking posts on/after {ALERT_START_DATE} PT with {VIRAL_THRESHOLD:,}+ views...")

    session = get_session()
    posts = _fetch_posts_since(session, ALERT_START_DATE)

    undated = [p for p in posts if not p.get("uploadedAt")]
    print(f"Fetched {len(posts)} posts; skipped {len(undated)} with no uploadedAt.")
    for p in undated:
        if (p.get("views") or 0) >= VIRAL_THRESHOLD:
            print(f"  WARNING: undated post over threshold — {p.get('contractorName')} "
                  f"{p.get('views'):,} views {p.get('url')} (id {p.get('id')})")

    alerted = _load_alerted()
    candidates = sorted(
        (
            p for p in posts
            if p.get("uploadedAt") and p["uploadedAt"] >= cutoff_ms
            and (p.get("views") or 0) >= VIRAL_THRESHOLD
            and p.get("contractorName", "").strip().lower() not in EXCLUDED_CREATOR_NAMES
            and p["id"] not in alerted
        ),
        key=lambda p: p["views"],
        reverse=True,
    )

    for p in candidates:
        _send_alert(p)
        # Save after each alert so a failure mid-run doesn't re-alert the ones already sent.
        alerted.add(p["id"])
        _save_alerted(alerted)
        print(f"  Alerted: {p['contractorName']} — {p['views']:,} views {p['url']}")

    print(f"Done. {len(candidates)} new alert(s).")


if __name__ == "__main__":
    run()
