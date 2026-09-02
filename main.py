"""
Usage:
    python main.py            # run one report right now (good for testing)
    python main.py --schedule # start a long-running process that fires every
                               # day at 9:00 AM in REPORT_TIMEZONE
"""

import sys
from dotenv import load_dotenv

load_dotenv()

from launchpoint_client import fetch_campaign_metrics
from slack_reporter import send_report
from snapshot import load_snapshot, save_snapshot, compute_deltas


def run_once():
    print("Fetching LaunchPoint metrics...")
    metrics = fetch_campaign_metrics()
    previous = load_snapshot()
    deltas = compute_deltas(metrics, previous)
    print("Sending Slack report...")
    send_report(metrics, deltas)
    save_snapshot(metrics)
    print("Done.")


def run_scheduled():
    import os
    from apscheduler.schedulers.blocking import BlockingScheduler

    tz = os.environ.get("REPORT_TIMEZONE", "America/Los_Angeles")
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(run_once, "cron", hour=9, minute=0)
    print(f"Scheduler started (daily 9:00 AM {tz}). Waiting for next run...")
    scheduler.start()


if __name__ == "__main__":
    if "--schedule" in sys.argv:
        run_scheduled()
    else:
        run_once()
