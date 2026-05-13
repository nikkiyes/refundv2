"""
Configuration — Pareeksha Gurukul Refund Bot v2
All environment variables, constants, and FSM state keys.
"""

import os
import re
from dotenv import load_dotenv

load_dotenv()

# ── Bot ────────────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# ── Admins ────────────────────────────────────────────────────────────────────
_raw = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list = [int(x.strip()) for x in _raw.split(",") if x.strip().isdigit()]

# Telegram group/channel for forwarding refund requests
ADMIN_GROUP_ID: int = int(os.getenv("ADMIN_GROUP_ID", "0"))

# ── Database ──────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "data/pg_refund.db")

# ── App metadata ──────────────────────────────────────────────────────────────
SUPPORT_CONTACT: str = os.getenv("SUPPORT_CONTACT", "@PareekshaGurukul")

# ── UPI validation ────────────────────────────────────────────────────────────
# Allows: name@paytm  9876543210@ybl  user.name@okicici
UPI_PATTERN = re.compile(r"^[\w.\-]{2,}@[a-zA-Z]{2,}$")


# ── FSM State Keys ────────────────────────────────────────────────────────────
class States:
    IDLE             = "idle"
    NAME             = "name"
    MOBILE           = "mobile"
    PLAN             = "plan"
    SCREENSHOT       = "screenshot"
    UPI              = "upi"
    CONFIRM          = "confirm"

    # Admin states
    A_UTR            = "a_utr"
    A_DECLINE_REASON = "a_decline_reason"
    A_NOTE           = "a_note"
    A_BROADCAST      = "a_broadcast"
    A_SEARCH         = "a_search"
    A_ADD_PLAN_NAME  = "a_add_plan_name"
    A_ADD_PLAN_ORIG  = "a_add_plan_orig"
    A_ADD_PLAN_REF   = "a_add_plan_ref"
    A_EDIT_PLAN_NAME = "a_edit_plan_name"
    A_EDIT_PLAN_ORIG = "a_edit_plan_orig"
    A_EDIT_PLAN_REF  = "a_edit_plan_ref"
    A_WELCOME_MSG    = "a_welcome_msg"
    A_SUPPORT_MSG    = "a_support_msg"
    A_WORKING_DAYS   = "a_working_days"
    A_ADD_ADMIN      = "a_add_admin"

    # All admin input states in one set for quick lookup
    ALL_ADMIN_INPUT = {
        A_UTR, A_DECLINE_REASON, A_NOTE, A_BROADCAST, A_SEARCH,
        A_ADD_PLAN_NAME, A_ADD_PLAN_ORIG, A_ADD_PLAN_REF,
        A_EDIT_PLAN_NAME, A_EDIT_PLAN_ORIG, A_EDIT_PLAN_REF,
        A_WELCOME_MSG, A_SUPPORT_MSG, A_WORKING_DAYS, A_ADD_ADMIN,
    }
