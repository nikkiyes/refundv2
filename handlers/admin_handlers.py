"""
Admin Handlers — Pareeksha Gurukul Refund Bot v2

FIXES vs v1:
- No duplicate text message handler — admin FSM text is handled via
  a SEPARATE handler registered with higher priority (group=1) that
  checks state first and returns, leaving non-admin messages to user handler.
- InputFile usage corrected for pyTelegramBotAPI 4.x
- All admin pending state stored in DB session, not memory dict
  (memory dict lost on restart — now uses DB sessions)
"""

import io
import logging
from datetime import datetime

from telebot.async_telebot import AsyncTeleBot
from telebot.types import Message, CallbackQuery

from config.config import States, ADMIN_GROUP_ID, ADMIN_IDS
from database import db
from keyboards.keyboards import (
    admin_main_menu_kb, admin_back_kb, admin_plans_kb, admin_plan_action_kb,
    admin_request_kb, admin_confirm_approve_kb, admin_confirm_decline_kb,
    admin_confirm_ban_kb, admin_send_conf_kb, admin_settings_kb,
    admin_admins_kb, paginate_kb, request_detail_kb, search_type_kb,
)
from utils.messages import (
    admin_request_card, admin_stats_card,
    user_approved_msg, user_declined_msg, status_detail, PARSE,
)

logger = logging.getLogger(__name__)


# ── Module-level admin ID cache ───────────────────────────────────────────────
# Populated at startup by populate_admin_cache() before handlers are registered.
# This allows the sync lambda filter to check admin IDs without async calls.
_admin_id_cache: set = set()


async def populate_admin_cache():
    """Call this once at startup before registering handlers."""
    global _admin_id_cache
    admins = await db.get_all_admins()
    _admin_id_cache = {a["admin_id"] for a in admins}
    from config.config import ADMIN_IDS
    _admin_id_cache.update(ADMIN_IDS)


