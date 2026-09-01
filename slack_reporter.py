import os
import datetime
import requests
from launchpoint_client import CampaignMetrics

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
CLIENT_NAME = os.environ.get("CLIENT_NAME", "Client")


def build_blocks(metrics: CampaignMetrics) -> list:
    today = datetime.date.today().strftime("%b %d, %Y")

    top_creators_text = "\n".join(
        f"  {i+1}. {c['name']} — {c['views']:,} views"
        for i, c in enumerate(metrics.top_creators)
    ) or "  _no creator data available_"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 {CLIENT_NAME} — Daily Campaign Report ({today})"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Views*\n{metrics.total_views:,}"},
                {"type": "mrkdwn", "text": f"*Active Creators*\n{metrics.total_creators:,}"},
                {"type": "mrkdwn", "text": f"*Total Payouts*\n${metrics.total_payouts:,.2f}"},
                {"type": "mrkdwn", "text": f"*Total Posts*\n{metrics.total_posts:,}"},
                {"type": "mrkdwn", "text": f"*Engagement Rate*\n{metrics.engagement_rate}%"},
                {"type": "mrkdwn", "text": f"*CPM*\n${metrics.cpm:,.2f}"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top Creators (All-Time)*\n{top_creators_text}"},
        },
    ]


def send_report(metrics: CampaignMetrics) -> None:
    payload = {"blocks": build_blocks(metrics)}
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()
