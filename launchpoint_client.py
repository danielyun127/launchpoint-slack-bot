"""
Pulls weekly campaign metrics from LaunchPoint.

Three modes, picked automatically based on env vars:

1. MCP mode (preferred, use this): if LAUNCHPOINT_MCP_URL + LAUNCHPOINT_API_KEY
   are set, we call LaunchPoint's official MCP server (get_analytics_overview).

2. Plain REST API mode: if LAUNCHPOINT_API_URL is set instead, we hit it
   directly with a session cookie. Only relevant if LaunchPoint also has a
   plain JSON endpoint separate from the MCP server.

3. Scrape mode (last resort): logs into the dashboard with Playwright and
   reads the rendered table. Fragile — only use if neither API exists.
   Requires `pip install playwright && playwright install chromium`
   (not installed by default; MCP mode covers Krea today).
"""

import os
import requests
from dataclasses import dataclass, field

MCP_URL = os.environ.get("LAUNCHPOINT_MCP_URL", "").strip()
API_KEY = os.environ.get("LAUNCHPOINT_API_KEY", "").strip()
API_URL = os.environ.get("LAUNCHPOINT_API_URL", "").strip()

# Only required for scrape mode
LAUNCHPOINT_EMAIL = os.environ.get("LAUNCHPOINT_EMAIL", "")
LAUNCHPOINT_PASSWORD = os.environ.get("LAUNCHPOINT_PASSWORD", "")
LOGIN_URL = os.environ.get("LAUNCHPOINT_LOGIN_URL", "")
CAMPAIGN_URL = os.environ.get("LAUNCHPOINT_CAMPAIGN_URL", "")
CAMPAIGN_ID = os.environ.get("LAUNCHPOINT_CAMPAIGN_ID", "8344cdc5-c1b2-4d12-ab04-44dacad85ec8")


@dataclass
class CampaignMetrics:
    # LaunchPoint is a creator/UGC platform, not an ad-click tracker: its
    # analytics_overview tool exposes views/engagement/earnings, not
    # clicks or conversions, so those aren't modeled here.
    #
    # total_spend comes from the separate REST payouts/spend endpoint
    # (docs.launchpointhq.com/api-reference/v1/payouts/report-creator-spend-per-program),
    # not the MCP server — this is the authoritative number behind the
    # dashboard's Spend tile. It breaks down as:
    #   spend = paid + paid_off_platform + awaiting + tracking
    # base_creator_payouts is get_analytics_overview's totalEarnings, which
    # is identical to this endpoint's "paid" field (both ~$53,535) — kept as
    # its own field since it comes from a different endpoint.
    total_views: int = 0
    total_creators: int = 0
    total_posts: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    engagement_rate: float = 0.0
    base_creator_payouts: float = 0.0
    paid: float = 0.0
    paid_off_platform: float = 0.0
    awaiting: float = 0.0
    tracking: float = 0.0
    total_spend: float = 0.0
    cpm: float = 0.0       # total_spend based — matches the dashboard's CPM tile
    base_cpm: float = 0.0  # base_creator_payouts based only
    top_creators: list = field(default_factory=list)  # [{"name": str, "views": int}]


# Creators excluded from the "Top Creators" report list (case-insensitive name match).
EXCLUDED_CREATOR_NAMES = {"simran batra"}


def _filter_creators(creators: list) -> list:
    return [c for c in creators if c.get("name", "").strip().lower() not in EXCLUDED_CREATOR_NAMES]


def _to_number(text: str) -> float:
    """'12.4K', '$3,200', '1,204' -> float"""
    text = text.strip().replace("$", "").replace(",", "")
    mult = 1
    if text.upper().endswith("K"):
        mult, text = 1_000, text[:-1]
    elif text.upper().endswith("M"):
        mult, text = 1_000_000, text[:-1]
    try:
        return float(text) * mult
    except ValueError:
        return 0.0


