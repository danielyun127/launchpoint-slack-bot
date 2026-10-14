import datetime
from launchpoint_client import CampaignMetrics
from clients import ClientConfig
from slack_client import post_message

PROGRESS_BAR_LENGTH = 10


def _abbreviate(n: float) -> str:
    """1234 -> '1.2K', 63900000 -> '63.9M'"""
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,.0f}"


def _dollars(n: float) -> str:
    return f"${n:,.0f}"


def _progress_bar(pct: float, length: int = PROGRESS_BAR_LENGTH) -> str:
    filled = max(0, min(length, round(pct / 100 * length)))
    return "🟩" * filled + "⬜" * (length - filled)


def _budget_line(total_spend: float, budget_raw: str) -> str:
    if not budget_raw:
        return f"💰 Spend: {_dollars(total_spend)}"

    budget = float(budget_raw)
    pct = round(total_spend / budget * 100) if budget else 0
    bar = _progress_bar(pct)
    return f"💰 Budget: {_dollars(total_spend)} / {_dollars(budget)} spent ({pct}%)\n{bar}"


def _video_goal_blocks(metrics: CampaignMetrics, client: ClientConfig) -> list:
    goal = client.video_goal
    pct = round(metrics.qualifying_videos / goal * 100)
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🎬 Videos: {metrics.qualifying_videos:,} / {goal:,} ({pct}%)\n{_progress_bar(pct)}",
            },
        },
    ]


def build_blocks(metrics: CampaignMetrics, client: ClientConfig) -> list:
    today = datetime.date.today().strftime("%b %d, %Y")

    if metrics.top_creators_7d:
        top_creators_text = "\n".join(
            f"  {i+1}. {c['name']} — {_abbreviate(c['views'])} views"
            for i, c in enumerate(metrics.top_creators_7d)
        )
    else:
        top_creators_text = "  _No new posts this week_"

    if client.video_goal:
        goal_blocks = _video_goal_blocks(metrics, client)
    else:
        goal_blocks = [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": _budget_line(metrics.total_spend, client.total_budget)},
        }]

    posts_text = f"📝 {_abbreviate(metrics.total_posts)} posts"
    if client.video_goal:
        posts_text += f" ({metrics.unique_videos:,} unique)"

    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 {client.name} — Campaign Report ({today})"},
        },
        *goal_blocks,
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"👁 {_abbreviate(metrics.total_views)} views · "
                    f"{posts_text} · "
                    f"👥 {metrics.total_creators:,} active creators"
                ),
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"${metrics.cpm:,.2f} CPM · {metrics.engagement_rate}% engagement rate",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🏆 Top Creators (Last 7 Days)*\n{top_creators_text}"},
        },
    ]


def send_report(metrics: CampaignMetrics, client: ClientConfig) -> str:
    """Returns the message ts when posted via the Web API (for threading), else None."""
    return post_message(client, {"blocks": build_blocks(metrics, client)})
