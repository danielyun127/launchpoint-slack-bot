"""
Weekly campaign email for clients that get email instead of Slack (Bon Credit):
creator budget used, all-time totals, this week's videos and top creators, and
any videos that crossed a view milestone this week. Sent through Gmail SMTP as
HTML with a plain-text fallback.

"This week" is the 7 days before today (Pacific) through now, the same window
as the Slack reports' "Top Creators (Last 7 Days)".

Usage:
    python weekly_email.py --client boncredit          # send to the client (To + CC)
    python weekly_email.py --client boncredit --test   # one [TEST] copy to daniel@vocreations.com only
"""

import os
import sys
import html
import smtplib
import datetime
import traceback
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

from clients import ClientConfig, get_client, client_keys_from_argv, WEEKLY_EMAIL
from mcp_client import get_session
from launchpoint_client import (
    CampaignMetrics, CampaignNotVisible, _mcp_json, check_campaign_visible,
    fetch_all_posts, fetch_campaign_metrics,
)

PACIFIC = ZoneInfo("America/Los_Angeles")

FROM_NAME = "Daniel Yun, Vo Creations"
REPLY_TO = "daniel@vocreations.com"
# --test sends only here: no client, no CC.
TEST_RECIPIENT = REPLY_TO

MILESTONES = [100_000, 250_000, 500_000, 1_000_000]

PLATFORM_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "facebook": "Facebook",
    "snapchat": "Snapchat",
}


@dataclass
class WeeklyData:
    metrics: CampaignMetrics
    week_start: datetime.date
    today: datetime.date
    week_posts: int
    top_videos: list  # [(post, milestone)], most views first


def _highest_milestone(views: int) -> int:
    return max((m for m in MILESTONES if views >= m), default=0)


def _milestone_label(m: int) -> str:
    return "1M+" if m >= 1_000_000 else f"{m // 1000}K"


def _views_at(session, post: dict, start_ms: int) -> int:
    """A post's views at the start of the week, from its daily metrics history."""
    if (post.get("uploadedAt") or 0) >= start_ms:
        return 0
    payload = _mcp_json(session.call_tool("get_post_metrics_history", {"post_id": post["id"], "days": 14}))
    history = payload.get("data", {}).get("history", [])
    before = [h for h in history if h.get("timestamp", 0) <= start_ms]
    if before:
        return max(before, key=lambda h: h["timestamp"])["views"]
    # History doesn't reach back to the start of the week: use the earliest
    # snapshot, so we only list crossings we can actually show happened.
    return min((h["views"] for h in history), default=post.get("views") or 0)


def gather(client: ClientConfig) -> WeeklyData:
    session = get_session(client.launchpoint_api_key)
    check_campaign_visible(session, client.campaign_id)
    metrics = fetch_campaign_metrics(client.campaign_id, client.excluded_creators, client.launchpoint_api_key)

    today = datetime.datetime.now(PACIFIC).date()
    week_start = today - datetime.timedelta(days=7)
    start_ms = int(datetime.datetime.combine(week_start, datetime.time(), PACIFIC).timestamp() * 1000)

    # Same rule as the Slack reports' posts count: posts with view data (views > 0).
    posts = [
        p for p in fetch_all_posts(session, client.campaign_id)
        if (p.get("views") or 0) > 0
        and p.get("contractorName", "").strip().lower() not in client.excluded_creators
    ]
    metrics.total_posts = len(posts)
    week_posts = sum(1 for p in posts if (p.get("uploadedAt") or 0) >= start_ms)

    top_videos = []
    for p in posts:
        now = _highest_milestone(p["views"])
        if now and now > _highest_milestone(_views_at(session, p, start_ms)):
            top_videos.append((p, now))
    top_videos.sort(key=lambda t: t[0]["views"], reverse=True)

    return WeeklyData(metrics, week_start, today, week_posts, top_videos)


