"""
Message Templates — Pareeksha Gurukul Refund Bot v2
All text is here — change messages without touching logic.
"""

from database.db import get_setting

PARSE = "Markdown"


# ── Welcome ────────────────────────────────────────────────────────────────────
async def welcome_text() -> str:
    custom = await get_setting("welcome_message")
    return custom or (
        "Welcome to *Pareeksha Gurukul Refund Support* 🎓\n\n"
        "We are here to help you with your refund request.\n\n"
        "Please select an option below:"
    )


# ── User Flow ──────────────────────────────────────────────────────────────────
STEP_NAME = (
    "📝 *Step 1 / 5 — Full Name*\n\n"
    "Please enter your *full name* as registered in our app.\n\n"
    "_Minimum 3 characters._"
)

STEP_MOBILE = (
    "📱 *Step 2 / 5 — Mobile Number*\n\n"
    "Enter your *registered 10-digit mobile number*."
)

STEP_PLAN = (
    "📚 *Step 3 / 5 — Select Your Plan*\n\n"
    "Tap the plan you purchased:"
)

STEP_SCREENSHOT = (
    "📸 *Step 4 / 5 — Payment Screenshot*\n\n"
    "Upload your *payment screenshot* as proof.\n\n"
    "_Send as a photo, not a file._"
)

STEP_UPI = (
    "💳 *Step 5 / 5 — UPI ID*\n\n"
    "Enter your UPI ID where the refund should be sent.\n\n"
    "_Examples:_ `name@paytm` · `9876543210@ybl` · `user@okicici`"
)

INVALID_NAME       = "❗ *Invalid Name*\n\nPlease enter at least 3 characters."
INVALID_MOBILE     = "❗ *Invalid Mobile*\n\nPlease enter a valid 10-digit number."
INVALID_UPI        = "❗ *Invalid UPI ID*\n\nExample: `name@paytm` or `9876543210@ybl`"
INVALID_IMAGE      = "❗ *Invalid File*\n\nPlease send your screenshot as a *photo*."

CANCELLED = (
    "🚫 *Cancelled*\n\n"
    "Your request has been cancelled.\n"
    "Tap below to return to the main menu."
)

ALREADY_HAS_REQUEST = (
    "⚠️ *Active Request Exists*\n\n"
    "You already have a refund request being processed.\n"
    "Please wait for it to be resolved before submitting a new one.\n\n"
    "Use *Check Refund Status* to view it."
)

REFUND_DISABLED = (
    "🔒 *Refund Requests Temporarily Disabled*\n\n"
    "We are not accepting refund requests at this time.\n"
    "Please try again later or contact support."
)

BANNED_MSG = (
    "🚫 *Account Restricted*\n\n"
    "Your account has been flagged.\n"
    "Contact support for help."
)

HELP_TEXT = (
    "🆘 *Pareeksha Gurukul Refund Help*\n"
    "─────────────────────────────\n\n"
    "*How to apply for a refund?*\n"
    "Tap *Apply for Refund* and follow the 5 steps.\n\n"
    "*How to check status?*\n"
    "Tap *Check Refund Status* from the main menu.\n\n"
    "*When will I receive the refund?*\n"
    "Within 7 working days after approval.\n\n"
    "*Note:* Platform charges and GST will be deducted."
)

NO_REQUESTS_YET = (
    "📋 *No Requests Found*\n\n"
    "You haven't submitted any refund request yet."
)


def get_breakdown(original_amount: float, refund_amount: float) -> dict:
    """
    Calculate deduction breakdown from original and refund amounts.
    Deduction ratio is derived from the 499 plan as the reference:
      Total deduction = original - refund
      Platform charge = deduction / 1.18 / 1.156  (reverse GST + gateway)
      GST = platform_charge * 0.18
      Gateway = deduction - platform_charge - gst
    """
    total_deduction    = original_amount - refund_amount
    # Back-calculate platform charge (it drives GST and gateway fee)
    # From 499 plan: platform=220, gst=39.60, gateway=34.40, total=294
    # platform / total_deduction = 220/294 = 0.7483
    platform_charge    = round(total_deduction * (220 / 294), 2)
    gst                = round(platform_charge * 0.18, 2)
    gateway_fee        = round(total_deduction - platform_charge - gst, 2)
    return {
        "total_amount":    original_amount,
        "platform_charge": platform_charge,
        "gst":             gst,
        "gateway_fee":     gateway_fee,
        "total_deduction": total_deduction,
        "refund_amount":   refund_amount,
    }


def breakdown_text(original_amount: float, refund_amount: float) -> str:
    b = get_breakdown(original_amount, refund_amount)
    lines = [
        f"💰 *Total Amount:* ₹{b['total_amount']:.0f}",
        f"🏢 *Platform Charge:* ₹{b['platform_charge']:.2f}",
        f"📊 *GST on Platform Charge (18%):* ₹{b['gst']:.2f}",
        f"💳 *Payment Gateway & Processing Fee:* ₹{b['gateway_fee']:.2f}",
        f"➖ *Total Deduction:* ₹{b['total_deduction']:.0f}",
        f"✅ *Final Refund Amount:* ₹{b['refund_amount']:.0f}",
    ]
    return "\n".join(lines)


