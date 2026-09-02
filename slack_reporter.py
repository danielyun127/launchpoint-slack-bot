import os
import datetime
import requests
from launchpoint_client import CampaignMetrics

SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
CLIENT_NAME = os.environ.get("CLIENT_NAME", "Client")


def _signed_int(n: int) -> str:
    return f"+{n:,}" if n >= 0 else f"-{abs(n):,}"


def _signed_money(n: float) -> str:
    return f"+${n:,.2f}" if n >= 0 else f"-${abs(n):,.2f}"


def build_blocks(metrics: CampaignMetrics, deltas: dict) -> list:
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
            "text": {"type": "mrkdwn", "text": "*Today*"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Views Gained*\n{_signed_int(deltas['views'])}"},
                {"type": "mrkdwn", "text": f"*Creators Δ*\n{_signed_int(deltas['creators'])}"},
                {"type": "mrkdwn", "text": f"*Posts Added*\n{_signed_int(deltas['posts'])}"},
                {"type": "mrkdwn", "text": f"*Engagement Rate*\n{metrics.engagement_rate}%"},
            ],
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Spend Added*\n{_signed_money(deltas['total_spend'])}"},
                {"type": "mrkdwn", "text": f"*Base Payouts Added*\n{_signed_money(deltas['base_creator_payouts'])}"},
                {"type": "mrkdwn", "text": f"*Bonus Payouts Added*\n{_signed_money(deltas['bonus_payouts'])}"},
                {"type": "mrkdwn", "text": f"*CPM*\n${metrics.cpm:,.2f}"},
                {"type": "mrkdwn", "text": f"*Base CPM*\n${metrics.base_cpm:,.2f}"},
            ],
        },
        {"type": "divider"},
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
                {"type": "mrkdwn", "text": f"*Bonuses*\n${metrics.bonus_payouts:,.2f}"},
                {"type": "mrkdwn", "text": f"*CPM*\n${metrics.cpm:,.2f}"},
                {"type": "mrkdwn", "text": f"*Base CPM*\n${metrics.base_cpm:,.2f}"},
            ],
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "_Views, Likes, Comments, Shares, Posts, and Engagement Rate match the LaunchPoint dashboard. Total Spend/Bonuses/CPM do not — no LaunchPoint API exposes the dashboard's spend aggregation for a single campaign. Base Creator Payouts = confirmed post earnings; Bonuses = this campaign's \"Canvas post bonus charge\" ledger entries (real, but a different total than the dashboard's bonus figure)._"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Top Creators (All-Time)*\n{top_creators_text}"},
        },
    ]


def send_report(metrics: CampaignMetrics, deltas: dict) -> None:
    payload = {"blocks": build_blocks(metrics, deltas)}
    resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()
