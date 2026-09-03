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
            "text": {"type": "plain_text", "text": f"📊 {CLIENT_NAME} — Campaign Report ({today})"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Campaign Totals (All-Time)*"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Views*\n{metrics.total_views:,}"},
                {"type": "mrkdwn", "text": f"*Active Creators*\n{metrics.total_creators:,}"},
                {"type": "mrkdwn", "text": f"*Total Posts*\n{metrics.total_posts:,}"},
                {"type": "mrkdwn", "text": f"*Total Likes*\n{metrics.total_likes:,}"},
                {"type": "mrkdwn", "text": f"*Total Comments*\n{metrics.total_comments:,}"},
                {"type": "mrkdwn", "text": f"*Total Shares*\n{metrics.total_shares:,}"},
                {"type": "mrkdwn", "text": f"*Engagement Rate*\n{metrics.engagement_rate}%"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Spend*\n${metrics.total_spend:,.2f}"},
                {"type": "mrkdwn", "text": f"*Base Creator Payouts*\n${metrics.base_creator_payouts:,.2f}"},
                {"type": "mrkdwn", "text": f"*CPM*\n${metrics.cpm:,.2f}"},
                {"type": "mrkdwn", "text": f"*Base CPM*\n${metrics.base_cpm:,.2f}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_Total Spend/CPM now come from LaunchPoint's payouts/spend endpoint and match the dashboard. Base Creator Payouts/Base CPM are confirmed post earnings only (a subset of Total Spend — the rest is paid off-platform, awaiting payout, or still tracking)._"},
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
