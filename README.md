# LaunchPoint → Slack Weekly Report Bot

Pulls campaign metrics (views, creators, payouts, CTR, conversions, top creators)
from a LaunchPoint dashboard campaign and posts a formatted report to Slack every
Monday morning.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed if using scrape mode
cp .env.example .env
```

Fill in `.env`:
- `LAUNCHPOINT_EMAIL` / `LAUNCHPOINT_PASSWORD` — a login with access to the campaign
- `LAUNCHPOINT_CAMPAIGN_URL` — your campaign's creators page
- `SLACK_WEBHOOK_URL` — create one at https://api.slack.com/messaging/webhooks,
  pick the channel you want the report posted to
- `CLIENT_NAME` — shown in the report header

## Getting data via LaunchPoint's MCP server (do this first)

LaunchPoint exposes an MCP server at `/api/v1/mcp` with API-key auth. This is
the cleanest path — no scraping, no fragile selectors.

1. **Rotate your API key first.** If you ever pasted a key anywhere outside
   your own `.env` (chat, Slack, a doc), treat it as burned and generate a
   fresh one from LaunchPoint's dashboard settings.
2. Put the new key + the MCP URL in `.env` (`LAUNCHPOINT_API_KEY`, `LAUNCHPOINT_MCP_URL`).
3. Run `python discover_tools.py`. It connects, lists every tool the server
   exposes, and prints each one's name and input schema.
4. Open `launchpoint_client.py` → `fetch_via_mcp()` and swap the placeholder
   tool name (`"get_campaign_metrics"`) and argument key (`"campaign_id"`) for
   whatever `discover_tools.py` actually printed. Also adjust the `data.get(...)`
   keys further down to match the real response shape.

If you'd rather not reverse-engineer the schema yourself, run `discover_tools.py`
and paste me its output — I'll fill in the exact tool call for you.

## Other ways this can fetch data (only if MCP doesn't cover what you need)

**Option A — find a plain REST endpoint**
1. Open the campaign creators page in Chrome, log in normally.
2. Open DevTools (Cmd+Opt+I) → Network tab → filter to Fetch/XHR.
3. Refresh the page and look for a request that returns JSON containing
   views/creators/payouts. Copy its URL into `LAUNCHPOINT_API_URL` in `.env`.
4. In DevTools → Application → Cookies, copy the session cookie value into
   a `LAUNCHPOINT_SESSION_COOKIE` entry in `.env`.
5. Open `launchpoint_client.py` → `fetch_via_api()` and adjust the `data.get(...)`
   keys to match the real JSON shape you see in the Network tab response.

**Option B — scrape the rendered page (fallback, more fragile)**
If there's no clean API, leave `LAUNCHPOINT_API_URL` blank. The bot will log in
with Playwright and scrape the page instead. You'll need to fill in the real
CSS selectors in `launchpoint_client.py` → `fetch_via_scrape()`:
1. Right-click a stat (e.g. the "Total Views" number) → Inspect.
2. Find a stable attribute (ideally `data-testid`, otherwise a class name).
3. Swap the placeholder selectors (`[data-testid="total-views"]` etc.) for the real ones.
4. Do the same for the top-creators table's row/column structure.

Scraping is inherently brittle — if LaunchPoint changes their frontend, the
selectors break. The API route in Option A survives redesigns much better.

## Clients

Each client (Krea, micro1, Tab) has its own config in `clients.py`: name, LaunchPoint
campaign ID, Slack webhook, total budget, creator exclusions, alerts state file,
alert start date, and which features are on. Krea keeps its original env var
names; micro1 uses `MICRO1_*` and Tab uses `TAB_*` (see `.env.example`).

| Feature | Krea | micro1 | Tab |
|---|---|---|---|
| Daily report | on | on | on |
| Report goal line | 💰 budget (`KREA_TOTAL_BUDGET`) | 🎬 unique videos (`MICRO1_VIDEO_GOAL`, default 600) | 🎬 unique videos (`TAB_VIDEO_GOAL`, default 750) |
| Milestone alerts | on (`alerted_posts.json`) | on (`alerted_posts_micro1.json`) | on (`alerted_posts_tab.json`) |
| Daily posts digest | off | on | off |

micro1's and Tab's video goals count unique videos, not posts: one video cross-posted to
TikTok, Instagram, YouTube and Facebook counts once (`unique_videos.py` groups posts by
LaunchPoint's `crossPostGroupId`, splits same-platform repeats, and merges groups from
the same creator posted within 15 minutes). A video counts toward the goal once any of
its posts reaches `MICRO1_MIN_VIEWS` / `TAB_MIN_VIEWS` (default 1000) views. Like the posts count, it only
considers posts with view data.

Every command takes `--client krea`, `--client micro1`, `--client tab`, or `--client all`, and
defaults to Krea.

## Running

```bash
python main.py                   # sends Krea's report immediately — use this to test
python main.py --client micro1   # micro1's report, followed by its posts digest
python main.py --schedule        # runs forever, fires every Monday 9am
```

### Daily posts digest (micro1)

After micro1's daily report, the bot posts links to every video posted yesterday
(full day, Pacific time), grouped by creator, split across messages if it's long.
Slack webhooks can't reply in a thread, so the digest only threads under the report
when `MICRO1_SLACK_BOT_TOKEN` and `MICRO1_SLACK_CHANNEL_ID` are set (a bot with
`chat:write`, invited to the channel). Without them it posts as a separate message
right after the report.

## Viral video alerts

```bash
python viral_alerts.py --client all   # alerts when a video posted on/after the alert start date crosses a view milestone
python viral_alerts.py --test         # posts one [TEST] alert to preview the design (not recorded)
```

Milestones are 100K, 250K, 500K, 750K, 1M, 2M, 3M, 4M and 5M views; nothing alerts
past 5M. If a video jumps several milestones between runs, only the highest one alerts.
Each client's state file maps post ID to the highest milestone already alerted.
The `Viral Video Alerts` GitHub Actions workflow runs this every 3 hours (or manually
from the Actions tab) and commits the updated file back to the repo. Alert start dates default to
2026-10-05 for Krea and 2026-10-13 for micro1 and Tab; to override them there, set
`ALERT_START_DATE` / `MICRO1_ALERT_START_DATE` / `TAB_ALERT_START_DATE` as repository *variables* (not secrets).

Both workflows run each client as a separate job, so one client failing doesn't
stop the other.

## Deploying so it actually runs weekly without your laptop being on

Pick one:
- **Cron on a small VPS / your own server**: `0 9 * * 1 cd /path/to/bot && venv/bin/python main.py`
- **GitHub Actions** scheduled workflow (`on: schedule: cron: '0 16 * * 1'` in UTC) —
  good if you don't want to manage a server, just add your `.env` values as repo secrets.
- **`python main.py --schedule`** kept alive on a box (e.g. via `pm2` or `systemd`) —
  simplest if you already have a server running your Discord bots.

## Notes

- LaunchPoint login credentials only ever live in your local `.env` — never commit it.
- If LaunchPoint ever adds an official API/export, swap it in — the rest of the
  pipeline (Slack formatting, scheduling) doesn't need to change.