def confirmation_preview(d: dict) -> str:
    return (
        "✅ *Review Your Refund Request*\n"
        "─────────────────────────────\n"
        f"👤 *Name:* {d['full_name']}\n"
        f"📱 *Mobile:* {d['mobile']}\n"
        f"📚 *Plan:* {d['plan_name']}\n"
        f"💳 *UPI ID:* `{d['upi_id']}`\n"
        "─────────────────────────────\n"
        "*💸 Refund Breakdown:*\n"
        f"{breakdown_text(d['original_amount'], d['refund_amount'])}\n"
        "─────────────────────────────\n\n"
        "Please confirm to submit."
    )


async def submission_success(refund_amount: float, ticket_id: str, original_amount: float = 0) -> str:
    days   = await get_setting("working_days") or "7"
    footer = await get_setting("footer_message") or "Thank you,\nPareeksha Gurukul Support Team 🎓"
    bkd = breakdown_text(original_amount, refund_amount) if original_amount else f"✅ *Final Refund Amount:* ₹{refund_amount:.0f}"
    return (
        "🎉 *Request Submitted Successfully!*\n"
        "─────────────────────────────\n\n"
        "Your refund request has been received.\n\n"
        f"🎫 *Ticket ID:* `{ticket_id}`\n\n"
        "Our team will verify your payment details.\n\n"
        "💸 *Deduction Breakdown:*\n"
        f"{bkd}\n\n"
        f"⏱ Amount credited within *{days} working days* after approval.\n\n"
        "─────────────────────────────\n"
        f"{footer}"
    )



def user_approved_msg(refund_amount: float, utr: str) -> str:
    return (
        "✅ *Refund Processed Successfully!*\n"
        "─────────────────────────────\n\n"
        "Your refund request has been *approved*.\n\n"
        f"💰 *Refund Amount:* ₹{refund_amount:.0f}\n"
        f"🔖 *UTR / Reference:* `{utr}`\n\n"
        "The amount may take a few hours to reflect.\n\n"
        "─────────────────────────────\n"
        "Thank you,\nPareeksha Gurukul Support Team 🎓"
    )


def user_declined_msg(reason: str) -> str:
    return (
        "❌ *Refund Request Declined*\n"
        "─────────────────────────────\n\n"
        "Your refund request has been *declined*.\n\n"
        f"📋 *Reason:*\n{reason}\n\n"
        "For further support, please contact our team.\n\n"
        "─────────────────────────────\n"
        "Thank you,\nPareeksha Gurukul Support Team 🎓"
    )


def status_detail(r: dict) -> str:
    icon = {"Pending": "⏳", "Approved": "✅", "Declined": "❌", "Processing": "🔄"}.get(r["status"], "📋")
    text = (
        "📋 *Refund Request Details*\n"
        "─────────────────────────────\n"
        f"🎫 *Ticket ID:* `{r['ticket_id']}`\n"
        f"📊 *Status:* {icon} {r['status']}\n"
        f"👤 *Name:* {r['full_name']}\n"
        f"📚 *Plan:* {r['plan_name']}\n"
        f"💰 *Original:* ₹{r['original_amount']:.0f}\n"
        f"💸 *Refund:* ₹{r['refund_amount']:.0f}\n"
        f"💳 *UPI:* `{r['upi_id']}`\n"
        f"🕐 *Submitted:* {r['submitted_at']}\n"
    )
    if r.get("status") == "Approved" and r.get("utr_number"):
        text += f"🔖 *UTR:* `{r['utr_number']}`\n"
        text += f"✅ *Processed:* {r['processed_at']}\n"
    elif r.get("status") == "Declined" and r.get("admin_remarks"):
        text += f"📝 *Reason:* {r['admin_remarks']}\n"
    return text


# ── Admin ──────────────────────────────────────────────────────────────────────
def admin_request_card(d: dict, ticket_id: str) -> str:
    return (
        "🆕 *New Refund Request*\n"
        "══════════════════════════════\n\n"
        f"🎫 *Ticket ID:* `{ticket_id}`\n"
        f"👤 *Name:* {d['full_name']}\n"
        f"📱 *Mobile:* `{d['mobile']}`\n"
        f"📚 *Plan:* {d['plan_name']}\n"
        f"💰 *Original:* ₹{d['original_amount']:.0f}\n"
        f"💸 *Refund:* ₹{d['refund_amount']:.0f}\n"
        f"💳 *UPI:* `{d['upi_id']}`\n"
        f"🆔 *User ID:* `{d['user_id']}`\n"
        "──────────────────────────────\n"
        "⏳ *Status:* Pending Review"
    )


def admin_stats_card(s: dict) -> str:
    total = sum(s[x]["total"] for x in ("Pending", "Approved", "Declined", "Processing"))
    return (
        "📊 *Refund Analytics Dashboard*\n"
        "══════════════════════════════\n\n"
        f"⏳ *Pending:*    {s['Pending']['count']} requests · ₹{s['Pending']['total']:.0f}\n"
        f"✅ *Approved:*   {s['Approved']['count']} requests · ₹{s['Approved']['total']:.0f}\n"
        f"❌ *Declined:*   {s['Declined']['count']} requests · ₹{s['Declined']['total']:.0f}\n"
        f"🔄 *Processing:* {s['Processing']['count']} requests · ₹{s['Processing']['total']:.0f}\n"
        "──────────────────────────────\n"
        f"💰 *Total Refund Value:* ₹{total:.0f}\n"
        f"👥 *Total Users:*  {s['users']}\n"
        f"📚 *Active Plans:* {s['plans']}\n"
    )
