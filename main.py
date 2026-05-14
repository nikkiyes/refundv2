"""
Pareeksha Gurukul Refund Bot — v2
CLEAN ARCHITECTURE: Single dispatcher file handles ALL message routing.
No competing handlers. No ambiguous func= filters.
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
logger = logging.getLogger(__name__)

os.makedirs("data", exist_ok=True)

from config.config import BOT_TOKEN, ADMIN_IDS
if not BOT_TOKEN:
    logger.critical("BOT_TOKEN not set in environment variables!")
    sys.exit(1)

from telebot.async_telebot import AsyncTeleBot
from telebot.types import BotCommand, Message, CallbackQuery

from database.db import init_db
import database.db as db
from config.config import States, UPI_PATTERN, ADMIN_GROUP_ID

# Import keyboard builders
from keyboards.keyboards import (
    main_menu_kb, cancel_home_kb, back_cancel_kb, back_home_kb,
    confirm_kb, plan_selection_kb, status_list_kb,
    admin_main_menu_kb, admin_back_kb, admin_plans_kb, admin_plan_action_kb,
    admin_request_kb, admin_confirm_approve_kb, admin_confirm_decline_kb,
    admin_confirm_ban_kb, admin_send_conf_kb, admin_settings_kb,
    admin_admins_kb, paginate_kb, request_detail_kb, search_type_kb,
)

# Import message templates
from utils.messages import (
    welcome_text, STEP_NAME, STEP_MOBILE, STEP_PLAN, STEP_SCREENSHOT, STEP_UPI,
    INVALID_NAME, INVALID_MOBILE, INVALID_UPI, INVALID_IMAGE,
    confirmation_preview, submission_success, status_detail,
    CANCELLED, ALREADY_HAS_REQUEST, REFUND_DISABLED, BANNED_MSG, HELP_TEXT,
    NO_REQUESTS_YET, user_approved_msg, user_declined_msg,
    admin_request_card, admin_stats_card, PARSE,
)

import io
import logging as _logging
from datetime import datetime

_log = _logging.getLogger("bot.handlers")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
async def _send(bot, chat_id, text, kb=None):
    await bot.send_message(chat_id, text, parse_mode=PARSE, reply_markup=kb)

async def _edit(bot, chat_id, msg_id, text, kb=None):
    try:
        await bot.edit_message_text(text, chat_id, msg_id, parse_mode=PARSE, reply_markup=kb)
    except Exception:
        await bot.send_message(chat_id, text, parse_mode=PARSE, reply_markup=kb)

async def _answer(bot, call, text=""):
    try:
        await bot.answer_callback_query(call.id, text)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN GUARD
# ══════════════════════════════════════════════════════════════════════════════
async def is_admin(user_id: int) -> bool:
    """Check ADMIN_IDS env var first (instant), then DB."""
    if user_id in ADMIN_IDS:
        return True
    return await db.is_admin(user_id)


# ══════════════════════════════════════════════════════════════════════════════
#  REGISTER ALL HANDLERS
# ══════════════════════════════════════════════════════════════════════════════
def register_all_handlers(bot: AsyncTeleBot):

    # ──────────────────────────────────────────────────────────────────────────
    #  COMMANDS  (highest priority — always registered first)
    # ──────────────────────────────────────────────────────────────────────────

    @bot.message_handler(commands=["start", "help"])
    async def cmd_start(msg: Message):
        u = msg.from_user
        await db.upsert_user(u.id, u.username or "", u.first_name or "", u.last_name or "")
        await db.clear_session(u.id)
        if await db.is_banned(u.id):
            await _send(bot, msg.chat.id, BANNED_MSG)
            return
        _log.info("cmd_start uid=%s", u.id)
        await _send(bot, msg.chat.id, await welcome_text(), main_menu_kb())

    @bot.message_handler(commands=["cancel"])
    async def cmd_cancel(msg: Message):
        await db.clear_session(msg.from_user.id)
        await _send(bot, msg.chat.id, CANCELLED, main_menu_kb())

    @bot.message_handler(commands=["status"])
    async def cmd_status(msg: Message):
        await _show_user_status(bot, msg.chat.id, msg.from_user.id)

    @bot.message_handler(commands=["refund"])
    async def cmd_refund(msg: Message):
        await _start_refund(bot, msg.chat.id, msg.from_user.id)

    @bot.message_handler(commands=["admin"])
    async def cmd_admin(msg: Message):
        uid = msg.from_user.id
        _log.info("cmd_admin uid=%s is_admin=%s", uid, await is_admin(uid))
        if not await is_admin(uid):
            await _send(bot, msg.chat.id, "🚫 You are not an admin.")
            return
        await _send(bot, msg.chat.id,
            f"👑 *Admin Panel — Pareeksha Gurukul*\n\nWelcome, {msg.from_user.first_name}!\nSelect an action:",
            admin_main_menu_kb())

    @bot.message_handler(commands=["stats"])
    async def cmd_stats(msg: Message):
        if not await is_admin(msg.from_user.id):
            return
        stats = await db.get_stats()
        await _send(bot, msg.chat.id, admin_stats_card(stats), admin_back_kb())

    @bot.message_handler(commands=["plans"])
    async def cmd_plans(msg: Message):
        if not await is_admin(msg.from_user.id):
            return
        plans = await db.get_all_plans()
        await _send(bot, msg.chat.id, "📚 *Manage Plans*", admin_plans_kb(plans))

    @bot.message_handler(commands=["export"])
    async def cmd_export(msg: Message):
        if not await is_admin(msg.from_user.id):
            return
        await _do_export(bot, msg.chat.id)

    @bot.message_handler(commands=["broadcast"])
    async def cmd_broadcast(msg: Message):
        if not await is_admin(msg.from_user.id):
            return
        await db.set_session(msg.from_user.id, States.A_BROADCAST, {})
        await _send(bot, msg.chat.id, "📢 Enter the message to broadcast:")

    @bot.message_handler(commands=["requests"])
    async def cmd_requests(msg: Message):
        if not await is_admin(msg.from_user.id):
            return
        await _send(bot, msg.chat.id, "📋 *View Requests*", admin_main_menu_kb())

    # ──────────────────────────────────────────────────────────────────────────
    #  ALL TEXT & PHOTO — single handler, routes by state
    # ──────────────────────────────────────────────────────────────────────────

    @bot.message_handler(content_types=["text", "photo"])
    async def handle_message(msg: Message):
        uid   = msg.from_user.id
        state, data = await db.get_session(uid)
        _log.info("handle_message uid=%s state=%s text=%s",
                  uid, state, (msg.text or "")[:30])

        # ── Admin FSM states ───────────────────────────────────────────────
        if state in States.ALL_ADMIN_INPUT and await is_admin(uid):
            await _handle_admin_fsm(bot, msg, uid, state, data)
            return

        # ── User FSM states ────────────────────────────────────────────────
        if await db.is_banned(uid):
            await _send(bot, msg.chat.id, BANNED_MSG)
            return

        if state == States.NAME:
            await _handle_name(bot, msg, data)
        elif state == States.MOBILE:
            await _handle_mobile(bot, msg, data)
        elif state == States.SCREENSHOT:
            await _handle_screenshot(bot, msg, data)
        elif state == States.UPI:
            await _handle_upi(bot, msg, data)
        else:
            # Idle — show home
            await _send(bot, msg.chat.id, await welcome_text(), main_menu_kb())

    # ──────────────────────────────────────────────────────────────────────────
    #  CALLBACK QUERIES
    # ──────────────────────────────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda c: True)
    async def handle_callback(call: CallbackQuery):
        d   = call.data
        uid = call.from_user.id
        cid = call.message.chat.id
        mid = call.message.message_id
        _log.info("callback uid=%s data=%s", uid, d)

        # ── USER CALLBACKS ─────────────────────────────────────────────────
        if d == "home":
            await db.clear_session(uid)
            await _answer(bot, call)
            await _edit(bot, cid, mid, await welcome_text(), main_menu_kb())

        elif d == "refund_start":
            await _answer(bot, call)
            await _start_refund(bot, cid, uid, mid)

        elif d == "check_status":
            await _answer(bot, call)
            await _show_user_status(bot, cid, uid, mid)

        elif d == "help":
            await _answer(bot, call)
            await _edit(bot, cid, mid, HELP_TEXT, back_home_kb("home"))

        elif d == "cancel":
            await db.clear_session(uid)
            await _answer(bot, call, "Cancelled")
            await _edit(bot, cid, mid, CANCELLED, main_menu_kb())

        elif d == "back":
            await _answer(bot, call)
            state, data = await db.get_session(uid)
            await _go_back(bot, cid, uid, state, data, mid)

        elif d == "back_to_plan":
            await _answer(bot, call)
            _, data = await db.get_session(uid)
            await db.set_session(uid, States.PLAN, data)
            await _edit(bot, cid, mid, STEP_PLAN, await plan_selection_kb())

        elif d.startswith("plan:"):
            plan_id = int(d.split(":")[1])
            plan = await db.get_plan(plan_id)
            if not plan:
                await _answer(bot, call, "Plan not found!")
                return
            await _answer(bot, call, f"✅ {plan['plan_name']} selected")
            _, data = await db.get_session(uid)
            data.update({
                "plan_id": plan["plan_id"],
                "plan_name": plan["plan_name"],
                "original_amount": plan["original_amount"],
                "refund_amount": plan["refund_amount"],
            })
            await db.set_session(uid, States.SCREENSHOT, data)
            await _edit(bot, cid, mid, STEP_SCREENSHOT, back_cancel_kb("back_to_plan"))

        elif d == "submit_confirm":
            await _answer(bot, call, "Submitting…")
            await _do_submit(bot, call, uid, cid, mid)

        elif d == "edit_details":
            await _answer(bot, call)
            _, data = await db.get_session(uid)
            await db.set_session(uid, States.NAME, data)
            await _edit(bot, cid, mid, STEP_NAME, cancel_home_kb())

        elif d.startswith("view_ticket:"):
            ticket_id = d.split(":")[1]
            req = await db.get_request_by_ticket(ticket_id)
            if not req or req["user_id"] != uid:
                await _answer(bot, call, "Ticket not found!")
                return
            await _answer(bot, call)
            await _edit(bot, cid, mid, status_detail(dict(req)), back_home_kb("check_status"))

        # ── ADMIN CALLBACKS ────────────────────────────────────────────────
        elif d == "admin_menu":
            if not await is_admin(uid):
                await _answer(bot, call, "🚫 Not authorised!")
                return
            await _answer(bot, call)
            await _edit(bot, cid, mid,
                "👑 *Admin Panel — Pareeksha Gurukul*\n\nSelect an action:",
                admin_main_menu_kb())

        elif d.startswith("admin_list:"):
            if not await is_admin(uid): return
            _, status, page_str = d.split(":")
            page = int(page_str)
            rows, total = await db.get_requests_by_status(status, page)
            await _answer(bot, call)
            if not rows:
                await _send(bot, cid, f"No {status} requests found.")
                return
            from telebot.types import InlineKeyboardButton
            text = f"📋 *{status} Requests* — Page {page+1}\n{'─'*26}\n\n"
            for r in rows:
                text += f"🎫 `{r['ticket_id']}`\n👤 {r['full_name']} · 📱 {r['mobile']}\n💸 ₹{r['refund_amount']:.0f} · {str(r['submitted_at'])[:16]}\n\n"
            kb = paginate_kb(status, page, total)
            for r in rows:
                kb.add(InlineKeyboardButton(f"📂 {r['ticket_id']}", callback_data=f"req_detail:{r['request_id']}"))
            await _edit(bot, cid, mid, text, kb)

        elif d.startswith("req_detail:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Not found!")
                return
            await _answer(bot, call)
            text = status_detail(dict(req))
            if req["admin_note"]:
                text += f"\n📝 *Note:* {req['admin_note']}"
            await _edit(bot, cid, mid, text, request_detail_kb(request_id, req["status"]))

        elif d.startswith("back_to_req:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Not found!")
                return
            await _answer(bot, call)
            await _edit(bot, cid, mid, admin_request_card(dict(req), req["ticket_id"]), admin_request_kb(request_id))

        elif d.startswith("approve:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            await db.set_session(uid, States.A_UTR, {"request_id": request_id})
            await _answer(bot, call)
            await _send(bot, cid, "✅ *Approve Refund*\n\nEnter the *UTR / Reference Number*:")

        elif d.startswith("confirm_approve:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            _, data = await db.get_session(uid)
            utr = data.get("utr", "")
            if not utr:
                await _answer(bot, call, "UTR missing. Enter it again.")
                return
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Request not found!")
                return
            await db.approve_request(request_id, utr, uid)
            await db.set_session(uid, "idle", {})
            await _answer(bot, call, "✅ Approved!")
            await _edit(bot, cid, mid,
                f"✅ *Refund Approved*\n\nTicket: `{req['ticket_id']}`\nUTR: `{utr}`",
                admin_send_conf_kb(request_id))

        elif d.startswith("decline:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            await db.set_session(uid, States.A_DECLINE_REASON, {"request_id": request_id})
            await _answer(bot, call)
            await _send(bot, cid, "❌ *Decline Refund*\n\nEnter the reason:")

        elif d.startswith("confirm_decline:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            _, data = await db.get_session(uid)
            reason = data.get("reason", "No reason provided")
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Not found!")
                return
            await db.decline_request(request_id, reason, uid)
            await db.set_session(uid, "idle", {})
            await _answer(bot, call, "❌ Declined!")
            try:
                await bot.send_message(req["user_id"], user_declined_msg(reason), parse_mode=PARSE)
            except Exception: pass
            await _edit(bot, cid, mid,
                f"❌ *Declined*\n\nTicket: `{req['ticket_id']}`\nReason: {reason}\n\nUser notified.",
                admin_back_kb())

        elif d.startswith("send_conf:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            req = await db.get_request_by_id(request_id)
            if not req or req["status"] != "Approved":
                await _answer(bot, call, "Not approved yet!")
                return
            try:
                await bot.send_message(req["user_id"], user_approved_msg(req["refund_amount"], req["utr_number"]), parse_mode=PARSE)
                await _answer(bot, call, "✅ User notified!")
            except Exception as e:
                await _answer(bot, call, f"Failed: {e}")
                return
            await _edit(bot, cid, mid, f"✅ Confirmation sent to user.", admin_back_kb())

        elif d.startswith("note:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            await db.set_session(uid, States.A_NOTE, {"request_id": request_id})
            await _answer(bot, call)
            await _send(bot, cid, "📝 Enter your internal note:")

        elif d.startswith("screenshot:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Not found!")
                return
            await _answer(bot, call)
            await bot.send_photo(cid, req["screenshot_file_id"],
                caption=f"📸 Screenshot — `{req['ticket_id']}`", parse_mode=PARSE)

        elif d.startswith("ban:"):
            if not await is_admin(uid): return
            request_id = int(d.split(":")[1])
            req = await db.get_request_by_id(request_id)
            if not req:
                await _answer(bot, call, "Not found!")
                return
            await _answer(bot, call)
            await _edit(bot, cid, mid,
                f"🚫 Ban user `{req['user_id']}`?",
                admin_confirm_ban_kb(req["user_id"], request_id))

        elif d.startswith("confirm_ban:"):
            if not await is_admin(uid): return
            parts = d.split(":")
            ban_uid = int(parts[1])
            request_id = int(parts[2])
            if ban_uid in ADMIN_IDS:
                await _answer(bot, call, "Cannot ban a super-admin!")
                return
            await db.ban_user(ban_uid, uid)
            try:
                await bot.send_message(ban_uid, "🚫 Your account has been restricted.")
            except Exception: pass
            await _answer(bot, call, "User banned!")
            await _edit(bot, cid, mid, f"🚫 User `{ban_uid}` banned.", admin_back_kb())

        elif d == "admin_stats":
            if not await is_admin(uid): return
            stats = await db.get_stats()
            await _answer(bot, call)
            await _edit(bot, cid, mid, admin_stats_card(stats), admin_back_kb())

        elif d == "admin_export":
            if not await is_admin(uid): return
            await _answer(bot, call, "Generating…")
            await _do_export(bot, cid)

        elif d == "admin_plans":
            if not await is_admin(uid): return
            plans = await db.get_all_plans()
            await _answer(bot, call)
            await _edit(bot, cid, mid, "📚 *Manage Plans*", admin_plans_kb(plans))

        elif d.startswith("plan_manage:"):
            if not await is_admin(uid): return
            plan_id = int(d.split(":")[1])
            plan = await db.get_plan(plan_id)
            if not plan:
                await _answer(bot, call, "Not found!")
                return
            text = (f"📚 *{plan['plan_name']}*\n💰 ₹{plan['original_amount']:.0f}  💸 ₹{plan['refund_amount']:.0f}\n"
                    f"{'🟢 Active' if plan['is_active'] else '🔴 Inactive'}")
            await _answer(bot, call)
            await _edit(bot, cid, mid, text, admin_plan_action_kb(plan_id, bool(plan["is_active"])))

        elif d == "plan_add":
            if not await is_admin(uid): return
            await db.set_session(uid, States.A_ADD_PLAN_NAME, {})
            await _answer(bot, call)
            await _send(bot, cid, "➕ *Add New Plan*\n\nEnter plan name:")

        elif d.startswith("plan_edit:"):
            if not await is_admin(uid): return
            plan_id = int(d.split(":")[1])
            await db.set_session(uid, States.A_EDIT_PLAN_NAME, {"plan_id": plan_id})
            await _answer(bot, call)
            await _send(bot, cid, "✏️ Enter new plan name:")

        elif d.startswith("plan_activate:") or d.startswith("plan_deactivate:"):
            if not await is_admin(uid): return
            action, pid_str = d.split(":")
            await db.toggle_plan_active(int(pid_str), action == "plan_activate")
            await _answer(bot, call, "Updated!")
            plans = await db.get_all_plans()
            await _edit(bot, cid, mid, "📚 *Manage Plans*", admin_plans_kb(plans))

        elif d.startswith("plan_delete:"):
            if not await is_admin(uid): return
            await db.delete_plan(int(d.split(":")[1]))
            await _answer(bot, call, "Deleted!")
            plans = await db.get_all_plans()
            await _edit(bot, cid, mid, "📚 *Manage Plans*", admin_plans_kb(plans))

        elif d == "admin_broadcast":
            if not await is_admin(uid): return
            await db.set_session(uid, States.A_BROADCAST, {})
            await _answer(bot, call)
            await _send(bot, cid, "📢 Enter the message to broadcast to all users:")

        elif d == "admin_settings":
            if not await is_admin(uid): return
            await _answer(bot, call)
            await _edit(bot, cid, mid, "⚙️ *Bot Settings*", admin_settings_kb())

        elif d.startswith("setting:"):
            if not await is_admin(uid): return
            key = d.split(":")[1]
            state_map = {
                "welcome_message": (States.A_WELCOME_MSG, "Welcome Message"),
                "support_message": (States.A_SUPPORT_MSG, "Support Message"),
                "working_days":    (States.A_WORKING_DAYS, "Working Days"),
            }
            cfg = state_map.get(key)
            if not cfg: return
            await db.set_session(uid, cfg[0], {"setting_key": key})
            await _answer(bot, call)
            await _send(bot, cid, f"✏️ Enter new *{cfg[1]}*:")

        elif d.startswith("toggle_refund:"):
            if not await is_admin(uid): return
            value = d.split(":")[1]
            await db.set_setting("refund_enabled", value)
            label = "enabled 🔓" if value == "1" else "disabled 🔒"
            await _answer(bot, call, f"Refunds {label}!")
            await _edit(bot, cid, mid, f"⚙️ Refund requests are now *{label}*.", admin_settings_kb())

        elif d == "admin_admins":
            if not await is_admin(uid): return
            admins = await db.get_all_admins()
            await _answer(bot, call)
            await _edit(bot, cid, mid, "👥 *Manage Admins*\n\nTap to remove:", admin_admins_kb(admins))

        elif d == "add_admin":
            if not await is_admin(uid): return
            await db.set_session(uid, States.A_ADD_ADMIN, {})
            await _answer(bot, call)
            await _send(bot, cid, "➕ Enter the Telegram user ID to add as admin:")

        elif d.startswith("remove_admin:"):
            if not await is_admin(uid): return
            admin_id = int(d.split(":")[1])
            if admin_id in ADMIN_IDS:
                await _answer(bot, call, "Cannot remove super-admin!")
                return
            await db.remove_admin(admin_id, uid)
            await _answer(bot, call, "Removed!")
            admins = await db.get_all_admins()
            await _edit(bot, cid, mid, "👥 *Manage Admins*", admin_admins_kb(admins))

        elif d == "admin_search":
            if not await is_admin(uid): return
            await _answer(bot, call)
            await _edit(bot, cid, mid, "🔍 *Search Requests*\n\nSearch by:", search_type_kb())

        elif d.startswith("search:"):
            if not await is_admin(uid): return
            search_type = d.split(":")[1]
            labels = {"ticket": "Ticket ID", "mobile": "Mobile", "name": "Name"}
            await db.set_session(uid, States.A_SEARCH, {"search_type": search_type})
            await _answer(bot, call)
            await _send(bot, cid, f"🔍 Enter {labels.get(search_type, 'query')}:")

        else:
            await _answer(bot, call)
            _log.warning("Unhandled callback: %s", d)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN FSM TEXT HANDLER
# ══════════════════════════════════════════════════════════════════════════════
async def _handle_admin_fsm(bot, msg, uid, state, data):
    cid = msg.chat.id

    if state == States.A_UTR:
        utr = (msg.text or "").strip()
        if not utr:
            await _send(bot, cid, "❗ Enter a valid UTR number.")
            return
        data["utr"] = utr
        request_id = data.get("request_id")
        await db.set_session(uid, "idle", data)
        await _send(bot, cid, f"✅ UTR `{utr}` received.\n\nConfirm to approve?",
                    admin_confirm_approve_kb(request_id))

    elif state == States.A_DECLINE_REASON:
        reason = (msg.text or "").strip()
        if not reason:
            await _send(bot, cid, "❗ Enter a reason.")
            return
        data["reason"] = reason
        request_id = data.get("request_id")
        await db.set_session(uid, "idle", data)
        await _send(bot, cid, f"❌ Reason: _{reason}_\n\nConfirm to decline?",
                    admin_confirm_decline_kb(request_id))

    elif state == States.A_NOTE:
        note = (msg.text or "").strip()
        request_id = data.get("request_id")
        await db.set_admin_note(request_id, note, uid)
        await db.set_session(uid, "idle", {})
        await _send(bot, cid, "📝 Note saved!", admin_back_kb())

    elif state == States.A_BROADCAST:
        text = (msg.text or "").strip()
        if not text:
            await _send(bot, cid, "❗ Message cannot be empty.")
            return
        await db.set_session(uid, "idle", {})
        users = await db.get_all_user_ids()
        prog = await bot.send_message(cid, f"📢 Broadcasting to {len(users)} users…")
        sent, failed = 0, 0
        for user_id in users:
            try:
                await bot.send_message(user_id, text, parse_mode=PARSE)
                sent += 1
            except Exception:
                failed += 1
        try:
            await bot.edit_message_text(
                f"📢 *Broadcast Complete*\n\n✅ Sent: {sent}\n❌ Failed: {failed}",
                cid, prog.message_id, parse_mode=PARSE, reply_markup=admin_back_kb())
        except Exception: pass

    elif state == States.A_SEARCH:
        query = (msg.text or "").strip()
        results = await db.search_requests(query)
        await db.set_session(uid, "idle", {})
        if not results:
            await _send(bot, cid, "🔍 No results found.", admin_back_kb())
            return
        from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
        text = f"🔍 *Results ({len(results)})*\n{'─'*26}\n\n"
        kb = InlineKeyboardMarkup()
        for r in results:
            text += f"🎫 `{r['ticket_id']}` · {r['status']}\n👤 {r['full_name']} · 📱 {r['mobile']}\n\n"
            kb.add(InlineKeyboardButton(f"📂 {r['ticket_id']}", callback_data=f"req_detail:{r['request_id']}"))
        kb.row(InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu"))
        await _send(bot, cid, text, kb)

    elif state == States.A_ADD_PLAN_NAME:
        data["plan_name"] = (msg.text or "").strip()
        await db.set_session(uid, States.A_ADD_PLAN_ORIG, data)
        await _send(bot, cid, f"💰 Enter *original amount* for _{data['plan_name']}_:")

    elif state == States.A_ADD_PLAN_ORIG:
        try:
            data["original_amount"] = float((msg.text or "").strip())
        except ValueError:
            await _send(bot, cid, "❗ Enter a valid number e.g. 499")
            return
        await db.set_session(uid, States.A_ADD_PLAN_REF, data)
        await _send(bot, cid, "💸 Enter *refundable amount*:")

    elif state == States.A_ADD_PLAN_REF:
        try:
            data["refund_amount"] = float((msg.text or "").strip())
        except ValueError:
            await _send(bot, cid, "❗ Enter a valid number.")
            return
        await db.add_plan(data["plan_name"], data["original_amount"], data["refund_amount"])
        await db.set_session(uid, "idle", {})
        await _send(bot, cid,
            f"✅ Plan *{data['plan_name']}* added!\n💰 ₹{data['original_amount']:.0f} → 💸 ₹{data['refund_amount']:.0f}",
            admin_back_kb())

    elif state == States.A_EDIT_PLAN_NAME:
        data["new_name"] = (msg.text or "").strip()
        await db.set_session(uid, States.A_EDIT_PLAN_ORIG, data)
        await _send(bot, cid, "💰 Enter new *original amount*:")

    elif state == States.A_EDIT_PLAN_ORIG:
        try:
            data["original_amount"] = float((msg.text or "").strip())
        except ValueError:
            await _send(bot, cid, "❗ Enter a valid number.")
            return
        await db.set_session(uid, States.A_EDIT_PLAN_REF, data)
        await _send(bot, cid, "💸 Enter new *refundable amount*:")

    elif state == States.A_EDIT_PLAN_REF:
        try:
            data["refund_amount"] = float((msg.text or "").strip())
        except ValueError:
            await _send(bot, cid, "❗ Enter a valid number.")
            return
        plan_id = data.get("plan_id")
        await db.update_plan(plan_id, data["new_name"], data["original_amount"], data["refund_amount"])
        await db.set_session(uid, "idle", {})
        await _send(bot, cid, f"✅ Plan updated to *{data['new_name']}*!", admin_back_kb())

    elif state in (States.A_WELCOME_MSG, States.A_SUPPORT_MSG, States.A_WORKING_DAYS):
        key = data.get("setting_key", "")
        if key:
            await db.set_setting(key, (msg.text or "").strip())
        await db.set_session(uid, "idle", {})
        await _send(bot, cid, "✅ Setting updated!", admin_back_kb())

    elif state == States.A_ADD_ADMIN:
        try:
            new_id = int((msg.text or "").strip())
        except ValueError:
            await _send(bot, cid, "❗ Enter a valid numeric Telegram user ID.")
            return
        await db.add_admin(new_id, "", uid)
        await db.set_session(uid, "idle", {})
        await _send(bot, cid, f"✅ Admin `{new_id}` added!", admin_back_kb())


# ══════════════════════════════════════════════════════════════════════════════
#  USER FLOW HELPERS
# ══════════════════════════════════════════════════════════════════════════════
async def _start_refund(bot, chat_id, user_id, msg_id=None):
    if await db.is_banned(user_id):
        await _send(bot, chat_id, BANNED_MSG)
        return
    if await db.get_setting("refund_enabled") == "0":
        await _edit(bot, chat_id, msg_id, REFUND_DISABLED, main_menu_kb()) if msg_id else await _send(bot, chat_id, REFUND_DISABLED, main_menu_kb())
        return
    if await db.get_active_request_for_user(user_id):
        await _edit(bot, chat_id, msg_id, ALREADY_HAS_REQUEST, main_menu_kb()) if msg_id else await _send(bot, chat_id, ALREADY_HAS_REQUEST, main_menu_kb())
        return
    await db.set_session(user_id, States.NAME, {})
    await _edit(bot, chat_id, msg_id, STEP_NAME, cancel_home_kb()) if msg_id else await _send(bot, chat_id, STEP_NAME, cancel_home_kb())


async def _handle_name(bot, msg, data):
    name = (msg.text or "").strip()
    if len(name) < 3:
        await _send(bot, msg.chat.id, INVALID_NAME, cancel_home_kb())
        return
    data["full_name"] = name
    await db.set_session(msg.from_user.id, States.MOBILE, data)
    await _send(bot, msg.chat.id, STEP_MOBILE, cancel_home_kb())


async def _handle_mobile(bot, msg, data):
    mobile = (msg.text or "").strip()
    if not mobile.isdigit() or len(mobile) != 10:
        await _send(bot, msg.chat.id, INVALID_MOBILE, cancel_home_kb())
        return
    data["mobile"] = mobile
    await db.set_session(msg.from_user.id, States.PLAN, data)
    await _send(bot, msg.chat.id, STEP_PLAN, await plan_selection_kb())


async def _handle_screenshot(bot, msg, data):
    if not msg.photo:
        await _send(bot, msg.chat.id, INVALID_IMAGE, back_cancel_kb("back_to_plan"))
        return
    data["screenshot_file_id"] = msg.photo[-1].file_id
    await db.set_session(msg.from_user.id, States.UPI, data)
    await _send(bot, msg.chat.id, STEP_UPI, cancel_home_kb())


async def _handle_upi(bot, msg, data):
    upi = (msg.text or "").strip()
    if not UPI_PATTERN.match(upi):
        await _send(bot, msg.chat.id, INVALID_UPI, cancel_home_kb())
        return
    data["upi_id"] = upi
    await db.set_session(msg.from_user.id, States.CONFIRM, data)
    await _send(bot, msg.chat.id, confirmation_preview(data), confirm_kb())


async def _do_submit(bot, call, uid, cid, mid):
    _, data = await db.get_session(uid)
    required = ("full_name", "mobile", "plan_id", "upi_id", "screenshot_file_id")
    if not all(k in data for k in required):
        await _send(bot, cid, "⚠️ Session expired. Please start again.", main_menu_kb())
        await db.clear_session(uid)
        return
    if await db.get_active_request_for_user(uid):
        await _edit(bot, cid, mid, ALREADY_HAS_REQUEST, main_menu_kb())
        return
    request_id, ticket_id = await db.create_request(
        user_id=uid, full_name=data["full_name"], mobile=data["mobile"],
        plan_id=data["plan_id"], plan_name=data["plan_name"],
        original_amount=data["original_amount"], refund_amount=data["refund_amount"],
        upi_id=data["upi_id"], screenshot_file_id=data["screenshot_file_id"],
    )
    await db.clear_session(uid)
    await _edit(bot, cid, mid, await submission_success(data["refund_amount"], ticket_id, data.get("original_amount", 0)), main_menu_kb())
    data["user_id"] = uid
    await _notify_admin_group(bot, request_id, data, ticket_id)


async def _show_user_status(bot, chat_id, user_id, msg_id=None):
    requests = await db.get_user_requests(user_id, limit=5)
    if not requests:
        await _edit(bot, chat_id, msg_id, NO_REQUESTS_YET, main_menu_kb()) if msg_id else await _send(bot, chat_id, NO_REQUESTS_YET, main_menu_kb())
        return
    text = "📋 *Your Refund Requests*\n\nTap to view details:"
    kb = status_list_kb(requests)
    await _edit(bot, chat_id, msg_id, text, kb) if msg_id else await _send(bot, chat_id, text, kb)


async def _go_back(bot, chat_id, user_id, state, data, msg_id=None):
    transitions = {
        States.MOBILE:   (States.NAME,       STEP_NAME,       cancel_home_kb()),
        States.PLAN:     (States.MOBILE,     STEP_MOBILE,     cancel_home_kb()),
        States.UPI:      (States.SCREENSHOT, STEP_SCREENSHOT, back_cancel_kb("back_to_plan")),
        States.CONFIRM:  (States.UPI,        STEP_UPI,        cancel_home_kb()),
    }
    if state == States.SCREENSHOT:
        await db.set_session(user_id, States.PLAN, data)
        kb = await plan_selection_kb()
        await _edit(bot, chat_id, msg_id, STEP_PLAN, kb) if msg_id else await _send(bot, chat_id, STEP_PLAN, kb)
        return
    if state not in transitions:
        await db.clear_session(user_id)
        await _edit(bot, chat_id, msg_id, await welcome_text(), main_menu_kb()) if msg_id else await _send(bot, chat_id, await welcome_text(), main_menu_kb())
        return
    new_state, text, kb = transitions[state]
    await db.set_session(user_id, new_state, data)
    await _edit(bot, chat_id, msg_id, text, kb) if msg_id else await _send(bot, chat_id, text, kb)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN GROUP NOTIFICATION
# ══════════════════════════════════════════════════════════════════════════════
async def _notify_admin_group(bot, request_id, data, ticket_id):
    if not ADMIN_GROUP_ID:
        _log.warning("ADMIN_GROUP_ID not set — skipping notification")
        return
    try:
        card_msg = await bot.send_message(
            ADMIN_GROUP_ID, admin_request_card(data, ticket_id),
            parse_mode=PARSE, reply_markup=admin_request_kb(request_id))
        await db.set_admin_msg_id(request_id, card_msg.message_id)
        await bot.send_photo(ADMIN_GROUP_ID, data["screenshot_file_id"],
            caption=f"📸 Screenshot — Ticket `{ticket_id}`", parse_mode=PARSE)
    except Exception as e:
        _log.error("notify_admin_group error: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  EXPORT HELPER
# ══════════════════════════════════════════════════════════════════════════════
async def _do_export(bot, chat_id):
    csv_data = await db.export_csv()
    file_bytes = csv_data.encode("utf-8")
    fname = f"refunds_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    file_obj = io.BytesIO(file_bytes)
    file_obj.name = fname
    await bot.send_document(chat_id, file_obj, caption="📥 *Refund Export*", parse_mode=PARSE)


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    logger.info("=== Pareeksha Gurukul Refund Bot v2 Starting ===")
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

    register_all_handlers(bot)
    logger.info("All handlers registered. ADMIN_IDS=%s", ADMIN_IDS)

    await bot.set_my_commands([
        BotCommand("start",  "Start the bot"),
        BotCommand("refund", "Apply for a refund"),
        BotCommand("status", "Check refund status"),
        BotCommand("help",   "Help & support"),
        BotCommand("cancel", "Cancel current action"),
    ])

    logger.info("=== Bot polling — ready ===")
    await bot.polling(non_stop=True, skip_pending=True, timeout=30, request_timeout=60)


if __name__ == "__main__":
    asyncio.run(main())
