"""
Sends a message to a client's Slack channel.

Incoming webhooks can't reply in a thread usefully: their response is just
"ok", with no timestamp for the message they posted. So when a client has a
bot token + channel ID, messages go through the Web API (chat.postMessage),
which returns the timestamp we need as thread_ts. Otherwise we fall back to
the webhook and return None.
"""

import requests

from clients import ClientConfig


def post_message(client: ClientConfig, payload: dict, thread_ts: str = None) -> str:
    """Posts payload (text/blocks/attachments) and returns its ts, or None via webhook."""
    if client.slack_bot_token and client.slack_channel_id:
        body = dict(payload, channel=client.slack_channel_id)
        if thread_ts:
            body["thread_ts"] = thread_ts
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {client.slack_bot_token}"},
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack chat.postMessage failed: {data.get('error')}")
        return data["ts"]

    resp = requests.post(client.slack_webhook_url, json=payload, timeout=15)
    resp.raise_for_status()
    return None
