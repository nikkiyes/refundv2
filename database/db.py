"""
Database Layer — Pareeksha Gurukul Refund Bot v2
Fully async SQLite via aiosqlite.

FIX v2: All functions use 'async with aiosqlite.connect(DB_PATH) as db'
directly instead of the broken 'async with await get_db()' pattern.
"""

import aiosqlite
import os
import json
import csv
import io
import logging
import random
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from config.config import DB_PATH, ADMIN_IDS

# Ensure data directory exists at import time
_db_dir = os.path.dirname(DB_PATH)
if _db_dir:
    os.makedirs(_db_dir, exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA
# ══════════════════════════════════════════════════════════════════════════════
SCHEMA = """\
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT    DEFAULT '',
    first_name  TEXT    DEFAULT '',
    last_name   TEXT    DEFAULT '',
    is_banned   INTEGER DEFAULT 0,
    joined_at   TEXT    DEFAULT (datetime('now','localtime')),
    last_active TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS plans (
    plan_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_name       TEXT    NOT NULL UNIQUE,
    original_amount REAL    NOT NULL,
    refund_amount   REAL    NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS refund_requests (
    request_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id          TEXT    NOT NULL UNIQUE,
    user_id            INTEGER NOT NULL,
    full_name          TEXT    NOT NULL,
    mobile             TEXT    NOT NULL,
    plan_id            INTEGER NOT NULL,
    plan_name          TEXT    NOT NULL,
    original_amount    REAL    NOT NULL,
    refund_amount      REAL    NOT NULL,
    upi_id             TEXT    NOT NULL,
    screenshot_file_id TEXT    NOT NULL,
    status             TEXT    DEFAULT 'Pending',
    utr_number         TEXT,
    admin_remarks      TEXT,
    admin_note         TEXT,
    processed_by       INTEGER,
    admin_msg_id       INTEGER,
    submitted_at       TEXT    DEFAULT (datetime('now','localtime')),
    processed_at       TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    admin_id  INTEGER PRIMARY KEY,
    username  TEXT    DEFAULT '',
    added_by  INTEGER,
    added_at  TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS logs (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT    NOT NULL,
    actor_id   INTEGER,
    target_id  INTEGER,
    details    TEXT,
    created_at TEXT    DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sessions (
    user_id    INTEGER PRIMARY KEY,
    state      TEXT    DEFAULT 'idle',
    data       TEXT    DEFAULT '{}',
    updated_at TEXT    DEFAULT (datetime('now','localtime'))
);
"""

_DEFAULT_SETTINGS = {
    "working_days":    "7",
    "refund_enabled":  "1",
    "welcome_message": (
        "Welcome to *Pareeksha Gurukul Refund Support* 🎓\n\n"
        "We are here to help you with your refund request.\n"
        "Our team processes refunds after careful verification.\n\n"
        "Please select an option below:"
    ),
    "support_message": (
        "📞 *Need Help?*\n\n"
        "Contact us at @PareekshaGurukul\n"
        "Our team is available Mon–Sat, 10 AM – 6 PM IST."
    ),
    "footer_message":  "Thank you,\nPareeksha Gurukul Support Team 🎓",
}

_DEFAULT_PLANS = [
    ("499 Plan", 499, 205),
    ("299 Plan", 299, 123),
]


# ══════════════════════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════════════════════
async def init_db() -> None:
    """Create all tables and seed initial data."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        # executescript needs plain string; run each pragma separately first
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
        # Create tables
        for stmt in _split_schema(SCHEMA):
            if stmt.strip():
                await db.execute(stmt)

        # Seed settings
        for k, v in _DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
            )

        # Seed default plans
        for name, orig, ref in _DEFAULT_PLANS:
            await db.execute(
                "INSERT OR IGNORE INTO plans(plan_name,original_amount,refund_amount) VALUES(?,?,?)",
                (name, orig, ref),
            )

        # Seed super-admins
        for aid in ADMIN_IDS:
            await db.execute(
                "INSERT OR IGNORE INTO admins(admin_id) VALUES(?)", (aid,)
            )

        await db.commit()
    logger.info("Database ready: %s", DB_PATH)


def _split_schema(schema: str) -> list:
    """Split schema string into individual statements (skip PRAGMA lines)."""
    stmts = []
    for stmt in schema.split(";"):
        s = stmt.strip()
        if s and not s.upper().startswith("PRAGMA"):
            stmts.append(s)
    return stmts


# ══════════════════════════════════════════════════════════════════════════════
#  TICKET ID
# ══════════════════════════════════════════════════════════════════════════════
def generate_ticket_id() -> str:
    ts   = datetime.now().strftime("%Y%m%d%H%M%S")
    rand = random.randint(100, 999)
    return f"PG-{ts}-{rand}"


# ══════════════════════════════════════════════════════════════════════════════
#  USERS
# ══════════════════════════════════════════════════════════════════════════════
async def upsert_user(user_id: int, username: str, first_name: str, last_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users(user_id,username,first_name,last_name)
               VALUES(?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   username=excluded.username,
                   first_name=excluded.first_name,
                   last_name=excluded.last_name,
                   last_active=datetime('now','localtime')""",
            (user_id, username, first_name, last_name),
        )
        await db.commit()


