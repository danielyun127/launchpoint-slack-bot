import re
import datetime
from zoneinfo import ZoneInfo
from launchpoint_client import CampaignMetrics
from clients import ClientConfig
from slack_client import post_message

PROGRESS_BAR_LENGTH = 10
PACIFIC = ZoneInfo("America/Los_Angeles")


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


def _conversions_text(conversions) -> str:
    return (
        f"🔗 {conversions.referrals:,} referrals · {conversions.traders:,} traders ({conversions.rate:.1f}%)\n"
        f"+{conversions.referrals_7d:,} referrals in the last 7 days"
    )


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _top_creators_block(metrics: CampaignMetrics) -> dict:
    if metrics.top_creators_7d:
        top_creators_text = "\n".join(
            f"  {i+1}. {c['name']} — {_abbreviate(c['views'])} views"
            for i, c in enumerate(metrics.top_creators_7d)
        )
    else:
        top_creators_text = "  _No new posts this week_"
    return _section(f"*🏆 Top Creators (Last 7 Days)*\n{top_creators_text}")


def _stats_lines(metrics: CampaignMetrics, client: ClientConfig) -> tuple:
    posts_text = f"📝 {_abbreviate(metrics.total_posts)} posts"
    if client.video_goal:
        posts_text += f" ({metrics.unique_videos:,} unique)"
    return (
        f"👁 {_abbreviate(metrics.total_views)} views · {posts_text} · 👥 {metrics.total_creators:,} active creators",
        f"${metrics.cpm:,.2f} CPM · {metrics.engagement_rate}% engagement rate",
    )


def build_blocks(metrics: CampaignMetrics, client: ClientConfig, conversions=None, note: str = "", cohorts=None) -> list:
    """cohorts: [(label, CampaignMetrics)] for a client with several campaigns
    (client.cohorts). The budget line is then their combined spend, followed by
    a section per cohort; metrics is unused."""
    today = datetime.date.today().strftime("%b %d, %Y")
    header = [
        *([_section(note)] if note else []),
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"📊 {client.name} — Campaign Report ({today})"},
        },
    ]

    if cohorts:
        total_spend = sum(m.total_spend for _, m in cohorts)
        blocks = header + ([_section(_budget_line(total_spend, client.total_budget))] if client.show_spend else [])
        for label, m in cohorts:
            views_line, cpm_line = _stats_lines(m, client)
            blocks += [{"type": "divider"}, _section(f"*{label}*\n{views_line}\n{cpm_line}"), _top_creators_block(m)]
        return blocks

    if client.video_goal:
        goal_blocks = _video_goal_blocks(metrics, client)
    elif not client.show_spend:
        goal_blocks = []
    else:
        goal_blocks = [_section(_budget_line(metrics.total_spend, client.total_budget))]

    views_line, cpm_line = _stats_lines(metrics, client)
    return [
        *header,
        *goal_blocks,
        _section(views_line),
        _section(cpm_line),
        *([_section(_conversions_text(conversions))] if conversions else []),
        {"type": "divider"},
        _top_creators_block(metrics),
    ]


def _plain(mrkdwn: str) -> str:
    """Drops Slack's *bold* / _italic_ markers; Teamily posts plain text."""
    return re.sub(r"(?<!\w)([*_])(\S(?:.*?\S)?)\1(?!\w)", r"\2", mrkdwn)


def build_text(metrics: CampaignMetrics, client: ClientConfig, conversions=None, note: str = "", cohorts=None) -> str:
    """The same report as build_blocks, as plain text (one paragraph per block)."""
    parts = []
    for block in build_blocks(metrics, client, conversions, note, cohorts):
        if block["type"] == "divider":
            continue
        parts.append(_plain(block["text"]["text"]))
    return "\n\n".join(parts)


def send_report(metrics: CampaignMetrics, client: ClientConfig, conversions=None, note: str = "", key_suffix: str = "", cohorts=None) -> str:
    """Returns the message ts when posted via the Web API (for threading), else None.
    note and key_suffix are for one-off re-sends, e.g. a corrected report: note goes
    above the report, and key_suffix keeps Teamily from dropping the send as a duplicate
    of the day's report."""
    if client.teamily_group_id:
        from teamily_client import send_text

        day = datetime.datetime.now(PACIFIC).date().isoformat()
        key = f"{client.key}-report-{day}" + (f"-{key_suffix}" if key_suffix else "")
        text = build_text(metrics, client, conversions, note, cohorts)
        print(f"  Idempotency-Key: {key}\n{text}")
        send_text(client, text, key)
        return None
    return post_message(client, {"blocks": build_blocks(metrics, client, conversions, note, cohorts)})
