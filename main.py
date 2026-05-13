"""
Pareeksha Gurukul Refund Bot — v2 Entry Point

FIXES vs v1:
- Removed FileHandler (Railway /app is read-only — causes crash on startup)
- Removed unused 'asyncio_filters' import
- Admin handlers registered BEFORE user handlers (correct priority)
- BOT_TOKEN validation before anything else
"""

import asyncio
import logging
import os
import sys

# ── Logging — stdout only (Railway streams logs, no file needed) ──────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ── Ensure data directory exists ──────────────────────────────────────────────
os.makedirs("data", exist_ok=True)

# ── Validate token before importing anything else ─────────────────────────────
from config.config import BOT_TOKEN, ADMIN_IDS
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set! Add it to Railway environment variables.")
    sys.exit(1)

# ── Bot imports ───────────────────────────────────────────────────────────────
from telebot.async_telebot import AsyncTeleBot
from telebot.types import BotCommand

from database.db import init_db
from handlers.admin_handlers import register_admin_handlers
from handlers.user_handlers import register_user_handlers


async def main():
    logger.info("Starting Pareeksha Gurukul Refund Bot v2...")

    # Init DB first
    await init_db()
    logger.info("Database ready.")

    bot = AsyncTeleBot(BOT_TOKEN, parse_mode=None)

    # IMPORTANT: admin handlers MUST be registered first.
    # The admin FSM text handler uses func=lambda m: True and checks
    # admin state internally — it must fire before the user text handler.
    register_admin_handlers(bot)
    register_user_handlers(bot)
    logger.info("Handlers registered.")
    logger.info("Super-admins: %s", ADMIN_IDS)

    # Set user-visible commands
    await bot.set_my_commands([
        BotCommand("start",  "Start the bot"),
        BotCommand("refund", "Apply for a refund"),
        BotCommand("status", "Check refund status"),
        BotCommand("help",   "Help & support"),
        BotCommand("cancel", "Cancel current action"),
    ])

    logger.info("Bot is polling. Press Ctrl+C to stop.")
    await bot.polling(non_stop=True, timeout=30, request_timeout=60)


if __name__ == "__main__":
    asyncio.run(main())