def _mcp_json(result: dict) -> dict:
    """
    MCP tool results are usually {"content": [{"type": "text", "text": "<json string>"}]}
    or sometimes structured JSON directly under "structuredContent". Handle both.
    """
    import json
    if "structuredContent" in result:
        return result["structuredContent"]
    text = result.get("content", [{}])[0].get("text", "{}")
    return json.loads(text)


def _count_posts_with_view_data(session, program_id: str) -> int:
    """
    The dashboard's "Posts" tile (e.g. "5.5k") counts posts that have picked up
    view data, not every post row LaunchPoint has recorded. get_analytics_overview's
    summary.totalPosts includes posts still at 0 views (not yet synced/hydrated),
    which is why it reads noticeably higher than the dashboard (e.g. 6,088 vs "5.5k").
    There's no server-side filter for this, so we page through list_posts and count
    client-side.
    """
    count = 0
    page = 1
    while True:
        result = session.call_tool(
            "list_posts",
            {"program_ids": [program_id], "limit": 500, "page": page},
        )
        payload = _mcp_json(result)
        rows = payload.get("data", [])
        if not rows:
            break
        count += sum(1 for r in rows if (r.get("views") or 0) > 0)
        total_pages = payload.get("totalPages", 1)
        if page >= total_pages:
            break
        page += 1
    return count


def _fetch_spend_report(program_id: str) -> dict:
    """
    Spend isn't exposed by the MCP server at all — it's a separate plain
    REST endpoint, authenticated with the same API key but as an
    "x-api-key" header instead of the MCP session's Bearer token.
    https://docs.launchpointhq.com/api-reference/v1/payouts/report-creator-spend-per-program
    """
    from urllib.parse import urlparse

    parsed = urlparse(MCP_URL)
    url = f"{parsed.scheme}://{parsed.netloc}/api/v1/payouts/spend"
    resp = requests.get(
        url,
        headers={"x-api-key": API_KEY, "Accept": "application/json"},
        params={"programId": program_id},
        timeout=30,
    )
    resp.raise_for_status()
    rows = resp.json().get("data", [])
    return rows[0] if rows else {}


def fetch_via_mcp() -> CampaignMetrics:
    """
    Calls LaunchPoint's MCP tool `get_analytics_overview`, scoped to our
    campaign via `program_id` (LaunchPoint's internal name for a campaign).
    """
    from mcp_client import get_session

    session = get_session()

    result = session.call_tool(
        "get_analytics_overview",
        {"program_id": CAMPAIGN_ID},
    )
    payload = _mcp_json(result)

    data = payload.get("data", payload)
    summary = data.get("summary", {})

    total_views = int(summary.get("totalViews", 0))
    total_likes = int(summary.get("totalLikes", 0))
    total_comments = int(summary.get("totalComments", 0))
    total_shares = int(summary.get("totalShares", 0))

    # summary.engagementRate additionally folds in totalBookmarks, which is why
    # it reads ~2.46% while the dashboard's Engagement tile shows 1.4% — the
    # dashboard defines engagement as (likes + comments + shares) / views only.
    engagement_rate = (
        round((total_likes + total_comments + total_shares) / total_views * 100, 2)
        if total_views else 0.0
    )

    base_creator_payouts = float(summary.get("totalEarnings", 0))

    spend_report = _fetch_spend_report(CAMPAIGN_ID)
    paid = float(spend_report.get("paid", 0))
    paid_off_platform = float(spend_report.get("paidOffPlatform", 0))
    awaiting = float(spend_report.get("awaiting", 0))
    tracking = float(spend_report.get("tracking", 0))
    total_spend = float(spend_report.get("spend", paid + paid_off_platform + awaiting + tracking))

    return CampaignMetrics(
        total_views=total_views,
        total_creators=int(summary.get("uniqueCreators", 0)),
        total_posts=_count_posts_with_view_data(session, CAMPAIGN_ID),
        total_likes=total_likes,
        total_comments=total_comments,
        total_shares=total_shares,
        engagement_rate=engagement_rate,
        base_creator_payouts=base_creator_payouts,
        paid=paid,
        paid_off_platform=paid_off_platform,
        awaiting=awaiting,
        tracking=tracking,
        total_spend=total_spend,
        cpm=round(total_spend / total_views * 1000, 2) if total_views else 0.0,
        base_cpm=round(base_creator_payouts / total_views * 1000, 2) if total_views else 0.0,
        top_creators=[
            {"name": c.get("name", "?"), "views": int(c.get("views", 0))}
            for c in sorted(_filter_creators(data.get("topCreators", [])), key=lambda c: c.get("views", 0), reverse=True)[:5]
        ],
    )


