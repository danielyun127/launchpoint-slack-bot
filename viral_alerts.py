"""
Posts a Slack alert when a Krea campaign video crosses a view milestone
(100K, 250K, 500K, 750K, 1M, 2M, 3M, 4M, 5M), for videos posted on or after
ALERT_START_DATE (Pacific time). alerted_posts.json maps each post ID to the
highest milestone already alerted, so each milestone only alerts once.

Usage:
    python viral_alerts.py          # check for new milestones and alert
    python viral_alerts.py --test   # post one [TEST] alert for the William Pham
                                    # reel at 250K, without recording it
"""

import os
import sys
import json
import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

from mcp_client import get_session
from launchpoint_client import CAMPAIGN_ID, EXCLUDED_CREATOR_NAMES, _mcp_json

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
ALERT_START_DATE = datetime.date.fromisoformat(os.environ.get("ALERT_START_DATE", "").strip() or "2026-10-05")
PACIFIC = ZoneInfo("America/Los_Angeles")

MILESTONES = [100_000, 250_000, 500_000, 750_000, 1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000]
ALERT_COLOR = "#4A90E2"

PLATFORM_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "snapchat": "Snapchat",
}

ALERTED_POSTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alerted_posts.json")

TEST_POST_URL = "https://www.instagram.com/reel/DeHBpe8KvBy/"


def _load_alerted() -> dict:
    """{post_id: highest milestone already alerted}"""
    try:
        with open(ALERTED_POSTS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_alerted(alerted: dict) -> None:
    with open(ALERTED_POSTS_PATH, "w") as f:
        json.dump(alerted, f, indent=2, sort_keys=True)
        f.write("\n")


def _highest_milestone(views: int) -> int:
    """Highest milestone at or below views, or 0 if under the first one."""
    return max((m for m in MILESTONES if views >= m), default=0)


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


def _build_attachment(post: dict, milestone: int, test: bool = False, include_image: bool = True) -> dict:
    creator = post["contractorName"]
    platform = PLATFORM_NAMES.get(post.get("platform", ""), post.get("platform", "").title())
    posted = datetime.datetime.fromtimestamp(post["uploadedAt"] / 1000, PACIFIC)
    header = f"🚀 Milestone: {creator} 🚀"
    if test:
        header = f"[TEST] {header}"

    section = {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                f"*{creator}* hit a new *Views* milestone on *{platform}*!\n\n"
                f"📈 *{post['views']:,}* Views\n"
                f"🎯 Milestone: *{milestone:,}*"
            ),
        },
    }
    if include_image and post.get("thumbnail"):
        section["accessory"] = {"type": "image", "image_url": post["thumbnail"], "alt_text": f"{creator} post thumbnail"}

    return {
        "color": ALERT_COLOR,
        "fallback": f"{creator} hit {milestone:,} views on {platform}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": header, "emoji": True}},
            {"type": "divider"},
            section,
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*📱 Platform*\n{platform}"},
                    {"type": "mrkdwn", "text": f"*📅 Posted*\n{posted.strftime('%b %-d, %Y')}"},
                ],
            },
            {
                # LaunchPoint returns only platform handles, no creator profile URL,
                # so there's no profile button.
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Open post ↗️", "emoji": True}, "url": post["url"]},
                ],
            },
        ],
    }


def _send_alert(post: dict, milestone: int, test: bool = False) -> None:
    fallback = f"🚀 {post['contractorName']} hit {milestone:,} views"
    resp = requests.post(
        SLACK_WEBHOOK_URL,
        json={"text": fallback, "attachments": [_build_attachment(post, milestone, test)]},
        timeout=15,
    )
    if not resp.ok and post.get("thumbnail"):
        # Slack rejects the whole message if it can't fetch the image accessory
        # (e.g. an expired thumbnail URL) — resend without it rather than drop the alert.
        print(f"  Slack rejected the message ({resp.status_code} {resp.text}); retrying without thumbnail.")
        resp = requests.post(
            SLACK_WEBHOOK_URL,
            json={"text": fallback, "attachments": [_build_attachment(post, milestone, test, include_image=False)]},
            timeout=15,
        )
    resp.raise_for_status()


def run() -> None:
    cutoff_ms = int(datetime.datetime.combine(ALERT_START_DATE, datetime.time(), PACIFIC).timestamp() * 1000)
    print(f"Checking posts on/after {ALERT_START_DATE} PT for new view milestones...")

    session = get_session()
    posts = _fetch_posts_since(session, ALERT_START_DATE)

    undated = [p for p in posts if not p.get("uploadedAt")]
    print(f"Fetched {len(posts)} posts; skipped {len(undated)} with no uploadedAt.")
    for p in undated:
        if (p.get("views") or 0) >= MILESTONES[0]:
            print(f"  WARNING: undated post over {MILESTONES[0]:,} views — {p.get('contractorName')} "
                  f"{p.get('views'):,} views {p.get('url')} (id {p.get('id')})")

    alerted = _load_alerted()
    due = []
    for p in posts:
        if not p.get("uploadedAt") or p["uploadedAt"] < cutoff_ms:
            continue
        if p.get("contractorName", "").strip().lower() in EXCLUDED_CREATOR_NAMES:
            continue
        # If a post jumped several milestones between runs, only the highest is alerted.
        milestone = _highest_milestone(p.get("views") or 0)
        if milestone > alerted.get(p["id"], 0):
            due.append((p, milestone))

    for p, milestone in sorted(due, key=lambda d: d[0]["views"], reverse=True):
        _send_alert(p, milestone)
        # Save after each alert so a failure mid-run doesn't re-alert the ones already sent.
        alerted[p["id"]] = milestone
        _save_alerted(alerted)
        print(f"  Alerted: {p['contractorName']} — {milestone:,} milestone ({p['views']:,} views) {p['url']}")

    print(f"Done. {len(due)} new alert(s).")


def run_test() -> None:
    posts = _fetch_posts_since(get_session(), ALERT_START_DATE)
    post = next(p for p in posts if p.get("url") == TEST_POST_URL)
    _send_alert(post, 250_000, test=True)
    print(f"Sent [TEST] alert: {post['contractorName']} — 250,000 milestone ({post['views']:,} views)")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test()
    else:
        run()