async def is_banned(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT is_banned FROM users WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        return bool(row and row["is_banned"])


async def ban_user(user_id: int, actor_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (user_id,))
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("BAN_USER", actor_id, user_id, "Banned"),
        )
        await db.commit()


async def unban_user(user_id: int, actor_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (user_id,))
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("UNBAN_USER", actor_id, user_id, "Unbanned"),
        )
        await db.commit()


async def get_all_user_ids() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT user_id FROM users WHERE is_banned=0")
        rows = await cur.fetchall()
        return [r["user_id"] for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
#  PLANS
# ══════════════════════════════════════════════════════════════════════════════
async def get_active_plans() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM plans WHERE is_active=1 ORDER BY plan_name"
        )
        return await cur.fetchall()


async def get_all_plans() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM plans ORDER BY plan_name")
        return await cur.fetchall()


async def get_plan(plan_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,))
        return await cur.fetchone()


async def add_plan(name: str, original: float, refund: float) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO plans(plan_name,original_amount,refund_amount) VALUES(?,?,?)",
            (name, original, refund),
        )
        await db.commit()
        return cur.lastrowid


async def update_plan(plan_id: int, name: str, original: float, refund: float) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE plans SET plan_name=?,original_amount=?,refund_amount=? WHERE plan_id=?",
            (name, original, refund, plan_id),
        )
        await db.commit()


async def toggle_plan_active(plan_id: int, active: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE plans SET is_active=? WHERE plan_id=?",
            (1 if active else 0, plan_id),
        )
        await db.commit()


async def delete_plan(plan_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE plans SET is_active=0 WHERE plan_id=?", (plan_id,)
        )
        await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  REFUND REQUESTS
# ══════════════════════════════════════════════════════════════════════════════
async def create_request(
    user_id: int, full_name: str, mobile: str,
    plan_id: int, plan_name: str,
    original_amount: float, refund_amount: float,
    upi_id: str, screenshot_file_id: str,
) -> tuple:
    """Returns (request_id, ticket_id)."""
    ticket = generate_ticket_id()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """INSERT INTO refund_requests
               (ticket_id,user_id,full_name,mobile,plan_id,plan_name,
                original_amount,refund_amount,upi_id,screenshot_file_id)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (ticket, user_id, full_name, mobile, plan_id, plan_name,
             original_amount, refund_amount, upi_id, screenshot_file_id),
        )
        await db.execute(
            "INSERT INTO logs(action,actor_id,details) VALUES(?,?,?)",
            ("SUBMIT", user_id, f"Ticket:{ticket}"),
        )
        await db.commit()
        return cur.lastrowid, ticket


async def get_request_by_id(request_id: int) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM refund_requests WHERE request_id=?", (request_id,)
        )
        return await cur.fetchone()


async def get_request_by_ticket(ticket_id: str) -> Optional[aiosqlite.Row]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM refund_requests WHERE ticket_id=?", (ticket_id,)
        )
        return await cur.fetchone()


async def get_active_request_for_user(user_id: int) -> Optional[aiosqlite.Row]:
    """Returns pending/processing request if user already has one open."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM refund_requests WHERE user_id=? AND status IN ('Pending','Processing') LIMIT 1",
            (user_id,),
        )
        return await cur.fetchone()


async def get_user_requests(user_id: int, limit: int = 5) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM refund_requests WHERE user_id=? ORDER BY submitted_at DESC LIMIT ?",
            (user_id, limit),
        )
        return await cur.fetchall()


