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

## Running

```bash
python main.py             # sends one report immediately — use this to test
python main.py --schedule  # runs forever, fires every Monday 9am
```

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
