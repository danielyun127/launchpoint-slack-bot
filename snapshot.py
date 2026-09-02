"""
Persists the previous run's campaign totals to data/last_snapshot.json so
main.py can diff today's totals against them and report a daily delta
alongside the all-time cumulative numbers.
"""

import json
import os
import datetime
from launchpoint_client import CampaignMetrics

SNAPSHOT_PATH = os.path.join(os.path.dirname(__file__), "data", "last_snapshot.json")


def load_snapshot() -> dict | None:
    """Returns the last saved snapshot, or None if there isn't a usable one yet."""
    try:
        with open(SNAPSHOT_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not data.get("generated_at"):
        return None
    return data


def save_snapshot(metrics: CampaignMetrics) -> None:
    os.makedirs(os.path.dirname(SNAPSHOT_PATH), exist_ok=True)
    data = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_views": metrics.total_views,
        "total_creators": metrics.total_creators,
        "total_payouts": metrics.total_payouts,
        "total_posts": metrics.total_posts,
        "engagement_rate": metrics.engagement_rate,
        "cpm": metrics.cpm,
        "top_creators": metrics.top_creators,
    }
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def compute_deltas(today: CampaignMetrics, previous: dict | None) -> dict:
    """
    Daily deltas for the cumulative counters. Engagement rate and CPM are
    rates, not running totals, so they aren't diffed here — the caller
    should just show today's value for those.

    If there's no previous snapshot (first run ever), every delta is 0.
    """
    if previous is None:
        return {"views": 0, "creators": 0, "payouts": 0.0, "posts": 0}
    return {
        "views": today.total_views - int(previous.get("total_views", 0)),
        "creators": today.total_creators - int(previous.get("total_creators", 0)),
        "payouts": today.total_payouts - float(previous.get("total_payouts", 0.0)),
        "posts": today.total_posts - int(previous.get("total_posts", 0)),
    }