def fetch_via_api() -> CampaignMetrics:
    """Fill this in once you've identified the JSON endpoint + auth header/cookie."""
    session_cookie = os.environ["LAUNCHPOINT_SESSION_COOKIE"]  # grab from DevTools > Application > Cookies
    resp = requests.get(
        API_URL,
        headers={"Cookie": session_cookie, "Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    # TODO: adjust these keys to match the real response shape once you see it
    # NOTE: this fallback mode has no way to distinguish base payouts from
    # bonuses, so it reports the whole amount as base and leaves bonus at 0.
    base_payouts = float(data.get("totalPayouts", 0))
    metrics = CampaignMetrics(
        total_views=int(data.get("totalViews", 0)),
        total_creators=int(data.get("creatorCount", 0)),
        base_creator_payouts=base_payouts,
        total_spend=base_payouts,
        top_creators=[
            {"name": c.get("name", "?"), "views": int(c.get("views", 0))}
            for c in sorted(_filter_creators(data.get("creators", [])), key=lambda c: c.get("views", 0), reverse=True)[:5]
        ],
    )
    return metrics


def fetch_via_scrape() -> CampaignMetrics:
    from playwright.sync_api import sync_playwright  # optional dep, only needed for this fallback

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # --- Login ---
        page.goto(LOGIN_URL)
        # TODO: confirm these selectors against the real login form
        page.fill('input[type="email"]', LAUNCHPOINT_EMAIL)
        page.fill('input[type="password"]', LAUNCHPOINT_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # --- Go to campaign creators page ---
        page.goto(CAMPAIGN_URL)
        page.wait_for_load_state("networkidle")
        # SPA dashboards often need an extra beat for data to hydrate
        page.wait_for_timeout(2000)

        # TODO: replace these with real selectors from the creators page.
        # Right-click any summary stat (e.g. "Total Views") in Chrome > Inspect
        # to find its selector, then repeat for creators/payouts/clicks/conversions.
        def read_stat(selector: str, default: str = "0") -> str:
            el = page.query_selector(selector)
            return el.inner_text() if el else default

        total_views = _to_number(read_stat('[data-testid="total-views"]'))
        total_creators = _to_number(read_stat('[data-testid="total-creators"]'))
        total_payouts = _to_number(read_stat('[data-testid="total-payouts"]'))

        # Top creators table — adjust row/column selectors to match the real table.
        # Read all rows (not just the first 5) since some may get filtered out below.
        top_creators_raw = []
        rows = page.query_selector_all('table tbody tr')
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 2:
                top_creators_raw.append({
                    "name": cells[0].inner_text().strip(),
                    "views": int(_to_number(cells[1].inner_text())),
                })
        top_creators = _filter_creators(top_creators_raw)[:5]

        browser.close()

        return CampaignMetrics(
            total_views=int(total_views),
            total_creators=int(total_creators),
            base_creator_payouts=total_payouts,
            total_spend=total_payouts,
            top_creators=top_creators,
        )


def fetch_campaign_metrics() -> CampaignMetrics:
    if MCP_URL and API_KEY:
        return fetch_via_mcp()
    if API_URL:
        return fetch_via_api()
    return fetch_via_scrape()
