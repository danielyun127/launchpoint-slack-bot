"""
Sends a message to a client's Teamily group through its Teamily agent
(POST https://teamily.ai/v1/agents/<agent id>/responses). The agent does the
actual posting, so the request is an instruction to post the text verbatim.

- No thread_id is passed, so every send starts a new agent thread and token
  usage doesn't grow with history.
- Each message has a deterministic Idempotency-Key (e.g. one per report day,
  one per post+milestone), so a re-run never double-posts.
- A send that doesn't come back completed and confirmed SENT (including
  requires_approval) raises, without retrying or approving.
- Nothing printed or raised contains the API key or any fragment of it; the
  agent's reply has echoed key fragments before.
"""

import re

import requests

from clients import ClientConfig

API_URL = "https://teamily.ai/v1/agents/{agent_id}/responses"
TIMEOUT_SECONDS = 300

PROMPT = """Post the message between the <message> tags to Teamily group {group_id} with a single send_text_message call.
Post it exactly as given, character for character, including line breaks and emoji: no rewording, no additions, no formatting changes. Send it once. Do nothing else.
Then reply with only `SENT <serverMsgID>` if it was delivered, or `FAILED: <error>` if it was not.

<message>
{text}
</message>"""


class TeamilySendError(RuntimeError):
    pass


def _redact(text: str, key: str) -> str:
    text = re.sub(r"tmly_sk_[^\s`'\"]*", "[REDACTED]", text)
    if key:
        text = text.replace(key, "[REDACTED]")
        # Any 6+ character run of the key, e.g. an echoed "prefix…suffix".
        for size in range(min(len(key), 12), 5, -1):
            for i in range(len(key) - size + 1):
                text = text.replace(key[i:i + size], "[REDACTED]")
    return text


def send_text(client: ClientConfig, text: str, idempotency_key: str) -> dict:
    """Posts text to the client's Teamily group. Returns the API response JSON."""
    key = client.teamily_agent_api_key
    try:
        resp = requests.post(
            API_URL.format(agent_id=client.teamily_agent_id),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
            json={"input": PROMPT.format(group_id=client.teamily_group_id, text=text)},
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise TeamilySendError(f"Teamily request failed ({idempotency_key}): {_redact(str(e), key)}") from None

    body = _redact(resp.text, key)
    if resp.status_code != 200:
        raise TeamilySendError(f"Teamily HTTP {resp.status_code} ({idempotency_key}): {body}")
    data = resp.json()
    status = data.get("status")
    reply = _redact((data.get("output") or {}).get("text") or "", key)
    credits = (data.get("usage") or {}).get("credits")
    print(f"  Teamily run {data.get('run_id')}: status={status}, credits={credits}")
    if status != "completed":
        # Includes requires_approval: never approved here.
        raise TeamilySendError(f"Teamily run not completed (status={status}, {idempotency_key}): {body}")
    if "FAILED" in reply or not re.search(r"\bSENT\b", reply):
        raise TeamilySendError(f"Teamily agent didn't confirm the send ({idempotency_key}): {reply}")
    return data
