"""One-time helper: detach the bot from Telegram's cloud Bot API so a local server can take over.

Usage:  docker compose run --rm --no-deps bot python -m bot.logout
"""

import json
import os
import sys
import urllib.request

from dotenv import load_dotenv


def main() -> None:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if ":" not in token:
        sys.exit("BOT_TOKEN is missing in .env")
    url = f"https://api.telegram.org/bot{token}/logOut"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"logOut request failed: {e}")
    print("OK - bot logged out of the cloud API." if data.get("ok") else f"Telegram said: {data}")
    print("Wait ~10 minutes before starting the bot against the local server if it fails to log in at first.")


if __name__ == "__main__":
    main()
