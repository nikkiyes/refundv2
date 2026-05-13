"""
Pareeksha Gurukul Refund Bot — v2 Entry Point
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

from config.config import BOT_TOKEN, ADMIN_IDS
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set!")
    sys.exit(1)

logger.info("Token loaded: ...%s", BOT_TOKEN[-6:])

from telebot.async_telebot import AsyncTeleBot
from telebot.types import BotCommand

from database.db import init_db
from handlers.admin_handlers import register_admin_handlers, populate_admin_cache
from handlers.user_handlers import register_user_handlers


async def main():
    logger.info("=== Starting Pareeksha Gurukul Refund Bot v2 ===")

    await init_db()
    logger.info("Database ready.")

    bot = AsyncTeleBot(BOT_TOKEN, parse_mode=None)

    try:
        me = await bot.get_me()
        logger.info("Bot confirmed: @%s (id=%s)", me.username, me.id)
    except Exception as e:
        logger.critical("getMe() FAILED — bad token: %s", e)
        sys.exit(1)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook cleared.")
    except Exception as e:
        logger.warning("delete_webhook: %s", e)

    # Populate admin ID cache BEFORE registering handlers
    await populate_admin_cache()
    logger.info("Admin cache populated.")

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

    logger.info("=== Bot is polling ===")
    await bot.polling(
        non_stop=True,
        skip_pending=True,
        timeout=30,
        request_timeout=60,
    )


if __name__ == "__main__":
    asyncio.run(main())
