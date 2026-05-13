"""
User Handlers — Pareeksha Gurukul Refund Bot v2

FIXES vs v1:
- _show_status now takes (bot, chat_id, user_id, msg_id=None) — no more dead alias
- Single text/photo message handler with clear routing
- Removed duplicate handler conflict
"""

import logging
from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message, CallbackQuery

from config.config import States, UPI_PATTERN
from database import db
from keyboards.keyboards import (
    main_menu_kb, back_cancel_kb, cancel_home_kb,
    plan_selection_kb, confirm_kb, back_home_kb, status_list_kb,
)
from utils.messages import (
    welcome_text, STEP_NAME, STEP_MOBILE, STEP_PLAN,
    STEP_SCREENSHOT, STEP_UPI,
    INVALID_NAME, INVALID_MOBILE, INVALID_UPI, INVALID_IMAGE,
    confirmation_preview, submission_success, status_detail,
    CANCELLED, ALREADY_HAS_REQUEST, REFUND_DISABLED, BANNED_MSG,
    HELP_TEXT, NO_REQUESTS_YET, PARSE,
)

logger = logging.getLogger(__name__)


def register_user_handlers(bot: AsyncTeleBot):

    # ── /start, /help ──────────────────────────────────────────────────────────
    @bot.message_handler(commands=["start", "help"])
    async def cmd_start(msg: Message):
        u = msg.from_user
        await db.upsert_user(u.id, u.username or "", u.first_name or "", u.last_name or "")
        await db.clear_session(u.id)
        if await db.is_banned(u.id):
            await bot.send_message(msg.chat.id, BANNED_MSG, parse_mode=PARSE)
            return
        text = await welcome_text()
        await bot.send_message(msg.chat.id, text, parse_mode=PARSE, reply_markup=main_menu_kb())

    # ── /cancel ────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["cancel"])
    async def cmd_cancel(msg: Message):
        await db.clear_session(msg.from_user.id)
        await bot.send_message(msg.chat.id, CANCELLED, parse_mode=PARSE, reply_markup=main_menu_kb())

    # ── /status ────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["status"])
    async def cmd_status(msg: Message):
        await _show_status(bot, msg.chat.id, msg.from_user.id)

    # ── /refund ────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["refund"])
    async def cmd_refund(msg: Message):
        await _begin_refund(bot, msg.chat.id, msg.from_user.id)

    # ── Callback: home ─────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "home")
    async def cb_home(call: CallbackQuery):
        await db.clear_session(call.from_user.id)
        text = await welcome_text()
        try:
            await bot.edit_message_text(
                text, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=main_menu_kb(),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, text, parse_mode=PARSE, reply_markup=main_menu_kb())
        await bot.answer_callback_query(call.id)

    # ── Callback: refund_start ─────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "refund_start")
    async def cb_refund_start(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        await _begin_refund(bot, call.message.chat.id, call.from_user.id, call.message.message_id)

    # ── Callback: check_status ─────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "check_status")
    async def cb_check_status(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        await _show_status(bot, call.message.chat.id, call.from_user.id, call.message.message_id)

    # ── Callback: help ─────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "help")
    async def cb_help(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(
                HELP_TEXT, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=back_home_kb("home"),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, HELP_TEXT, parse_mode=PARSE, reply_markup=back_home_kb("home"))

    # ── Callback: cancel ───────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "cancel")
    async def cb_cancel(call: CallbackQuery):
        await db.clear_session(call.from_user.id)
        await bot.answer_callback_query(call.id, "Cancelled")
        try:
            await bot.edit_message_text(
                CANCELLED, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=main_menu_kb(),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, CANCELLED, parse_mode=PARSE, reply_markup=main_menu_kb())

    # ── Callback: plan selected ────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("plan:"))
    async def cb_plan_selected(call: CallbackQuery):
        plan_id = int(call.data.split(":")[1])
        plan = await db.get_plan(plan_id)
        if not plan:
            await bot.answer_callback_query(call.id, "Plan not found!")
            return
        await bot.answer_callback_query(call.id, f"✅ {plan['plan_name']} selected")
        _, data = await db.get_session(call.from_user.id)
        data.update({
            "plan_id":         plan["plan_id"],
            "plan_name":       plan["plan_name"],
            "original_amount": plan["original_amount"],
            "refund_amount":   plan["refund_amount"],
        })
        await db.set_session(call.from_user.id, States.SCREENSHOT, data)
        try:
            await bot.edit_message_text(
                STEP_SCREENSHOT, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=back_cancel_kb("back_to_plan"),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, STEP_SCREENSHOT, parse_mode=PARSE, reply_markup=back_cancel_kb("back_to_plan"))

    # ── Callback: back_to_plan ─────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "back_to_plan")
    async def cb_back_to_plan(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        _, data = await db.get_session(call.from_user.id)
        await db.set_session(call.from_user.id, States.PLAN, data)
        kb = await plan_selection_kb()
        try:
            await bot.edit_message_text(
                STEP_PLAN, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=kb,
            )
        except Exception:
            await bot.send_message(call.message.chat.id, STEP_PLAN, parse_mode=PARSE, reply_markup=kb)

    # ── Callback: back ─────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "back")
    async def cb_back(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        state, data = await db.get_session(call.from_user.id)
        await _go_back(bot, call.message.chat.id, call.from_user.id, state, data, call.message.message_id)

    # ── Callback: submit_confirm ───────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "submit_confirm")
    async def cb_submit_confirm(call: CallbackQuery):
        await bot.answer_callback_query(call.id, "Submitting…")
        _, data = await db.get_session(call.from_user.id)

        required = ("full_name", "mobile", "plan_id", "upi_id", "screenshot_file_id")
        if not all(k in data for k in required):
            await bot.send_message(
                call.message.chat.id,
                "⚠️ Session expired. Please start again.",
                parse_mode=PARSE, reply_markup=main_menu_kb(),
            )
            await db.clear_session(call.from_user.id)
            return

        if await db.get_active_request_for_user(call.from_user.id):
            try:
                await bot.edit_message_text(
                    ALREADY_HAS_REQUEST, call.message.chat.id, call.message.message_id,
                    parse_mode=PARSE, reply_markup=main_menu_kb(),
                )
            except Exception:
                await bot.send_message(call.message.chat.id, ALREADY_HAS_REQUEST, parse_mode=PARSE, reply_markup=main_menu_kb())
            return

        request_id, ticket_id = await db.create_request(
            user_id            = call.from_user.id,
            full_name          = data["full_name"],
            mobile             = data["mobile"],
            plan_id            = data["plan_id"],
            plan_name          = data["plan_name"],
            original_amount    = data["original_amount"],
            refund_amount      = data["refund_amount"],
            upi_id             = data["upi_id"],
            screenshot_file_id = data["screenshot_file_id"],
        )
        await db.clear_session(call.from_user.id)

        success = await submission_success(data["refund_amount"], ticket_id)
        try:
            await bot.edit_message_text(
                success, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=main_menu_kb(),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, success, parse_mode=PARSE, reply_markup=main_menu_kb())

        # Notify admin group (import here to avoid circular)
        from handlers.admin_handlers import notify_admin_group
        data["user_id"] = call.from_user.id
        await notify_admin_group(bot, request_id, data, ticket_id)

    # ── Callback: edit_details ─────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "edit_details")
    async def cb_edit_details(call: CallbackQuery):
        await bot.answer_callback_query(call.id)
        _, data = await db.get_session(call.from_user.id)
        await db.set_session(call.from_user.id, States.NAME, data)
        try:
            await bot.edit_message_text(
                STEP_NAME, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=cancel_home_kb(),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, STEP_NAME, parse_mode=PARSE, reply_markup=cancel_home_kb())

    # ── Callback: view_ticket ──────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("view_ticket:"))
    async def cb_view_ticket(call: CallbackQuery):
        ticket_id = call.data.split(":")[1]
        req = await db.get_request_by_ticket(ticket_id)
        if not req or req["user_id"] != call.from_user.id:
            await bot.answer_callback_query(call.id, "Ticket not found!")
            return
        await bot.answer_callback_query(call.id)
        text = status_detail(dict(req))
        try:
            await bot.edit_message_text(
                text, call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=back_home_kb("check_status"),
            )
        except Exception:
            await bot.send_message(call.message.chat.id, text, parse_mode=PARSE, reply_markup=back_home_kb("check_status"))

    # ── Universal text/photo message handler ───────────────────────────────────
    # NOTE: This handler ONLY fires for non-admin FSM states.
    #       Admin FSM states are handled in admin_handlers.py's
    #       handle_admin_fsm_text which is registered FIRST and returns True
    #       to stop routing when it handles the message.
    @bot.message_handler(content_types=["text", "photo"])
    async def handle_user_message(msg: Message):
        user_id = msg.from_user.id

        if await db.is_banned(user_id):
            await bot.send_message(msg.chat.id, BANNED_MSG, parse_mode=PARSE)
            return

        state, data = await db.get_session(user_id)

        if state == States.NAME:
            await _handle_name(bot, msg, data)
        elif state == States.MOBILE:
            await _handle_mobile(bot, msg, data)
        elif state == States.SCREENSHOT:
            await _handle_screenshot(bot, msg, data)
        elif state == States.UPI:
            await _handle_upi(bot, msg, data)
        else:
            # Idle or unknown — show home
            text = await welcome_text()
            await bot.send_message(msg.chat.id, text, parse_mode=PARSE, reply_markup=main_menu_kb())


# ══════════════════════════════════════════════════════════════════════════════
#  INTERNAL STEP HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
async def _begin_refund(bot: AsyncTeleBot, chat_id: int, user_id: int, msg_id: int = None):
    if await db.is_banned(user_id):
        await bot.send_message(chat_id, BANNED_MSG, parse_mode=PARSE)
        return

    if await db.get_setting("refund_enabled") == "0":
        await _edit_or_send(bot, chat_id, msg_id, REFUND_DISABLED, main_menu_kb())
        return

    if await db.get_active_request_for_user(user_id):
        await _edit_or_send(bot, chat_id, msg_id, ALREADY_HAS_REQUEST, main_menu_kb())
        return

    await db.set_session(user_id, States.NAME, {})
    await _edit_or_send(bot, chat_id, msg_id, STEP_NAME, cancel_home_kb())


async def _handle_name(bot: AsyncTeleBot, msg: Message, data: dict):
    name = (msg.text or "").strip()
    if len(name) < 3:
        await bot.send_message(msg.chat.id, INVALID_NAME, parse_mode=PARSE, reply_markup=cancel_home_kb())
        return
    data["full_name"] = name
    await db.set_session(msg.from_user.id, States.MOBILE, data)
    await bot.send_message(msg.chat.id, STEP_MOBILE, parse_mode=PARSE, reply_markup=cancel_home_kb())


async def _handle_mobile(bot: AsyncTeleBot, msg: Message, data: dict):
    mobile = (msg.text or "").strip()
    if not mobile.isdigit() or len(mobile) != 10:
        await bot.send_message(msg.chat.id, INVALID_MOBILE, parse_mode=PARSE, reply_markup=cancel_home_kb())
        return
    data["mobile"] = mobile
    await db.set_session(msg.from_user.id, States.PLAN, data)
    kb = await plan_selection_kb()
    await bot.send_message(msg.chat.id, STEP_PLAN, parse_mode=PARSE, reply_markup=kb)


async def _handle_screenshot(bot: AsyncTeleBot, msg: Message, data: dict):
    if not msg.photo:
        await bot.send_message(msg.chat.id, INVALID_IMAGE, parse_mode=PARSE, reply_markup=back_cancel_kb("back_to_plan"))
        return
    data["screenshot_file_id"] = msg.photo[-1].file_id
    await db.set_session(msg.from_user.id, States.UPI, data)
    await bot.send_message(msg.chat.id, STEP_UPI, parse_mode=PARSE, reply_markup=cancel_home_kb())


async def _handle_upi(bot: AsyncTeleBot, msg: Message, data: dict):
    upi = (msg.text or "").strip()
    if not UPI_PATTERN.match(upi):
        await bot.send_message(msg.chat.id, INVALID_UPI, parse_mode=PARSE, reply_markup=cancel_home_kb())
        return
    data["upi_id"] = upi
    await db.set_session(msg.from_user.id, States.CONFIRM, data)
    await bot.send_message(msg.chat.id, confirmation_preview(data), parse_mode=PARSE, reply_markup=confirm_kb())


async def _show_status(bot: AsyncTeleBot, chat_id: int, user_id: int, msg_id: int = None):
    requests = await db.get_user_requests(user_id, limit=5)
    if not requests:
        await _edit_or_send(bot, chat_id, msg_id, NO_REQUESTS_YET, main_menu_kb())
        return
    await _edit_or_send(
        bot, chat_id, msg_id,
        "📋 *Your Refund Requests*\n\nTap a request to view details:",
        status_list_kb(requests),
    )


async def _go_back(bot: AsyncTeleBot, chat_id: int, user_id: int, state: str, data: dict, msg_id: int = None):
    transitions = {
        States.MOBILE:     (States.NAME,       STEP_NAME,       cancel_home_kb()),
        States.PLAN:       (States.MOBILE,     STEP_MOBILE,     cancel_home_kb()),
        States.UPI:        (States.SCREENSHOT, STEP_SCREENSHOT, back_cancel_kb("back_to_plan")),
        States.CONFIRM:    (States.UPI,        STEP_UPI,        cancel_home_kb()),
    }
    if state == States.SCREENSHOT:
        await db.set_session(user_id, States.PLAN, data)
        kb = await plan_selection_kb()
        await _edit_or_send(bot, chat_id, msg_id, STEP_PLAN, kb)
        return
    if state not in transitions:
        await db.clear_session(user_id)
        text = await welcome_text()
        await _edit_or_send(bot, chat_id, msg_id, text, main_menu_kb())
        return
    new_state, text, kb = transitions[state]
    await db.set_session(user_id, new_state, data)
    await _edit_or_send(bot, chat_id, msg_id, text, kb)


async def _edit_or_send(bot: AsyncTeleBot, chat_id: int, msg_id, text: str, kb):
    """Try edit, fall back to send — avoids MessageNotModified crashes."""
    if msg_id:
        try:
            await bot.edit_message_text(text, chat_id, msg_id, parse_mode=PARSE, reply_markup=kb)
            return
        except Exception:
            pass
    await bot.send_message(chat_id, text, parse_mode=PARSE, reply_markup=kb)
