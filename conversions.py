"""
Conversions (referrals and traders) from PostHog, for clients that track them
there (FOMO).

Today the data comes from the client's shared PostHog dashboard: the page
embeds each tile's query results as JSON. That isn't a documented API, so
every load is checked before use (fresh results, the expected tiles and
columns, numbers that add up), and anything unexpected raises
ConversionsUnavailable instead of returning numbers. The report then goes out
without its conversions lines and the run fails, so it shows up.

To switch to a PostHog personal API key later, add a source that runs the
same two queries through PostHog's query API and returns the same
Conversions, and pick it in fetch_conversions(). Nothing else changes.
"""

import re
import json
import time
import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import requests

from clients import ClientConfig

TOTALS_TILE = "VO UGC Totals"
TOTALS_COLUMNS = ["total_referees", "total_referred_all_traders", "all_trader_conversion"]
DAILY_TILE = "VO UGC Daily Referrals by Creator"
DAILY_COLUMNS = ["day", "creator", "referrals"]

# Loading the page serves cached results and starts a refresh in the
# background, so a reload shortly after usually gets fresh ones.
MAX_AGE = datetime.timedelta(minutes=30)
LOAD_ATTEMPTS = 4
RETRY_WAIT_SECONDS = 20


class ConversionsUnavailable(Exception):
    """The conversions couldn't be read, or didn't pass the checks."""


@dataclass
class Conversions:
    referrals: int  # all time
    traders: int  # all time: referred users with at least one trade
    referrals_7d: int  # the 7 full days before today

    @property
    def rate(self) -> float:
        return self.traders / self.referrals * 100 if self.referrals else 0.0


def _load_tiles(url: str) -> dict:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    m = re.search(r'<script id="posthog-exported-data"[^>]*>(.*?)</script>', resp.text, re.S)
    if not m:
        raise ConversionsUnavailable("shared dashboard page has no embedded data (page format changed?)")
    try:
        # A JSON string holding the JSON document.
        data = json.loads(json.loads(m.group(1).strip()))
        return {t["insight"]["name"]: t["insight"] for t in data["dashboard"]["tiles"] if t.get("insight")}
    except (ValueError, KeyError, TypeError) as e:
        raise ConversionsUnavailable(f"couldn't parse the shared dashboard data (format changed?): {e!r}")


def _tile(tiles: dict, name: str, columns: list) -> dict:
    tile = tiles.get(name)
    if tile is None:
        raise ConversionsUnavailable(f"tile {name!r} is missing from the shared dashboard")
    if tile.get("columns") != columns:
        raise ConversionsUnavailable(f"tile {name!r} has columns {tile.get('columns')}, expected {columns}")
    if not isinstance(tile.get("result"), list):
        raise ConversionsUnavailable(f"tile {name!r} has no results")
    return tile


def _age(tile: dict) -> datetime.timedelta:
    try:
        refreshed = datetime.datetime.fromisoformat(tile["last_refresh"].replace("Z", "+00:00"))
    except (KeyError, AttributeError, ValueError):
        raise ConversionsUnavailable(f"tile {tile.get('name')!r} has no readable last_refresh")
    return datetime.datetime.now(datetime.timezone.utc) - refreshed


def _count(value, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ConversionsUnavailable(f"{what} is {value!r}, expected a non-negative whole number")
    return value


def _totals(tile: dict) -> tuple:
    if len(tile["result"]) != 1 or len(tile["result"][0]) != len(TOTALS_COLUMNS):
        raise ConversionsUnavailable(f"tile {TOTALS_TILE!r} should have one row of {len(TOTALS_COLUMNS)} values")
    referrals, traders, rate = tile["result"][0]
    referrals = _count(referrals, "all-time referrals")
    traders = _count(traders, "all-time traders")
    if traders > referrals:
        raise ConversionsUnavailable(f"more traders ({traders}) than referrals ({referrals})")
    # The tile rounds its rate to 3 decimals; it must agree with the counts.
    if referrals and (rate is None or abs(rate - traders / referrals) > 0.0006):
        raise ConversionsUnavailable(f"tile rate {rate!r} doesn't match {traders}/{referrals}")
    return referrals, traders


def _referrals_7d(tile: dict) -> int:
    tz = ZoneInfo(tile.get("timezone") or "UTC")
    today = datetime.datetime.now(tz).date()
    start = today - datetime.timedelta(days=7)
    total = 0
    for row in tile["result"]:
        try:
            day = datetime.date.fromisoformat(row[0])
        except (TypeError, ValueError, IndexError):
            raise ConversionsUnavailable(f"tile {DAILY_TILE!r} has a row with no readable day: {row!r}")
        if start <= day < today:
            total += _count(row[2], f"referrals on {day}")
    return total


def from_shared_dashboard(url: str) -> Conversions:
    for attempt in range(LOAD_ATTEMPTS):
        tiles = _load_tiles(url)
        totals = _tile(tiles, TOTALS_TILE, TOTALS_COLUMNS)
        daily = _tile(tiles, DAILY_TILE, DAILY_COLUMNS)
        age = max(_age(totals), _age(daily))
        if age <= MAX_AGE:
            break
        if attempt < LOAD_ATTEMPTS - 1:
            time.sleep(RETRY_WAIT_SECONDS)
    else:
        raise ConversionsUnavailable(f"results still {age} old after {LOAD_ATTEMPTS} loads")

    referrals, traders = _totals(totals)
    return Conversions(referrals, traders, _referrals_7d(daily))


def fetch_conversions(client: ClientConfig) -> Conversions:
    if not client.posthog_shared_url:
        raise ConversionsUnavailable("no PostHog source configured (FOMO_POSTHOG_SHARED_URL is empty)")
    try:
        return from_shared_dashboard(client.posthog_shared_url)
    except requests.RequestException as e:
        raise ConversionsUnavailable(f"couldn't load the shared dashboard: {e}")