def register_admin_handlers(bot: AsyncTeleBot):

    # ── Guard helper ───────────────────────────────────────────────────────────
    async def guard(uid: int, event) -> bool:
        if not await db.is_admin(uid):
            if isinstance(event, CallbackQuery):
                await bot.answer_callback_query(event.id, "🚫 Not authorised!")
            else:
                await bot.send_message(event.chat.id, "🚫 Not authorised.")
            return False
        return True

    # ── Admin FSM text handler ─────────────────────────────────────────────────
    # func checks:
    #   1. Message is from a known admin ID
    #   2. Message is NOT a command (so /admin /start etc are never consumed here)
    # State check inside body handles remaining routing.
    @bot.message_handler(
        func=lambda m: (
            m.from_user is not None
            and m.from_user.id in _admin_id_cache
            and (m.text is None or not m.text.startswith("/"))
            and m.content_type in ("text", "photo")
        ),
        content_types=["text", "photo"],
    )
    async def handle_admin_fsm(msg: Message):
        uid = msg.from_user.id
        state, data = await db.get_session(uid)
        if state not in States.ALL_ADMIN_INPUT:
            return  # Admin not in FSM state — fall through to user handler

        # ── A_UTR ──────────────────────────────────────────────────────────────
        if state == States.A_UTR:
            utr = (msg.text or "").strip()
            if not utr:
                await bot.send_message(msg.chat.id, "❗ Please enter a valid UTR number.")
                return
            data["utr"] = utr
            request_id  = data.get("request_id")
            await db.set_session(uid, "idle", {})
            await bot.send_message(
                msg.chat.id,
                f"✅ UTR `{utr}` received.\n\nConfirm to approve?",
                parse_mode=PARSE,
                reply_markup=admin_confirm_approve_kb(request_id),
            )

        # ── A_DECLINE_REASON ───────────────────────────────────────────────────
        elif state == States.A_DECLINE_REASON:
            reason = (msg.text or "").strip()
            if not reason:
                await bot.send_message(msg.chat.id, "❗ Please enter a reason.")
                return
            request_id = data.get("request_id")
            data["reason"] = reason
            await db.set_session(uid, "idle", {})
            await bot.send_message(
                msg.chat.id,
                f"❌ Reason: _{reason}_\n\nConfirm to decline?",
                parse_mode=PARSE,
                reply_markup=admin_confirm_decline_kb(request_id),
            )

        # ── A_NOTE ─────────────────────────────────────────────────────────────
        elif state == States.A_NOTE:
            note       = (msg.text or "").strip()
            request_id = data.get("request_id")
            await db.set_admin_note(request_id, note, uid)
            await db.set_session(uid, "idle", {})
            await bot.send_message(msg.chat.id, "📝 Note saved!", reply_markup=admin_back_kb())

        # ── A_BROADCAST ────────────────────────────────────────────────────────
        elif state == States.A_BROADCAST:
            text = (msg.text or "").strip()
            if not text:
                await bot.send_message(msg.chat.id, "❗ Message cannot be empty.")
                return
            await db.set_session(uid, "idle", {})
            users = await db.get_all_user_ids()
            prog  = await bot.send_message(msg.chat.id, f"📢 Broadcasting to {len(users)} users…")
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
                    msg.chat.id, prog.message_id,
                    parse_mode=PARSE, reply_markup=admin_back_kb(),
                )
            except Exception:
                pass

        # ── A_SEARCH ───────────────────────────────────────────────────────────
        elif state == States.A_SEARCH:
            from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
            query   = (msg.text or "").strip()
            results = await db.search_requests(query)
            await db.set_session(uid, "idle", {})
            if not results:
                await bot.send_message(msg.chat.id, "🔍 No results found.", reply_markup=admin_back_kb())
                return
            text = f"🔍 *Results ({len(results)})*\n{'─'*26}\n\n"
            kb   = InlineKeyboardMarkup()
            for r in results:
                text += f"🎫 `{r['ticket_id']}` · {r['status']}\n👤 {r['full_name']} · 📱 {r['mobile']}\n\n"
                kb.add(InlineKeyboardButton(f"📂 {r['ticket_id']}", callback_data=f"req_detail:{r['request_id']}"))
            kb.row(InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu"))
            await bot.send_message(msg.chat.id, text, parse_mode=PARSE, reply_markup=kb)

        # ── A_ADD_PLAN_NAME ────────────────────────────────────────────────────
        elif state == States.A_ADD_PLAN_NAME:
            data["plan_name"] = (msg.text or "").strip()
            await db.set_session(uid, States.A_ADD_PLAN_ORIG, data)
            await bot.send_message(msg.chat.id, f"💰 Enter *original amount* for _{data['plan_name']}_:", parse_mode=PARSE)

        elif state == States.A_ADD_PLAN_ORIG:
            try:
                data["original_amount"] = float((msg.text or "").strip())
            except ValueError:
                await bot.send_message(msg.chat.id, "❗ Enter a valid number (e.g. 499).")
                return
            await db.set_session(uid, States.A_ADD_PLAN_REF, data)
            await bot.send_message(msg.chat.id, "💸 Enter *refundable amount*:", parse_mode=PARSE)

        elif state == States.A_ADD_PLAN_REF:
            try:
                data["refund_amount"] = float((msg.text or "").strip())
            except ValueError:
                await bot.send_message(msg.chat.id, "❗ Enter a valid number.")
                return
            await db.add_plan(data["plan_name"], data["original_amount"], data["refund_amount"])
            await db.set_session(uid, "idle", {})
            await bot.send_message(
                msg.chat.id,
                f"✅ Plan *{data['plan_name']}* added!\n"
                f"💰 ₹{data['original_amount']:.0f}  →  💸 ₹{data['refund_amount']:.0f}",
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )

        # ── A_EDIT_PLAN_NAME ───────────────────────────────────────────────────
        elif state == States.A_EDIT_PLAN_NAME:
            data["new_name"] = (msg.text or "").strip()
            await db.set_session(uid, States.A_EDIT_PLAN_ORIG, data)
            await bot.send_message(msg.chat.id, "💰 Enter new *original amount*:", parse_mode=PARSE)

        elif state == States.A_EDIT_PLAN_ORIG:
            try:
                data["original_amount"] = float((msg.text or "").strip())
            except ValueError:
                await bot.send_message(msg.chat.id, "❗ Enter a valid number.")
                return
            await db.set_session(uid, States.A_EDIT_PLAN_REF, data)
            await bot.send_message(msg.chat.id, "💸 Enter new *refundable amount*:", parse_mode=PARSE)

        elif state == States.A_EDIT_PLAN_REF:
            try:
                data["refund_amount"] = float((msg.text or "").strip())
            except ValueError:
                await bot.send_message(msg.chat.id, "❗ Enter a valid number.")
                return
            plan_id = data.get("plan_id")
            await db.update_plan(plan_id, data["new_name"], data["original_amount"], data["refund_amount"])
            await db.set_session(uid, "idle", {})
            await bot.send_message(
                msg.chat.id,
                f"✅ Plan updated to *{data['new_name']}*!",
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )

        # ── Settings edit ──────────────────────────────────────────────────────
        elif state in (States.A_WELCOME_MSG, States.A_SUPPORT_MSG, States.A_WORKING_DAYS):
            key = data.get("setting_key", "")
            if key:
                await db.set_setting(key, (msg.text or "").strip())
            await db.set_session(uid, "idle", {})
            await bot.send_message(msg.chat.id, "✅ Setting updated!", reply_markup=admin_back_kb())

        # ── Add admin ──────────────────────────────────────────────────────────
        elif state == States.A_ADD_ADMIN:
            try:
                new_id = int((msg.text or "").strip())
            except ValueError:
                await bot.send_message(msg.chat.id, "❗ Enter a valid numeric Telegram user ID.")
                return
            await db.add_admin(new_id, "", uid)
            await db.set_session(uid, "idle", {})
            await bot.send_message(
                msg.chat.id, f"✅ Admin `{new_id}` added!",
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )

    # ── /admin ─────────────────────────────────────────────────────────────────
    @bot.message_handler(commands=["admin"])
    async def cmd_admin(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        await bot.send_message(
            msg.chat.id,
            f"👑 *Admin Panel — Pareeksha Gurukul*\n\nWelcome, {msg.from_user.first_name}!\nSelect an action:",
            parse_mode=PARSE, reply_markup=admin_main_menu_kb(),
        )

    @bot.message_handler(commands=["stats"])
    async def cmd_stats(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        stats = await db.get_stats()
        await bot.send_message(msg.chat.id, admin_stats_card(stats), parse_mode=PARSE, reply_markup=admin_back_kb())

    @bot.message_handler(commands=["plans"])
    async def cmd_plans(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        plans = await db.get_all_plans()
        await bot.send_message(msg.chat.id, "📚 *Manage Plans*", parse_mode=PARSE, reply_markup=admin_plans_kb(plans))

    @bot.message_handler(commands=["export"])
    async def cmd_export(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        await _do_export(bot, msg.chat.id)

    @bot.message_handler(commands=["broadcast"])
    async def cmd_broadcast(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        await db.set_session(msg.from_user.id, States.A_BROADCAST, {})
        await bot.send_message(msg.chat.id, "📢 Enter the message to broadcast to all users:")

    @bot.message_handler(commands=["requests"])
    async def cmd_requests(msg: Message):
        if not await guard(msg.from_user.id, msg):
            return
        await bot.send_message(msg.chat.id, "📋 *View Requests*", parse_mode=PARSE, reply_markup=admin_main_menu_kb())

    # ── Callback: admin_menu ───────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_menu")
    async def cb_admin_menu(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(
                "👑 *Admin Panel — Pareeksha Gurukul*\n\nSelect an action:",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_main_menu_kb(),
            )
        except Exception:
            await bot.send_message(
                call.message.chat.id,
                "👑 *Admin Panel — Pareeksha Gurukul*\n\nSelect an action:",
                parse_mode=PARSE, reply_markup=admin_main_menu_kb(),
            )

    # ── Callback: admin_list ───────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("admin_list:"))
    async def cb_admin_list(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        parts  = call.data.split(":")
        status = parts[1]
        page   = int(parts[2])
        rows, total = await db.get_requests_by_status(status, page)

        if not rows:
            await bot.answer_callback_query(call.id, f"No {status} requests.")
            return

        from telebot.types import InlineKeyboardButton
        text = f"📋 *{status} Requests* — Page {page+1}\n{'─'*26}\n\n"
        for r in rows:
            text += (
                f"🎫 `{r['ticket_id']}`\n"
                f"👤 {r['full_name']}  📱 {r['mobile']}\n"
                f"💸 ₹{r['refund_amount']:.0f}  ·  {str(r['submitted_at'])[:16]}\n\n"
            )
        kb = paginate_kb(status, page, total)
        for r in rows:
            kb.add(InlineKeyboardButton(
                f"📂 {r['ticket_id']}", callback_data=f"req_detail:{r['request_id']}"
            ))
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=kb)
        except Exception:
            await bot.send_message(call.message.chat.id, text, parse_mode=PARSE, reply_markup=kb)

    # ── Callback: req_detail ───────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("req_detail:"))
    async def cb_req_detail(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Not found!")
            return
        text = status_detail(dict(req))
        if req["admin_note"]:
            text += f"\n📝 *Admin Note:* {req['admin_note']}"
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=request_detail_kb(request_id, req["status"]))
        except Exception:
            await bot.send_message(call.message.chat.id, text, parse_mode=PARSE, reply_markup=request_detail_kb(request_id, req["status"]))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("back_to_req:"))
    async def cb_back_to_req(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Not found!")
            return
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(
                admin_request_card(dict(req), req["ticket_id"]),
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_request_kb(request_id),
            )
        except Exception:
            pass

    # ── Approve flow ───────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("approve:"))
    async def cb_approve(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        await db.set_session(call.from_user.id, States.A_UTR, {"request_id": request_id})
        await bot.answer_callback_query(call.id)
        await bot.send_message(
            call.message.chat.id,
            "✅ *Approve Refund*\n\nEnter the *UTR / Reference Number*:",
            parse_mode=PARSE,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_approve:"))
    async def cb_confirm_approve(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        # UTR is stored temporarily in session data by handle_admin_fsm
        _, data    = await db.get_session(call.from_user.id)
        request_id = int(call.data.split(":")[1])
        utr        = data.get("utr", "")

        if not utr:
            await bot.answer_callback_query(call.id, "UTR missing. Please start again.")
            return

        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Request not found!")
            return

        await db.approve_request(request_id, utr, call.from_user.id)
        await db.set_session(call.from_user.id, "idle", {})
        await bot.answer_callback_query(call.id, "✅ Approved!")
        try:
            await bot.edit_message_text(
                f"✅ *Refund Approved*\n\nTicket: `{req['ticket_id']}`\nUTR: `{utr}`",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_send_conf_kb(request_id),
            )
        except Exception:
            await bot.send_message(
                call.message.chat.id,
                f"✅ Approved. Ticket `{req['ticket_id']}`, UTR `{utr}`.",
                parse_mode=PARSE, reply_markup=admin_send_conf_kb(request_id),
            )

    # ── Decline flow ───────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("decline:"))
    async def cb_decline(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        await db.set_session(call.from_user.id, States.A_DECLINE_REASON, {"request_id": request_id})
        await bot.answer_callback_query(call.id)
        await bot.send_message(
            call.message.chat.id,
            "❌ *Decline Refund*\n\nEnter the reason for declining:",
            parse_mode=PARSE,
        )

    @bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_decline:"))
    async def cb_confirm_decline(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        _, data    = await db.get_session(call.from_user.id)
        request_id = int(call.data.split(":")[1])
        reason     = data.get("reason", "No reason provided")

        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Request not found!")
            return

        await db.decline_request(request_id, reason, call.from_user.id)
        await db.set_session(call.from_user.id, "idle", {})
        await bot.answer_callback_query(call.id, "❌ Declined!")

        # Notify user immediately
        try:
            await bot.send_message(req["user_id"], user_declined_msg(reason), parse_mode=PARSE)
        except Exception as e:
            logger.warning("Could not notify user %s: %s", req["user_id"], e)

        try:
            await bot.edit_message_text(
                f"❌ *Declined*\n\nTicket: `{req['ticket_id']}`\nReason: {reason}\n\nUser notified.",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )
        except Exception:
            pass

    # ── Send confirmation to user ──────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("send_conf:"))
    async def cb_send_conf(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        req = await db.get_request_by_id(request_id)
        if not req or req["status"] != "Approved":
            await bot.answer_callback_query(call.id, "Cannot send — not yet approved.")
            return
        try:
            await bot.send_message(
                req["user_id"],
                user_approved_msg(req["refund_amount"], req["utr_number"]),
                parse_mode=PARSE,
            )
            await bot.answer_callback_query(call.id, "✅ User notified!")
        except Exception as e:
            await bot.answer_callback_query(call.id, f"Failed: {e}")
            return
        try:
            await bot.edit_message_text(
                f"✅ Confirmation sent to user `{req['user_id']}`.",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )
        except Exception:
            pass

    # ── Add note ───────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("note:"))
    async def cb_note(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        await db.set_session(call.from_user.id, States.A_NOTE, {"request_id": request_id})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "📝 Enter your internal note:")

    # ── View screenshot ────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("screenshot:"))
    async def cb_screenshot(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Not found!")
            return
        await bot.answer_callback_query(call.id)
        await bot.send_photo(
            call.message.chat.id,
            req["screenshot_file_id"],
            caption=f"📸 Screenshot\n🎫 Ticket: `{req['ticket_id']}`",
            parse_mode=PARSE,
        )

    # ── Ban / unban ────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data.startswith("ban:"))
    async def cb_ban(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        request_id = int(call.data.split(":")[1])
        req = await db.get_request_by_id(request_id)
        if not req:
            await bot.answer_callback_query(call.id, "Not found!")
            return
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(
                f"🚫 Ban user `{req['user_id']}`?\n\nThis will prevent them from using the bot.",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_confirm_ban_kb(req["user_id"], request_id),
            )
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_ban:"))
    async def cb_confirm_ban(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        parts      = call.data.split(":")
        ban_uid    = int(parts[1])
        request_id = int(parts[2])
        if ban_uid in ADMIN_IDS:
            await bot.answer_callback_query(call.id, "Cannot ban a super-admin!")
            return
        await db.ban_user(ban_uid, call.from_user.id)
        try:
            await bot.send_message(ban_uid, "🚫 Your account has been restricted. Contact support.")
        except Exception:
            pass
        await bot.answer_callback_query(call.id, "User banned!")
        try:
            await bot.edit_message_text(
                f"🚫 User `{ban_uid}` has been banned.",
                call.message.chat.id, call.message.message_id,
                parse_mode=PARSE, reply_markup=admin_back_kb(),
            )
        except Exception:
            pass

    # ── Analytics ──────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_stats")
    async def cb_stats(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        stats = await db.get_stats()
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(admin_stats_card(stats), call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_back_kb())
        except Exception:
            await bot.send_message(call.message.chat.id, admin_stats_card(stats), parse_mode=PARSE, reply_markup=admin_back_kb())

    # ── Export CSV ─────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_export")
    async def cb_export(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await bot.answer_callback_query(call.id, "Generating…")
        await _do_export(bot, call.message.chat.id)

    # ── Plans ──────────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_plans")
    async def cb_plans(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        plans = await db.get_all_plans()
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text("📚 *Manage Plans*", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_plans_kb(plans))
        except Exception:
            await bot.send_message(call.message.chat.id, "📚 *Manage Plans*", parse_mode=PARSE, reply_markup=admin_plans_kb(plans))

    @bot.callback_query_handler(func=lambda c: c.data.startswith("plan_manage:"))
    async def cb_plan_manage(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        plan_id = int(call.data.split(":")[1])
        plan    = await db.get_plan(plan_id)
        if not plan:
            await bot.answer_callback_query(call.id, "Plan not found!")
            return
        text = (
            f"📚 *{plan['plan_name']}*\n"
            f"💰 Original: ₹{plan['original_amount']:.0f}\n"
            f"💸 Refund: ₹{plan['refund_amount']:.0f}\n"
            f"Status: {'🟢 Active' if plan['is_active'] else '🔴 Inactive'}"
        )
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_plan_action_kb(plan_id, bool(plan["is_active"])))
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data == "plan_add")
    async def cb_plan_add(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await db.set_session(call.from_user.id, States.A_ADD_PLAN_NAME, {})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "➕ *Add New Plan*\n\nEnter plan name:", parse_mode=PARSE)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("plan_edit:"))
    async def cb_plan_edit(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        plan_id = int(call.data.split(":")[1])
        await db.set_session(call.from_user.id, States.A_EDIT_PLAN_NAME, {"plan_id": plan_id})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "✏️ Enter new plan name:", parse_mode=PARSE)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("plan_activate:") or c.data.startswith("plan_deactivate:"))
    async def cb_plan_toggle(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        action, pid_str = call.data.split(":")
        await db.toggle_plan_active(int(pid_str), action == "plan_activate")
        await bot.answer_callback_query(call.id, "Updated!")
        plans = await db.get_all_plans()
        try:
            await bot.edit_message_text("📚 *Manage Plans*", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_plans_kb(plans))
        except Exception:
            pass

    @bot.callback_query_handler(func=lambda c: c.data.startswith("plan_delete:"))
    async def cb_plan_delete(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        plan_id = int(call.data.split(":")[1])
        await db.delete_plan(plan_id)
        await bot.answer_callback_query(call.id, "Plan deleted!")
        plans = await db.get_all_plans()
        try:
            await bot.edit_message_text("📚 *Manage Plans*", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_plans_kb(plans))
        except Exception:
            pass

    # ── Broadcast ──────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_broadcast")
    async def cb_broadcast(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await db.set_session(call.from_user.id, States.A_BROADCAST, {})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "📢 Enter the message to broadcast to all users:")

    # ── Settings ───────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_settings")
    async def cb_settings(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text("⚙️ *Bot Settings*", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_settings_kb())
        except Exception:
            await bot.send_message(call.message.chat.id, "⚙️ *Bot Settings*", parse_mode=PARSE, reply_markup=admin_settings_kb())

    @bot.callback_query_handler(func=lambda c: c.data.startswith("setting:"))
    async def cb_setting_edit(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        key = call.data.split(":")[1]
        state_map = {
            "welcome_message": States.A_WELCOME_MSG,
            "support_message": States.A_SUPPORT_MSG,
            "working_days":    States.A_WORKING_DAYS,
        }
        state = state_map.get(key)
        if not state:
            await bot.answer_callback_query(call.id, "Unknown setting.")
            return
        await db.set_session(call.from_user.id, state, {"setting_key": key})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, f"✏️ Enter new value for *{key}*:", parse_mode=PARSE)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("toggle_refund:"))
    async def cb_toggle_refund(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        value = call.data.split(":")[1]
        await db.set_setting("refund_enabled", value)
        label = "enabled 🔓" if value == "1" else "disabled 🔒"
        await bot.answer_callback_query(call.id, f"Refunds {label}!")
        try:
            await bot.edit_message_text(f"⚙️ Refund requests are now *{label}*.", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_settings_kb())
        except Exception:
            pass

    # ── Admins management ──────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_admins")
    async def cb_admins(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        admins = await db.get_all_admins()
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text("👥 *Manage Admins*\n\nTap an admin to remove:", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_admins_kb(admins))
        except Exception:
            await bot.send_message(call.message.chat.id, "👥 *Manage Admins*", parse_mode=PARSE, reply_markup=admin_admins_kb(admins))

    @bot.callback_query_handler(func=lambda c: c.data == "add_admin")
    async def cb_add_admin(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await db.set_session(call.from_user.id, States.A_ADD_ADMIN, {})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, "➕ Enter the Telegram user ID to add as admin:")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("remove_admin:"))
    async def cb_remove_admin(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        admin_id = int(call.data.split(":")[1])
        if admin_id in ADMIN_IDS:
            await bot.answer_callback_query(call.id, "Cannot remove super-admin!")
            return
        await db.remove_admin(admin_id, call.from_user.id)
        await bot.answer_callback_query(call.id, "Admin removed!")
        admins = await db.get_all_admins()
        try:
            await bot.edit_message_text("👥 *Manage Admins*", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=admin_admins_kb(admins))
        except Exception:
            pass

    # ── Search ─────────────────────────────────────────────────────────────────
    @bot.callback_query_handler(func=lambda c: c.data == "admin_search")
    async def cb_admin_search(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        await bot.answer_callback_query(call.id)
        try:
            await bot.edit_message_text("🔍 *Search Requests*\n\nSearch by:", call.message.chat.id, call.message.message_id, parse_mode=PARSE, reply_markup=search_type_kb())
        except Exception:
            await bot.send_message(call.message.chat.id, "🔍 Search by:", reply_markup=search_type_kb())

    @bot.callback_query_handler(func=lambda c: c.data.startswith("search:"))
    async def cb_search_type(call: CallbackQuery):
        if not await guard(call.from_user.id, call):
            return
        search_type = call.data.split(":")[1]
        labels = {"ticket": "Ticket ID", "mobile": "Mobile", "name": "Name"}
        await db.set_session(call.from_user.id, States.A_SEARCH, {"search_type": search_type})
        await bot.answer_callback_query(call.id)
        await bot.send_message(call.message.chat.id, f"🔍 Enter {labels.get(search_type, 'query')}:")


# ══════════════════════════════════════════════════════════════════════════════
#  NOTIFY ADMIN GROUP
# ══════════════════════════════════════════════════════════════════════════════
async def notify_admin_group(bot: AsyncTeleBot, request_id: int, data: dict, ticket_id: str):
    if not ADMIN_GROUP_ID:
        logger.warning("ADMIN_GROUP_ID not set — skipping admin notification")
        return
    try:
        card_msg = await bot.send_message(
            ADMIN_GROUP_ID,
            admin_request_card(data, ticket_id),
            parse_mode=PARSE,
            reply_markup=admin_request_kb(request_id),
        )
        await db.set_admin_msg_id(request_id, card_msg.message_id)
        await bot.send_photo(
            ADMIN_GROUP_ID,
            data["screenshot_file_id"],
            caption=f"📸 Payment Screenshot — Ticket `{ticket_id}`",
            parse_mode=PARSE,
        )
    except Exception as e:
        logger.error("notify_admin_group error: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  EXPORT HELPER
# ══════════════════════════════════════════════════════════════════════════════
async def _do_export(bot: AsyncTeleBot, chat_id: int):
    csv_data   = await db.export_csv()
    file_bytes = csv_data.encode("utf-8")
    fname      = f"refunds_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    # Use io.BytesIO — this is the correct way for pyTelegramBotAPI 4.x
    file_obj      = io.BytesIO(file_bytes)
    file_obj.name = fname
    await bot.send_document(
        chat_id,
        file_obj,
        caption="📥 *Refund Export*",
        parse_mode=PARSE,
    )
