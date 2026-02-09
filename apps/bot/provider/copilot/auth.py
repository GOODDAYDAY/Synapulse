"""
GitHub authentication for the Copilot provider.

Token resolution order:
1. GITHUB_TOKEN from .env                        → use directly
2. OAuth Device Flow (GITHUB_CLIENT_ID required)  → save to .env
"""

import json
import logging
import re
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from apps.bot.config.settings import config

logger = logging.getLogger("synapulse.provider.copilot")

_env_path = Path(__file__).resolve().parent.parent.parent.parent.parent / ".env"
_token: str | None = None

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
OAUTH_APP_URL = "https://github.com/settings/developers"


def _post_form(url: str, data: dict) -> dict:
    """POST form-encoded data, return JSON response (stdlib only)."""
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        logger.error("HTTP %d from %s: %s", e.code, url, body[:300])
        raise


def _device_flow(client_id: str) -> str:
    """Run the GitHub OAuth Device Flow — prints code, opens browser, polls for token."""
    logger.info("Starting GitHub OAuth Device Flow...")

    # Step 1: Request device code
    data = _post_form(DEVICE_CODE_URL, {"client_id": client_id})
    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    # Step 2: Show code and open browser
    print(f"\n  Open:  {verification_uri}")
    print(f"  Code:  {user_code}\n")
    logger.info("Waiting for user authorization (expires in %ds)...", expires_in)
    webbrowser.open(verification_uri)

    # Step 3: Poll for token
    poll_interval = max(interval, 5)
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        resp = _post_form(TOKEN_URL, {
            "client_id": client_id,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        })

        if "access_token" in resp:
            logger.info("Device flow authorized")
            return resp["access_token"]

        error = resp.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            poll_interval += 5
        elif error == "expired_token":
            break
        elif error == "access_denied":
            raise RuntimeError("User denied authorization.")
        else:
            raise RuntimeError(f"OAuth device flow error: {error}")

    raise RuntimeError("Device code expired. Please try again.")


def _save_to_env(token: str) -> None:
    """Write or update GITHUB_TOKEN in the .env file."""
    if not _env_path.exists():
        _env_path.write_text(f"GITHUB_TOKEN={token}\n", encoding="utf-8")
        logger.info("Created .env and saved GITHUB_TOKEN")
        return

    content = _env_path.read_text(encoding="utf-8")
    if re.search(r"^GITHUB_TOKEN=.*$", content, re.MULTILINE):
        content = re.sub(
            r"^GITHUB_TOKEN=.*$",
            f"GITHUB_TOKEN={token}",
            content,
            flags=re.MULTILINE,
        )
    else:
        content = content.rstrip("\n") + f"\nGITHUB_TOKEN={token}\n"

    _env_path.write_text(content, encoding="utf-8")
    logger.info("Saved GITHUB_TOKEN to %s", _env_path)


def get_token() -> str:
    """Get a GitHub token: from .env or via OAuth Device Flow."""
    global _token
    if _token is not None:
        return _token

    # 1. From .env
    if config.GITHUB_TOKEN:
        logger.info("Using GITHUB_TOKEN from .env")
        _token = config.GITHUB_TOKEN
        return _token

    # 2. OAuth Device Flow
    if config.GITHUB_CLIENT_ID:
        token = _device_flow(config.GITHUB_CLIENT_ID)
        _save_to_env(token)
        _token = token
        return _token

    raise RuntimeError(
        "GitHub token not found and no GITHUB_CLIENT_ID configured.\n"
        "To enable OAuth Device Flow:\n"
        f"  1. Register an OAuth App at {OAUTH_APP_URL}\n"
        "  2. Set GITHUB_CLIENT_ID=<your_client_id> in .env\n"
        "  3. Restart the bot — it will generate a verification code for you\n"
        "Or set GITHUB_TOKEN directly in .env."
    )