def _budget(m: CampaignMetrics, client: ClientConfig) -> tuple:
    """(line, pct) — pct is None when there's no budget set."""
    spend = f"${m.total_spend:,.0f}"
    if not client.total_budget:
        return f"Creator spend: {spend}", None
    budget = float(client.total_budget)
    pct = round(m.total_spend / budget * 100) if budget else 0
    return f"Creator budget: {spend} of ${budget:,.0f} used ({pct}%)", pct


def _date(d: datetime.date) -> str:
    return d.strftime("%b %-d, %Y")


def subject(client: ClientConfig, data: WeeklyData) -> str:
    return f"{client.name} Campaign Update — Week of {_date(data.week_start)}"


def _totals(m: CampaignMetrics) -> list:
    return [
        ("Total views", f"{m.total_views:,}"),
        ("Videos posted", f"{m.total_posts:,}"),
        ("Active creators", f"{m.total_creators:,}"),
        ("Cost per 1,000 views", f"${m.cpm:,.2f}"),
    ]


def _platform(post: dict) -> str:
    return PLATFORM_NAMES.get(post.get("platform", ""), post.get("platform", "").title())


def build_text(client: ClientConfig, data: WeeklyData) -> str:
    m = data.metrics
    line, _ = _budget(m, client)
    out = [
        f"{client.name} Campaign Update",
        f"{_date(data.week_start)} – {_date(data.today)}",
        "",
        line,
        "",
        "ALL-TIME TOTALS",
        *(f"{label}: {value}" for label, value in _totals(m)),
        "",
        "THIS WEEK",
        f"Videos posted: {data.week_posts:,}",
    ]
    if m.top_creators_7d:
        out.append("Top creators by views:")
        out += [f"  {i}. {c['name']} — {c['views']:,} views" for i, c in enumerate(m.top_creators_7d, 1)]
    else:
        out.append("No new videos this week.")
    if data.top_videos:
        out += ["", "TOP VIDEOS THIS WEEK"]
        for p, ms in data.top_videos:
            out.append(f"{p['contractorName']} ({_platform(p)}) passed {_milestone_label(ms)} views — now {p['views']:,}")
            out.append(f"  {p['url']}")
    out += ["", "Reply to this email with any questions. — Daniel", ""]
    return "\n".join(out)


# Inline styles only: most email clients strip <style> blocks.
FONT = "font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;"
TEXT = "#1f2937"
MUTED = "#6b7280"
RULE = "#e5e7eb"
GREEN = "#2e7d32"


def _section_title(title: str) -> str:
    return (f'<tr><td style="padding:28px 0 8px;{FONT}font-size:14px;font-weight:600;'
            f'letter-spacing:0.06em;text-transform:uppercase;color:{MUTED};">{title}</td></tr>')


def _rows(pairs: list) -> str:
    cells = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid {RULE};{FONT}font-size:18px;color:{TEXT};">{html.escape(label)}</td>'
        f'<td align="right" style="padding:10px 0;border-bottom:1px solid {RULE};{FONT}font-size:18px;font-weight:600;color:{TEXT};">{html.escape(value)}</td></tr>'
        for label, value in pairs
    )
    return f'<tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{cells}</table></td></tr>'