async def get_requests_by_status(status: str, page: int = 0, per_page: int = 5) -> tuple:
    """Returns (rows, total_count)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT COUNT(*) as cnt FROM refund_requests WHERE status=?", (status,)
        )
        total = (await cur.fetchone())["cnt"]
        cur = await db.execute(
            "SELECT * FROM refund_requests WHERE status=? ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
            (status, per_page, page * per_page),
        )
        rows = await cur.fetchall()
        return rows, total


async def search_requests(query: str) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        like = f"%{query}%"
        cur = await db.execute(
            """SELECT * FROM refund_requests
               WHERE ticket_id LIKE ? OR mobile LIKE ? OR full_name LIKE ?
               ORDER BY submitted_at DESC LIMIT 20""",
            (like, like, like),
        )
        return await cur.fetchall()


async def approve_request(request_id: int, utr: str, admin_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE refund_requests SET
               status='Approved', utr_number=?, processed_by=?,
               processed_at=datetime('now','localtime')
               WHERE request_id=?""",
            (utr, admin_id, request_id),
        )
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("APPROVE", admin_id, request_id, f"UTR:{utr}"),
        )
        await db.commit()


async def decline_request(request_id: int, reason: str, admin_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE refund_requests SET
               status='Declined', admin_remarks=?, processed_by=?,
               processed_at=datetime('now','localtime')
               WHERE request_id=?""",
            (reason, admin_id, request_id),
        )
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("DECLINE", admin_id, request_id, reason[:200]),
        )
        await db.commit()


async def set_admin_note(request_id: int, note: str, admin_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE refund_requests SET admin_note=? WHERE request_id=?",
            (note, request_id),
        )
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("NOTE", admin_id, request_id, note[:200]),
        )
        await db.commit()


async def set_admin_msg_id(request_id: int, msg_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE refund_requests SET admin_msg_id=? WHERE request_id=?",
            (msg_id, request_id),
        )
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        stats = {}
        for status in ("Pending", "Approved", "Declined", "Processing"):
            cur = await db.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(refund_amount),0) as total "
                "FROM refund_requests WHERE status=?",
                (status,),
            )
            row = await cur.fetchone()
            stats[status] = {"count": row["cnt"], "total": row["total"]}
        cur = await db.execute("SELECT COUNT(*) as cnt FROM users")
        stats["users"] = (await cur.fetchone())["cnt"]
        cur = await db.execute("SELECT COUNT(*) as cnt FROM plans WHERE is_active=1")
        stats["plans"] = (await cur.fetchone())["cnt"]
        return stats


async def export_csv() -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM refund_requests ORDER BY submitted_at DESC"
        )
        rows = await cur.fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Ticket ID", "User ID", "Full Name", "Mobile", "Plan",
        "Original Amount", "Refund Amount", "UPI ID", "Status",
        "UTR Number", "Admin Remarks", "Submitted At", "Processed At",
    ])
    for r in rows:
        writer.writerow([
            r["ticket_id"], r["user_id"], r["full_name"], r["mobile"],
            r["plan_name"], r["original_amount"], r["refund_amount"],
            r["upi_id"], r["status"], r["utr_number"] or "",
            r["admin_remarks"] or "", r["submitted_at"], r["processed_at"] or "",
        ])
    return output.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
#  ADMINS
# ══════════════════════════════════════════════════════════════════════════════
async def is_admin(user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT 1 FROM admins WHERE admin_id=?", (user_id,)
        )
        return await cur.fetchone() is not None


async def add_admin(admin_id: int, username: str, added_by: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO admins(admin_id,username,added_by) VALUES(?,?,?)",
            (admin_id, username, added_by),
        )
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("ADD_ADMIN", added_by, admin_id, f"@{username}"),
        )
        await db.commit()


async def remove_admin(admin_id: int, removed_by: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM admins WHERE admin_id=?", (admin_id,))
        await db.execute(
            "INSERT INTO logs(action,actor_id,target_id,details) VALUES(?,?,?,?)",
            ("REMOVE_ADMIN", removed_by, admin_id, "Removed"),
        )
        await db.commit()


async def get_all_admins() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM admins")
        return await cur.fetchall()


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
async def get_setting(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else None


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO settings(key,value) VALUES(?,?)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value,
                   updated_at=datetime('now','localtime')""",
            (key, value),
        )
        await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  SESSIONS
# ══════════════════════════════════════════════════════════════════════════════
async def get_session(user_id: int) -> tuple:
    """Returns (state_str, data_dict)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT state, data FROM sessions WHERE user_id=?", (user_id,)
        )
        row = await cur.fetchone()
        if row:
            try:
                data = json.loads(row["data"])
            except Exception:
                data = {}
            return row["state"], data
        return "idle", {}


async def set_session(user_id: int, state: str, data: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO sessions(user_id,state,data) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                   state=excluded.state,
                   data=excluded.data,
                   updated_at=datetime('now','localtime')""",
            (user_id, state, json.dumps(data)),
        )
        await db.commit()


async def clear_session(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sessions(user_id,state,data) VALUES(?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET state='idle',data='{}'",
            (user_id, "idle", "{}"),
        )
        await db.commit()
