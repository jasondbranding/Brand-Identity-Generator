#!/usr/bin/env python3
"""
run_bot.py — Brand Identity Generator Telegram Bot entry point.

Usage:
    python run_bot.py

Required env vars (in .env):
    GEMINI_API_KEY=...
    TELEGRAM_BOT_TOKEN=...

Optional:
    TELEGRAM_ALLOWED_CHAT_IDS=123456,789012   # whitelist (leave empty = allow all)
"""

from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment / .env")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not set in environment / .env")
        sys.exit(1)

    logger.info("Starting Brand Identity Generator Bot...")
    logger.info("Polling for updates — press Ctrl+C to stop")

    from bot.telegram_bot import build_app
    app = build_app(token=token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
