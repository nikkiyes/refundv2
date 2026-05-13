# 🎓 Pareeksha Gurukul Refund Bot — v2

Production-ready async Telegram refund management bot.

---

## 🐛 Bugs Fixed in v2

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `main.py` | `FileHandler("bot.log")` crashes on Railway (read-only `/app`) | Removed — stdout only |
| 2 | `main.py` | `asyncio_filters` imported but never used | Removed |
| 3 | `database/db.py` | `async with await get_db()` — fragile double-await pattern | All functions use `async with aiosqlite.connect(DB_PATH)` directly |
| 4 | `admin_handlers.py` | `InputFile(file_obj, file_name=...)` — wrong class for pyTelegramBotAPI 4.x | Changed to `BufferedInputFile(bytes, filename=...)` |
| 5 | `admin_handlers.py` + `user_handlers.py` | Both registered `@bot.message_handler(content_types=["text"])` — duplicate handler conflict, unpredictable routing | Admin FSM handler uses `func=lambda m: True` with internal guard; cleanly returns for non-admin states |
| 6 | `user_handlers.py` | `_show_status(bot_or_chat, ...)` — dead alias, both branches identical | Cleaned to `_show_status(bot, chat_id, user_id, msg_id=None)` |
| 7 | `requirements.txt` | Missing `aiohttp` — pyTelegramBotAPI async **requires** it | Added `aiohttp==3.9.5` |
| 8 | `railway.toml` | `builder = "nixpacks"` + custom `nixpacks.toml` breaks pip PATH | `builder = "RAILPACK"`, `nixpacks.toml` deleted |
| 9 | All handlers | No try/except around `edit_message_text` — crashes on `MessageNotModified` | All edits wrapped with fallback `send_message` |
| 10 | `admin_handlers.py` | Admin pending state in memory dict — lost on restart | Moved to DB sessions |

---

## ⚙️ Setup

### 1 — Create bot
1. Open [@BotFather](https://t.me/BotFather) → `/newbot`
2. Copy the **Bot Token**

### 2 — Get your Telegram ID
Open [@userinfobot](https://t.me/userinfobot) → send `/start` → copy your **User ID**

### 3 — Create admin group
1. Create a Telegram group
2. Add your bot → make it **Admin**
3. Get the group ID (negative number) via [@RawDataBot](https://t.me/RawDataBot)

### 4 — Configure `.env`
```bash
cp .env.example .env
# Edit .env and fill in BOT_TOKEN, ADMIN_IDS, ADMIN_GROUP_ID
```

### 5 — Run locally
```bash
pip install -r requirements.txt
python main.py
```

---

## 🚂 Deploy on Railway

1. Push to GitHub:
```bash
git init && git add . && git commit -m "v2"
git remote add origin https://github.com/you/pg-refund-bot
git push -u origin main
```

2. Railway → **New Project** → **Deploy from GitHub**

3. Add environment variables in Railway **Variables** tab:

| Key | Value |
|-----|-------|
| `BOT_TOKEN` | Your bot token |
| `ADMIN_IDS` | Your Telegram user ID |
| `ADMIN_GROUP_ID` | Group ID (negative number) |

4. Railway auto-detects `.python-version` (3.11) and `railway.toml` → deploys.

---

## 📁 Structure

```
pg_refund_bot_v2/
├── main.py                  ← Entry point
├── requirements.txt         ← Dependencies
├── railway.toml             ← RAILPACK builder
├── .python-version          ← Pins Python 3.11
├── .env.example
├── .gitignore
├── config/config.py         ← Env vars, FSM states
├── database/db.py           ← All DB operations (aiosqlite)
├── handlers/
│   ├── user_handlers.py     ← Student flow
│   └── admin_handlers.py    ← Admin panel + notify
├── keyboards/keyboards.py   ← All keyboard builders
├── utils/messages.py        ← All message text
└── middlewares/             ← (rate limiting placeholder)
```

---

## 🤖 Commands

**User:** `/start` `/refund` `/status` `/help` `/cancel`

**Admin:** `/admin` `/stats` `/plans` `/broadcast` `/export` `/requests`