def _progress_bar(pct: int) -> str:
    # A two-cell table, since many email clients ignore widths on divs.
    filled = max(0, min(100, pct))
    cells = ""
    if filled:
        cells += f'<td width="{filled}%" style="background:{GREEN};height:14px;font-size:0;line-height:0;">&nbsp;</td>'
    if filled < 100:
        cells += f'<td width="{100 - filled}%" style="background:{RULE};height:14px;font-size:0;line-height:0;">&nbsp;</td>'
    return (f'<tr><td style="padding:10px 0 0;"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'border="0" style="border-radius:7px;overflow:hidden;"><tr>{cells}</tr></table></td></tr>')


def _paragraph(text_html: str, size: int = 18, color: str = TEXT, pad: str = "6px 0") -> str:
    return f'<tr><td style="padding:{pad};{FONT}font-size:{size}px;line-height:1.5;color:{color};">{text_html}</td></tr>'


def build_html(client: ClientConfig, data: WeeklyData) -> str:
    m = data.metrics
    line, pct = _budget(m, client)
    e = html.escape

    body = [
        _paragraph(f"<strong>{e(client.name)} Campaign Update</strong>", size=26, pad="0"),
        _paragraph(f"{_date(data.week_start)} – {_date(data.today)}", size=16, color=MUTED, pad="4px 0 0"),
        _paragraph(f"<strong>{e(line)}</strong>", size=19, pad="28px 0 0"),
    ]
    if pct is not None:
        body.append(_progress_bar(pct))

    body += [_section_title("All-time totals"), _rows(_totals(m))]

    body += [_section_title("This week"), _rows([("Videos posted", f"{data.week_posts:,}")])]
    if m.top_creators_7d:
        body.append(_paragraph("Top creators by views:", pad="14px 0 2px"))
        body += [
            _paragraph(f"{i}. {e(c['name'])} — {c['views']:,} views", pad="2px 0")
            for i, c in enumerate(m.top_creators_7d, 1)
        ]
    else:
        body.append(_paragraph("No new videos this week.", pad="14px 0 0"))

    if data.top_videos:
        body.append(_section_title("Top videos this week"))
        for p, ms in data.top_videos:
            body.append(_paragraph(
                f"<strong>{e(p['contractorName'])}</strong> passed <strong>{_milestone_label(ms)}</strong> views "
                f"on {e(_platform(p))} — now {p['views']:,}<br>"
                f'<a href="{e(p["url"], quote=True)}" style="color:#1d4ed8;">Watch the video</a>',
                pad="8px 0",
            ))

    body.append(_paragraph("Reply to this email with any questions. — Daniel", pad="32px 0 0"))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{e(subject(client, data))}</title>
</head>
<body style="margin:0;padding:0;background:#ffffff;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff;">
<tr><td align="center" style="padding:24px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
{"".join(body)}
</table>
</td></tr>
</table>
</body>
</html>
"""


def _addresses(raw: str) -> list:
    return [a.strip() for a in raw.split(",") if a.strip()]


def send(client: ClientConfig, data: WeeklyData, test: bool = False) -> list:
    """Sends the email and returns the envelope recipients."""
    gmail = os.environ["GMAIL_ADDRESS"].strip()
    # Google shows app passwords in groups of four; the spaces aren't part of it.
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()

    to = [TEST_RECIPIENT] if test else _addresses(client.email_to)
    cc = [] if test else _addresses(client.email_cc)

    msg = EmailMessage()
    msg["Subject"] = ("[TEST] " if test else "") + subject(client, data)
    msg["From"] = formataddr((FROM_NAME, gmail))
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Reply-To"] = REPLY_TO
    msg.set_content(build_text(client, data))
    msg.add_alternative(build_html(client, data), subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(gmail, password)
        smtp.send_message(msg)
    return to + cc


def main() -> None:
    test = "--test" in sys.argv
    failed = []
    for key in client_keys_from_argv(sys.argv, default="boncredit"):
        try:
            client = get_client(key)
            if not client.has(WEEKLY_EMAIL):
                continue
            print(f"[{client.name}] Fetching LaunchPoint data...")
            data = gather(client)
            recipients = send(client, data, test)
            print(f"[{client.name}] Sent{' [TEST]' if test else ''} weekly email to {', '.join(recipients)}")
        except CampaignNotVisible as e:
            print(f"ERROR [{key}] Skipped, no email sent: {e}", file=sys.stderr)
            failed.append(key)
        except Exception:
            traceback.print_exc()
            failed.append(key)
    if failed:
        sys.exit(f"Failed for: {', '.join(failed)}")


if __name__ == "__main__":
    main()
