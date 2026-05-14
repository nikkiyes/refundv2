"""
Keyboard Builders — Pareeksha Gurukul Refund Bot v2
Every InlineKeyboardMarkup is built here.
"""

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from database.db import get_active_plans


# ── Quick helpers ──────────────────────────────────────────────────────────────
def _ik(*rows):
    """Build InlineKeyboardMarkup from rows of (text, cb_data) tuples."""
    kb = InlineKeyboardMarkup()
    for row in rows:
        kb.row(*[InlineKeyboardButton(t, callback_data=c) for t, c in row])
    return kb


# ══════════════════════════════════════════════════════════════════════════════
#  USER KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════
def main_menu_kb():
    return _ik(
        [("💸 Apply for Refund",    "refund_start")],
        [("🔍 Check Refund Status", "check_status")],
        [("🆘 Help & Support",      "help")],
    )


def cancel_home_kb():
    return _ik(
        [("❌ Cancel", "cancel"), ("🏠 Home", "home")],
    )


def back_cancel_kb(back_cb="back"):
    return _ik(
        [("🔙 Back", back_cb), ("❌ Cancel", "cancel")],
        [("🏠 Home", "home")],
    )


def back_home_kb(back_cb="back"):
    return _ik(
        [("🔙 Back", back_cb), ("🏠 Home", "home")],
    )


def confirm_kb():
    return _ik(
        [("✅ Confirm & Submit", "submit_confirm")],
        [("✏️ Edit Details",     "edit_details"), ("❌ Cancel", "cancel")],
    )


