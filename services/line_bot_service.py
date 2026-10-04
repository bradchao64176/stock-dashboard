"""LINE push transport. Called only by an explicit manual send action."""
import os
from pathlib import Path
from dotenv import dotenv_values
import requests

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def load_line_credentials():
    """Read the project file per send; explicit process variables take priority.

    No global environment mutation, cwd dependency or credential caching.
    """
    values = dotenv_values(ENV_PATH, interpolate=False)
    return tuple(os.environ.get(key, values.get(key) or "").strip()
                 for key in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID"))


def send_text(text, retry_key):
    try:
        token, recipient = load_line_credentials()
    except (OSError, UnicodeError):
        return {"ok": False, "error": "Unable to read the project LINE configuration."}
    if not token or not recipient:
        return {"ok": False, "error": "LINE credentials are not configured on the server."}
    if not text or len(text.encode("utf-16-le")) // 2 > 5000:
        return {"ok": False, "error": "Invalid LINE message length."}
    try:
        response = requests.post("https://api.line.me/v2/bot/message/push",
                                 headers={"Authorization": "Bearer " + token, "X-Line-Retry-Key": retry_key},
                                 json={"to": recipient, "messages": [{"type": "text", "text": text}]}, timeout=20)
        if response.status_code == 200 or (response.status_code == 409 and response.headers.get("x-line-accepted-request-id")):
            return {"ok": True, "error": None}
        # Never expose the provider response, headers, exception or recipient.
        return {"ok": False, "error": f"LINE rejected the request (HTTP {response.status_code})."}
    except requests.RequestException:
        return {"ok": False, "error": "LINE connection failed or timed out; delivery may be uncertain."}
