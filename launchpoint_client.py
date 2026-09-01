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
    total_views: int = 0
    total_creators: int = 0
    total_payouts: float = 0.0
    total_posts: int = 0
    engagement_rate: float = 0.0
    cpm: float = 0.0
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

    # MCP tool results are usually {"content": [{"type": "text", "text": "<json string>"}]}
    # or sometimes structured JSON directly under "structuredContent". Handle both.
    import json
    if "structuredContent" in result:
        payload = result["structuredContent"]
    else:
        text = result.get("content", [{}])[0].get("text", "{}")
        payload = json.loads(text)

    data = payload.get("data", payload)
    summary = data.get("summary", {})

    return CampaignMetrics(
        total_views=int(summary.get("totalViews", 0)),
        total_creators=int(summary.get("uniqueCreators", 0)),
        total_payouts=float(summary.get("totalEarnings", 0)),
        total_posts=int(summary.get("totalPosts", 0)),
        engagement_rate=round(float(summary.get("engagementRate") or 0), 2),
        cpm=round(float(summary.get("cpm") or 0), 2),
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
    metrics = CampaignMetrics(
        total_views=int(data.get("totalViews", 0)),
        total_creators=int(data.get("creatorCount", 0)),
        total_payouts=float(data.get("totalPayouts", 0)),
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
            total_payouts=total_payouts,
            top_creators=top_creators,
        )


def fetch_campaign_metrics() -> CampaignMetrics:
    if MCP_URL and API_KEY:
        return fetch_via_mcp()
    if API_URL:
        return fetch_via_api()
    return fetch_via_scrape()