async def plan_selection_kb():
    plans = await get_active_plans()
    kb = InlineKeyboardMarkup()
    for p in plans:
        kb.add(InlineKeyboardButton(
            f"📚 {p['plan_name']}  —  ₹{p['original_amount']:.0f}",
            callback_data=f"plan:{p['plan_id']}",
        ))
    kb.row(
        InlineKeyboardButton("🔙 Back",   callback_data="back"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel"),
    )
    return kb


def status_list_kb(requests):
    icons = {"Pending": "⏳", "Approved": "✅", "Declined": "❌", "Processing": "🔄"}
    kb = InlineKeyboardMarkup()
    for r in requests[:5]:
        icon = icons.get(r["status"], "📋")
        kb.add(InlineKeyboardButton(
            f"{icon} {r['ticket_id']}  —  {r['status']}",
            callback_data=f"view_ticket:{r['ticket_id']}",
        ))
    kb.row(InlineKeyboardButton("🏠 Home", callback_data="home"))
    return kb


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — REQUEST ACTIONS
# ══════════════════════════════════════════════════════════════════════════════
def admin_request_kb(request_id: int):
    rid = str(request_id)
    return _ik(
        [("✅ Approve Refund",  f"approve:{rid}"),
         ("❌ Decline Refund", f"decline:{rid}")],
        [("📝 Add Note",       f"note:{rid}"),
         ("🚫 Ban User",       f"ban:{rid}")],
        [("🖼 View Screenshot", f"screenshot:{rid}")],
    )


def admin_confirm_approve_kb(request_id: int):
    rid = str(request_id)
    return _ik(
        [("✅ Yes, Approve", f"confirm_approve:{rid}"),
         ("🔙 Back",         f"back_to_req:{rid}")],
    )


def admin_confirm_decline_kb(request_id: int):
    rid = str(request_id)
    return _ik(
        [("❌ Yes, Decline", f"confirm_decline:{rid}"),
         ("🔙 Back",         f"back_to_req:{rid}")],
    )


def admin_confirm_ban_kb(user_id: int, request_id: int):
    return _ik(
        [("🚫 Yes, Ban",  f"confirm_ban:{user_id}:{request_id}"),
         ("🔙 Cancel",    f"back_to_req:{request_id}")],
    )


def admin_send_conf_kb(request_id: int):
    return _ik(
        [("📤 Send Confirmation to User", f"send_conf:{request_id}")],
        [("🔙 Admin Menu", "admin_menu")],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════
def admin_main_menu_kb():
    return _ik(
        [("⏳ Pending",    "admin_list:Pending:0"),
         ("✅ Approved",   "admin_list:Approved:0")],
        [("❌ Declined",   "admin_list:Declined:0"),
         ("🔄 Processing", "admin_list:Processing:0")],
        [("📚 Manage Plans",   "admin_plans")],
        [("📊 Analytics",      "admin_stats"),
         ("📢 Broadcast",      "admin_broadcast")],
        [("📥 Export CSV",     "admin_export"),
         ("⚙️ Settings",       "admin_settings")],
        [("👥 Manage Admins",  "admin_admins")],
        [("🔍 Search Request", "admin_search")],
    )


def admin_back_kb():
    return _ik([("🔙 Admin Menu", "admin_menu")])


def admin_plans_kb(plans):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Add New Plan", callback_data="plan_add"))
    for p in plans:
        dot = "🟢" if p["is_active"] else "🔴"
        kb.add(InlineKeyboardButton(
            f"{dot} {p['plan_name']}  ₹{p['original_amount']:.0f} → ₹{p['refund_amount']:.0f}",
            callback_data=f"plan_manage:{p['plan_id']}",
        ))
    kb.row(InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu"))
    return kb


def admin_plan_action_kb(plan_id: int, is_active: bool):
    pid = str(plan_id)
    tog_label = "🔴 Deactivate" if is_active else "🟢 Activate"
    tog_cb    = f"plan_deactivate:{pid}" if is_active else f"plan_activate:{pid}"
    return _ik(
        [("✏️ Edit",   f"plan_edit:{pid}"), (tog_label, tog_cb)],
        [("🗑️ Delete", f"plan_delete:{pid}")],
        [("🔙 Plans",  "admin_plans")],
    )


def admin_settings_kb():
    return _ik(
        [("📝 Welcome Message",  "setting:welcome_message"),
         ("🆘 Support Message",  "setting:support_message")],
        [("📅 Working Days",     "setting:working_days")],
        [("🔓 Enable Refunds",   "toggle_refund:1"),
         ("🔒 Disable Refunds",  "toggle_refund:0")],
        [("🔙 Admin Menu",       "admin_menu")],
    )


def admin_admins_kb(admins):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Add Admin", callback_data="add_admin"))
    for a in admins:
        label = f"👤 {a['username'] or a['admin_id']}"
        kb.add(InlineKeyboardButton(label, callback_data=f"remove_admin:{a['admin_id']}"))
    kb.row(InlineKeyboardButton("🔙 Admin Menu", callback_data="admin_menu"))
    return kb


def paginate_kb(status: str, page: int, total: int, per_page: int = 5):
    kb = InlineKeyboardMarkup()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_list:{status}:{page-1}"))
    if (page + 1) * per_page < total:
        nav.append(InlineKeyboardButton("➡️ Next", callback_data=f"admin_list:{status}:{page+1}"))
    if nav:
        kb.row(*nav)
    kb.row(
        InlineKeyboardButton("🔄 Refresh",   callback_data=f"admin_list:{status}:{page}"),
        InlineKeyboardButton("🔙 Menu",      callback_data="admin_menu"),
    )
    return kb


def request_detail_kb(request_id: int, status: str):
    kb = InlineKeyboardMarkup()
    rid = str(request_id)
    if status == "Pending":
        kb.row(
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{rid}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"decline:{rid}"),
        )
    kb.row(
        InlineKeyboardButton("📝 Note",       callback_data=f"note:{rid}"),
        InlineKeyboardButton("🖼 Screenshot", callback_data=f"screenshot:{rid}"),
    )
    kb.row(InlineKeyboardButton("🔙 Back", callback_data="admin_menu"))
    return kb


def search_type_kb():
    return _ik(
        [("🎫 Ticket ID",  "search:ticket"),
         ("📱 Mobile",     "search:mobile")],
        [("👤 Name",       "search:name")],
        [("🔙 Admin Menu", "admin_menu")],
    )
