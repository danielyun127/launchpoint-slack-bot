"""
Usage:
    python main.py                   # run Krea's report right now (good for testing)
    python main.py --client micro1   # run one client's report (krea, micro1, or all)
    python main.py --schedule        # start a long-running process that fires every
                                      # day at 9:00 AM in REPORT_TIMEZONE
"""

import sys
import traceback
from dotenv import load_dotenv

load_dotenv()

from clients import get_client, client_keys_from_argv, DAILY_REPORT, POSTS_DIGEST
from launchpoint_client import fetch_campaign_metrics
from slack_reporter import send_report


def run_client(key: str):
    client = get_client(key)
    if not client.has(DAILY_REPORT):
        return
    print(f"[{client.name}] Fetching LaunchPoint metrics...")
    metrics = fetch_campaign_metrics(client.campaign_id, client.excluded_creators)
    if client.video_goal:
        from mcp_client import get_session
        from launchpoint_client import fetch_all_posts
        from unique_videos import count_videos

        # Same post set as the report's "posts" number: posts with view data
        # (views > 0), matching the dashboard's Posts tile. Posts still at 0
        # views haven't been synced by LaunchPoint yet. Both numbers come from
        # this one fetch so they always agree.
        posts = [
            p for p in fetch_all_posts(get_session(), client.campaign_id)
            if (p.get("views") or 0) > 0
            and p.get("contractorName", "").strip().lower() not in client.excluded_creators
        ]
        counts = count_videos(posts, client.min_views)
        metrics.total_posts = len(posts)
        metrics.unique_videos, metrics.qualifying_videos = counts.unique, counts.qualifying
    print(f"[{client.name}] Sending Slack report...")
    report_ts = send_report(metrics, client)

    if client.has(POSTS_DIGEST):
        from mcp_client import get_session
        from posts_digest import send_digest

        where = "in the report's thread" if report_ts else "as a separate message (no bot token)"
        count = send_digest(get_session(), client, thread_ts=report_ts)
        print(f"[{client.name}] Sent posts digest ({count} posts) {where}.")
    print(f"[{client.name}] Done.")


def run_once(keys: list):
    # Run every client even if one fails, then exit non-zero so the failure shows up.
    failed = []
    for key in keys:
        try:
            run_client(key)
        except Exception:
            traceback.print_exc()
            failed.append(key)
    if failed:
        sys.exit(f"Failed for: {', '.join(failed)}")


def run_scheduled(keys: list):
    import os
    from apscheduler.schedulers.blocking import BlockingScheduler

    tz = os.environ.get("REPORT_TIMEZONE", "America/Los_Angeles")
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(run_once, "cron", hour=9, minute=0, args=[keys])
    print(f"Scheduler started (daily 9:00 AM {tz}). Waiting for next run...")
    scheduler.start()


if __name__ == "__main__":
    keys = client_keys_from_argv(sys.argv)
    if "--schedule" in sys.argv:
        run_scheduled(keys)
    else:
        run_once(keys)
