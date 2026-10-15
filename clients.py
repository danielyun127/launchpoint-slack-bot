"""
Per-client configuration. Each client reads its own env vars, so Krea's
original names (LAUNCHPOINT_CAMPAIGN_ID, SLACK_WEBHOOK_URL, KREA_TOTAL_BUDGET,
ALERT_START_DATE, CLIENT_NAME) keep working unchanged. Krea, micro1 and Tab
share LAUNCHPOINT_API_KEY; Wron AI is on a separate LaunchPoint account and
uses WRON_LAUNCHPOINT_API_KEY. Bon Credit is emailed weekly instead of
posted to Slack, and uses BONCREDIT_LAUNCHPOINT_API_KEY.

Env vars are read when a client is loaded, not at import, so running one
client never requires the other client's secrets.
"""

import os
import datetime
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Feature flags
DAILY_REPORT = "daily_report"
MILESTONE_ALERTS = "milestone_alerts"
POSTS_DIGEST = "posts_digest"
WEEKLY_EMAIL = "weekly_email"


@dataclass
class ClientConfig:
    key: str
    name: str
    campaign_id: str
    slack_webhook_url: str
    total_budget: str  # raw env value; empty means "no budget line"
    video_goal: int  # unique-video goal shown instead of the budget line; 0 means none
    min_views: int  # a unique video counts toward video_goal once any of its posts has this many views
    excluded_creators: set
    alerts_state_file: str
    alert_start_date: datetime.date
    features: set
    # Each LaunchPoint account has its own key; a key only sees its account's campaigns.
    launchpoint_api_key: str
    # Optional: posting through the Slack Web API (instead of the webhook)
    # returns the message timestamp, which the posts digest needs to reply in
    # the report's thread.
    slack_bot_token: str = ""
    slack_channel_id: str = ""
    # --test milestone card uses this post; if unset, the client's top post.
    test_post_url: str = ""
    # Weekly email recipients (weekly_email.py), comma-separated.
    email_to: str = ""
    email_cc: str = ""

    def has(self, feature: str) -> bool:
        return feature in self.features


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _required(name: str) -> str:
    value = _env(name)
    if not value:
        raise RuntimeError(f"Missing required env var {name}")
    return value


def _date(name: str, default: str) -> datetime.date:
    return datetime.date.fromisoformat(_env(name, default))


def _krea() -> ClientConfig:
    return ClientConfig(
        key="krea",
        name=_env("CLIENT_NAME", "Krea"),
        campaign_id=_env("LAUNCHPOINT_CAMPAIGN_ID", "8344cdc5-c1b2-4d12-ab04-44dacad85ec8"),
        slack_webhook_url=_required("SLACK_WEBHOOK_URL"),
        total_budget=_env("KREA_TOTAL_BUDGET"),
        video_goal=0,
        min_views=0,
        excluded_creators={"simran batra"},
        alerts_state_file=os.path.join(BASE_DIR, "alerted_posts.json"),
        alert_start_date=_date("ALERT_START_DATE", "2026-10-05"),
        features={DAILY_REPORT, MILESTONE_ALERTS},
        launchpoint_api_key=_required("LAUNCHPOINT_API_KEY"),
        test_post_url="https://www.instagram.com/reel/DeHBpe8KvBy/",
    )


def _micro1() -> ClientConfig:
    return ClientConfig(
        key="micro1",
        name="micro1",
        campaign_id=_required("MICRO1_CAMPAIGN_ID"),
        slack_webhook_url=_required("MICRO1_SLACK_WEBHOOK_URL"),
        total_budget="",
        video_goal=int(_env("MICRO1_VIDEO_GOAL", "600")),
        min_views=int(_env("MICRO1_MIN_VIEWS", "1000")),
        excluded_creators=set(),
        alerts_state_file=os.path.join(BASE_DIR, "alerted_posts_micro1.json"),
        alert_start_date=_date("MICRO1_ALERT_START_DATE", "2026-10-13"),
        features={DAILY_REPORT, MILESTONE_ALERTS, POSTS_DIGEST},
        launchpoint_api_key=_required("LAUNCHPOINT_API_KEY"),
        slack_bot_token=_env("MICRO1_SLACK_BOT_TOKEN"),
        slack_channel_id=_env("MICRO1_SLACK_CHANNEL_ID"),
    )


def _tab() -> ClientConfig:
    return ClientConfig(
        key="tab",
        name="Tab",
        campaign_id=_required("TAB_CAMPAIGN_ID"),
        slack_webhook_url=_required("TAB_SLACK_WEBHOOK_URL"),
        total_budget="",
        video_goal=int(_env("TAB_VIDEO_GOAL", "750")),
        min_views=int(_env("TAB_MIN_VIEWS", "1000")),
        excluded_creators=set(),
        alerts_state_file=os.path.join(BASE_DIR, "alerted_posts_tab.json"),
        alert_start_date=_date("TAB_ALERT_START_DATE", "2026-10-13"),
        features={DAILY_REPORT, MILESTONE_ALERTS},
        launchpoint_api_key=_required("LAUNCHPOINT_API_KEY"),
    )


def _wron() -> ClientConfig:
    return ClientConfig(
        key="wron",
        name="Wron AI",
        campaign_id=_required("WRON_CAMPAIGN_ID"),
        slack_webhook_url=_required("WRON_SLACK_WEBHOOK_URL"),
        total_budget=_env("WRON_TOTAL_BUDGET"),
        video_goal=0,
        min_views=0,
        excluded_creators=set(),
        alerts_state_file=os.path.join(BASE_DIR, "alerted_posts_wron.json"),
        alert_start_date=_date("WRON_ALERT_START_DATE", "2026-10-13"),
        features={DAILY_REPORT, MILESTONE_ALERTS},
        launchpoint_api_key=_required("WRON_LAUNCHPOINT_API_KEY"),
    )


def _boncredit() -> ClientConfig:
    return ClientConfig(
        key="boncredit",
        name="Bon Credit",
        campaign_id=_required("BONCREDIT_CAMPAIGN_ID"),
        slack_webhook_url="",  # email only
        total_budget=_env("BONCREDIT_TOTAL_BUDGET"),
        video_goal=0,
        min_views=0,
        excluded_creators=set(),
        alerts_state_file="",
        alert_start_date=datetime.date.min,
        features={WEEKLY_EMAIL},
        launchpoint_api_key=_required("BONCREDIT_LAUNCHPOINT_API_KEY"),
        email_to=_required("BONCREDIT_EMAIL_TO"),
        email_cc=_env("BONCREDIT_EMAIL_CC"),
    )


CLIENTS = {"krea": _krea, "micro1": _micro1, "tab": _tab, "wron": _wron, "boncredit": _boncredit}


def get_client(key: str) -> ClientConfig:
    if key not in CLIENTS:
        raise ValueError(f"Unknown client {key!r}; expected one of {', '.join(CLIENTS)}")
    return CLIENTS[key]()


def client_keys_from_argv(argv: list, default: str = "krea") -> list:
    """`--client krea` (or micro1, tab, wron, boncredit), or `--client all`. Defaults to Krea
    so plain `python main.py` behaves exactly as it did before."""
    key = default
    if "--client" in argv:
        key = argv[argv.index("--client") + 1]
    return list(CLIENTS) if key == "all" else [key]
