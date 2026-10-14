"""
Daily posts digest: links to every video a client's creators posted
yesterday (full day, Pacific time), grouped by creator. Posted as a threaded
reply under that morning's daily report when the client has a Slack bot
token, otherwise as a separate message right after it.
"""

import datetime
from collections import defaultdict
from zoneinfo import ZoneInfo

from clients import ClientConfig
from launchpoint_client import fetch_posts_published_since
from slack_client import post_message

PACIFIC = ZoneInfo("America/Los_Angeles")

# Slack truncates message text past ~4,000 characters; stay well under it.
MAX_MESSAGE_CHARS = 3500


def _posts_on(session, client: ClientConfig, day: datetime.date) -> list:
    start_ms = int(datetime.datetime.combine(day, datetime.time(), PACIFIC).timestamp() * 1000)
    end_ms = int(datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time(), PACIFIC).timestamp() * 1000)
    posts = fetch_posts_published_since(session, client.campaign_id, day)
    return [
        p for p in posts
        if p.get("uploadedAt") and start_ms <= p["uploadedAt"] < end_ms
        and p.get("contractorName", "").strip().lower() not in client.excluded_creators
    ]


def build_messages(posts: list, day: datetime.date) -> list:
    """Digest text, split into as many messages as needed to fit Slack's limits."""
    header = f"*📎 Posts from {day.strftime('%b %-d, %Y')} ({len(posts)} total)*"
    if not posts:
        return [f"{header}\nNo posts yesterday"]

    by_creator = defaultdict(list)
    for p in sorted(posts, key=lambda p: p["uploadedAt"]):
        by_creator[p.get("contractorName") or "Unknown creator"].append(p["url"])

    messages = []
    lines = [header]
    length = len(header)

    def flush():
        nonlocal lines, length
        messages.append("\n".join(lines))
        lines, length = [], 0

    for creator in sorted(by_creator, key=str.lower):
        urls = by_creator[creator]
        creator_line = f"\n*{creator}* ({len(urls)})"
        if length + len(creator_line) + len(urls[0]) + 2 > MAX_MESSAGE_CHARS:
            flush()
            creator_line = creator_line.lstrip("\n")
        lines.append(creator_line)
        length += len(creator_line) + 1
        for url in urls:
            if length + len(url) + 1 > MAX_MESSAGE_CHARS:
                flush()
                lines.append(f"*{creator}* (cont.)")
                length = len(lines[0]) + 1
            lines.append(url)
            length += len(url) + 1
    flush()
    return messages


def send_digest(session, client: ClientConfig, thread_ts: str = None) -> int:
    """Posts yesterday's digest; returns the number of posts it listed."""
    yesterday = datetime.datetime.now(PACIFIC).date() - datetime.timedelta(days=1)
    posts = _posts_on(session, client, yesterday)
    for text in build_messages(posts, yesterday):
        # Previews for dozens of links would bury the channel; links only.
        post_message(client, {"text": text, "unfurl_links": False, "unfurl_media": False}, thread_ts=thread_ts)
    return len(posts)
