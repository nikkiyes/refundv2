"""
Pareeksha Gurukul Refund Bot — v2 Entry Point
"""

import asyncio
import logging
import os
import sys

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,  # DEBUG so we see every incoming update
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Suppress noisy third-party debug logs but keep ours
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ── Data dir ──────────────────────────────────────────────────────────────────
os.makedirs("data", exist_ok=True)

# ── Token check ───────────────────────────────────────────────────────────────
from config.config import BOT_TOKEN, ADMIN_IDS
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set!")
    sys.exit(1)

logger.info("Token loaded: ...%s", BOT_TOKEN[-6:])  # show last 6 chars to confirm correct token

# ── Imports ───────────────────────────────────────────────────────────────────
from telebot.async_telebot import AsyncTeleBot
from telebot.types import BotCommand

from database.db import init_db
from handlers.admin_handlers import register_admin_handlers
from handlers.user_handlers import register_user_handlers


async def main():
    logger.info("=== Starting Pareeksha Gurukul Refund Bot v2 ===")

    await init_db()
    logger.info("Database ready.")

    bot = AsyncTeleBot(BOT_TOKEN, parse_mode=None)

    # Verify token works by calling getMe
    try:
        me = await bot.get_me()
        logger.info("Bot identity confirmed: @%s (id=%s)", me.username, me.id)
    except Exception as e:
        logger.critical("getMe() FAILED — token is wrong or bot is blocked: %s", e)
        sys.exit(1)

    # Delete any existing webhook + clear pending updates
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted, pending updates cleared.")
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)

    register_admin_handlers(bot)
    register_user_handlers(bot)
    logger.info("Handlers registered. Super-admins: %s", ADMIN_IDS)

    await bot.set_my_commands([
        BotCommand("start",  "Start the bot"),
        BotCommand("refund", "Apply for a refund"),
        BotCommand("status", "Check refund status"),
        BotCommand("help",   "Help & support"),
        BotCommand("cancel", "Cancel current action"),
    ])

    logger.info("=== Bot is polling — waiting for messages ===")

    # Use skip_pending=True so old queued messages are ignored on startup
    await bot.polling(
        non_stop=True,
        skip_pending=True,
        timeout=30,
        request_timeout=60,
    )


if __name__ == "__main__":
    asyncio.run(main())
