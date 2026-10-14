"""
Posts a Slack alert when a client's campaign video crosses a view milestone
(100K, 250K, 500K, 750K, 1M, 2M, 3M, 4M, 5M), for videos posted on or after
the client's alert start date (Pacific time). Each client's alerts state file
maps post ID to the highest milestone already alerted, so each milestone only
alerts once.

Usage:
    python viral_alerts.py                          # Krea (or --client micro1 / all)
    python viral_alerts.py --test [--client micro1] # post one [TEST] card, not recorded
                                                    # (Krea: the William Pham reel at 250K;
                                                    # others: the client's top post)
"""

import sys
import json
import datetime
import traceback
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

from clients import ClientConfig, get_client, client_keys_from_argv, MILESTONE_ALERTS
from mcp_client import get_session
from launchpoint_client import fetch_all_posts, fetch_posts_published_since
from slack_client import post_message

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


def _load_alerted(client: ClientConfig) -> dict:
    """{post_id: highest milestone already alerted}"""
    try:
        with open(client.alerts_state_file) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_alerted(client: ClientConfig, alerted: dict) -> None:
    with open(client.alerts_state_file, "w") as f:
        json.dump(alerted, f, indent=2, sort_keys=True)
        f.write("\n")


def _highest_milestone(views: int) -> int:
    """Highest milestone at or below views, or 0 if under the first one."""
    return max((m for m in MILESTONES if views >= m), default=0)


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


def _send_alert(client: ClientConfig, post: dict, milestone: int, test: bool = False) -> None:
    fallback = f"🚀 {post['contractorName']} hit {milestone:,} views"
    try:
        post_message(client, {"text": fallback, "attachments": [_build_attachment(post, milestone, test)]})
    except (requests.HTTPError, RuntimeError) as e:
        if not post.get("thumbnail"):
            raise
        # Slack rejects the whole message if it can't fetch the image accessory
        # (e.g. an expired thumbnail URL) — resend without it rather than drop the alert.
        print(f"  Slack rejected the message ({e}); retrying without thumbnail.")
        post_message(client, {"text": fallback, "attachments": [_build_attachment(post, milestone, test, include_image=False)]})


def run(client: ClientConfig) -> None:
    cutoff_ms = int(datetime.datetime.combine(client.alert_start_date, datetime.time(), PACIFIC).timestamp() * 1000)
    print(f"[{client.name}] Checking posts on/after {client.alert_start_date} PT for new view milestones...")

    session = get_session()
    posts = fetch_posts_published_since(session, client.campaign_id, client.alert_start_date)

    undated = [p for p in posts if not p.get("uploadedAt")]
    print(f"Fetched {len(posts)} posts; skipped {len(undated)} with no uploadedAt.")
    for p in undated:
        if (p.get("views") or 0) >= MILESTONES[0]:
            print(f"  WARNING: undated post over {MILESTONES[0]:,} views — {p.get('contractorName')} "
                  f"{p.get('views'):,} views {p.get('url')} (id {p.get('id')})")

    alerted = _load_alerted(client)
    due = []
    for p in posts:
        if not p.get("uploadedAt") or p["uploadedAt"] < cutoff_ms:
            continue
        if p.get("contractorName", "").strip().lower() in client.excluded_creators:
            continue
        # If a post jumped several milestones between runs, only the highest is alerted.
        milestone = _highest_milestone(p.get("views") or 0)
        if milestone > alerted.get(p["id"], 0):
            due.append((p, milestone))

    for p, milestone in sorted(due, key=lambda d: d[0]["views"], reverse=True):
        _send_alert(client, p, milestone)
        # Save after each alert so a failure mid-run doesn't re-alert the ones already sent.
        alerted[p["id"]] = milestone
        _save_alerted(client, alerted)
        print(f"  Alerted: {p['contractorName']} — {milestone:,} milestone ({p['views']:,} views) {p['url']}")

    print(f"Done. {len(due)} new alert(s).")


def run_test(client: ClientConfig) -> None:
    session = get_session()
    if client.test_post_url:
        posts = fetch_posts_published_since(session, client.campaign_id, client.alert_start_date)
        post = next(p for p in posts if p.get("url") == client.test_post_url)
        milestone = 250_000
    else:
        post = max((p for p in fetch_all_posts(session, client.campaign_id) if p.get("uploadedAt")), key=lambda p: p.get("views") or 0)
        # A sample card needs a milestone even if the top post hasn't reached one yet.
        milestone = max(_highest_milestone(post["views"]), MILESTONES[0])
    _send_alert(client, post, milestone, test=True)
    print(f"[{client.name}] Sent [TEST] alert: {post['contractorName']} — {milestone:,} milestone ({post['views']:,} views)")


def main() -> None:
    failed = []
    for key in client_keys_from_argv(sys.argv):
        try:
            client = get_client(key)
            if "--test" in sys.argv:
                run_test(client)
            elif client.has(MILESTONE_ALERTS):
                run(client)
        except Exception:
            traceback.print_exc()
            failed.append(key)
    if failed:
        sys.exit(f"Failed for: {', '.join(failed)}")


if __name__ == "__main__":
    main()
