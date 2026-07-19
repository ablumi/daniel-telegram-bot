"""
הלוחש לצמחים — Telegram DM Bot
================================
סורק Instagram + Facebook כל 12 שעות,
שולח הצעות תשובה לדניאל בטלגרם עם אפשרות ערוך/שלח/דלג.
"""

import asyncio
import logging
import os
import sqlite3
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

import httpx
from anthropic import Anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN       = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID     = int(os.environ["TELEGRAM_CHAT_ID"])   # ה-chat ID של דניאל
META_PAGE_TOKEN      = os.environ["META_PAGE_ACCESS_TOKEN"]
ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
FACEBOOK_PAGE_ID     = os.environ.get("FACEBOOK_PAGE_ID", "")
DB_PATH              = os.environ.get("DB_PATH", "messages.db")
SCAN_HOURS           = int(os.environ.get("SCAN_HOURS", "12"))

anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── System prompt ────────────────────────────────────────────────────────────
DANIEL_PROMPT = """אתה דניאל בנטל — "הלוחש לצמחים". אתה עונה על הודעות DM בשם דניאל.

כלל ראשי: קצר מאוד — לא יותר מ-3 משפטים. שיחתי כמו WhatsApp.

5 סוגי תגובות:
1. זיהוי + עצה אחת
2. שאלה אבחנתית (שאלה אחת קצרה)
3. הפנייה לייעוץ וידאו 99₪ לשאלות מורכבות — "רוצה שנקבע?"
4. תגובה רגשית: "באהבה" / "🙂" / "חחח"
5. עצה ישירה כשברור מה הבעיה

אסור: ❌ פתיחות מנומסות ❌ לחזור על מה ששאלו ❌ "אני ממליץ ש..." ❌ הרבה אמוג'י ❌ לסיים בשאלה (אלא שאלת מכירה)

ידע: עלים צהובים=השקיית יתר | קצות חומים=יובש/מזגן | פיקוס מפיל=הזזה/רוח | כנימה קמחית=מטלית לחה במים (לא מגבון!) | אקריות=שמן נים | ריסוס: ליטר מים+כפית סבון+חצי כפית שמן | פיקוס כינורי: שונא הזזה, להשקות כש-50% מתייבש | מונסטרה: עמוד מוס | סחלב: טבילה 10 דק' | ייעוץ וידאו: 99₪"""

# ─── Database ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_id          TEXT UNIQUE,
            sender_id       TEXT NOT NULL,
            sender_name     TEXT,
            platform        TEXT,
            message_text    TEXT NOT NULL,
            suggested_reply TEXT,
            telegram_msg_id INTEGER,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # ברירת מחדל: סריקה מ-24 שעות אחורה בהתחלה
    conn.execute(
        "INSERT OR IGNORE INTO state (key, value) VALUES ('last_scan', ?)",
        ((datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(),)
    )
    conn.commit()
    conn.close()

def get_last_scan() -> datetime:
    conn = get_db()
    row = conn.execute("SELECT value FROM state WHERE key='last_scan'").fetchone()
    conn.close()
    return datetime.fromisoformat(row["value"]) if row else datetime.now(timezone.utc) - timedelta(hours=24)

def set_last_scan(ts: datetime):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES ('last_scan', ?)", (ts.isoformat(),))
    conn.commit()
    conn.close()

# ─── Meta API — polling ───────────────────────────────────────────────────────
async def fetch_new_messages(since: datetime) -> list[dict]:
    """מושך הודעות חדשות מ-Instagram ו-Facebook מאז זמן נתון."""
    messages = []
    since_ts = int(since.timestamp())

    async with httpx.AsyncClient(timeout=20) as client:

        # Instagram
        if INSTAGRAM_ACCOUNT_ID:
            try:
                url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/conversations"
                params = {
                    "platform": "instagram",
                    "access_token": META_PAGE_TOKEN,
                    "fields": "messages{id,message,from,created_time}",
                }
                resp = await client.get(url, params=params)
                data = resp.json()
                for conv in data.get("data", []):
                    for msg in conv.get("messages", {}).get("data", []):
                        created = datetime.fromisoformat(
                            msg["created_time"].replace("Z", "+00:00")
                        )
                        if created <= since:
                            continue
                        if msg.get("from", {}).get("id") == INSTAGRAM_ACCOUNT_ID:
                            continue  # הודעה שיצאה מהחשבון עצמו
                        if not msg.get("message"):
                            continue
                        messages.append({
                            "msg_id": msg["id"],
                            "sender_id": msg["from"]["id"],
                            "sender_name": msg["from"].get("name", ""),
                            "platform": "instagram",
                            "message_text": msg["message"],
                        })
            except Exception as e:
                logger.error(f"Instagram fetch error: {type(e).__name__}: {e}")

        # Facebook
        if FACEBOOK_PAGE_ID:
            try:
                url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/conversations"
                params = {
                    "access_token": META_PAGE_TOKEN,
                    "fields": "messages{id,message,from,created_time}",
                }
                resp = await client.get(url, params=params)
                data = resp.json()
                for conv in data.get("data", []):
                    for msg in conv.get("messages", {}).get("data", []):
                        created = datetime.fromisoformat(
                            msg["created_time"].replace("Z", "+00:00")
                        )
                        if created <= since:
                            continue
                        if msg.get("from", {}).get("id") == FACEBOOK_PAGE_ID:
                            continue
                        if not msg.get("message"):
                            continue
                        messages.append({
                            "msg_id": msg["id"],
                            "sender_id": msg["from"]["id"],
                            "sender_name": msg["from"].get("name", ""),
                            "platform": "facebook",
                            "message_text": msg["message"],
                        })
            except Exception as e:
                logger.error(f"Facebook fetch error: {type(e).__name__}: {e}")

    return messages

# ─── Claude reply generation ──────────────────────────────────────────────────
def generate_reply(sender_name: str, message: str) -> str:
    content = f"{sender_name}: {message}" if sender_name else message
    try:
        resp = anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=DANIEL_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        logger.error(f"Claude error: {type(e).__name__}")
        return ""

# ─── Meta API — send ──────────────────────────────────────────────────────────
async def send_meta_message(sender_id: str, text: str, platform: str) -> bool:
    url = "https://graph.facebook.com/v19.0/me/messages"
    payload = {
        "recipient": {"id": sender_id},
        "message": {"text": text},
        "messaging_type": "RESPONSE",
    }
    headers = {"Authorization": f"Bearer {META_PAGE_TOKEN}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
            return resp.status_code == 200
    except Exception as e:
        logger.error(f"Meta send error: {type(e).__name__}")
        return False

# ─── Telegram message formatting ──────────────────────────────────────────────
PLATFORM_EMOJI = {"instagram": "📸", "facebook": "💙"}

def build_telegram_text(msg: dict) -> str:
    emoji = PLATFORM_EMOJI.get(msg["platform"], "💬")
    platform_name = "Instagram" if msg["platform"] == "instagram" else "Facebook"
    name = msg["sender_name"] or "משתמש"
    return (
        f"{emoji} <b>{platform_name}</b> • {name}\n"
        f"─────────────────\n"
        f"{msg['message_text']}\n"
        f"─────────────────\n"
        f"💬 <b>תשובה מוצעת:</b>\n"
        f"{msg['suggested_reply'] or '⏳ מייצר תשובה...'}"
    )

def build_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ שלח", callback_data=f"send:{msg_id}"),
            InlineKeyboardButton("✏️ ערוך ושלח", callback_data=f"edit:{msg_id}"),
            InlineKeyboardButton("⏭️ דלג", callback_data=f"skip:{msg_id}"),
        ]
    ])

# ─── Scanner ──────────────────────────────────────────────────────────────────
async def scan_and_notify(bot):
    """הסריקה הראשית — מושכת DMs חדשים ושולחת לטלגרם."""
    logger.info("Starting scan...")
    since = get_last_scan()
    now = datetime.now(timezone.utc)

    messages = await fetch_new_messages(since)
    logger.info(f"Found {len(messages)} new messages")

    if not messages:
        return

    conn = get_db()
    new_count = 0

    for msg in messages:
        # בדוק שלא עיבדנו כבר
        exists = conn.execute(
            "SELECT id FROM messages WHERE msg_id=?", (msg["msg_id"],)
        ).fetchone()
        if exists:
            continue

        # ייצר תשובה
        suggested = generate_reply(msg["sender_name"] or "הלקוח", msg["message_text"])
        msg["suggested_reply"] = suggested

        # שמור ב-DB
        cur = conn.execute(
            """INSERT INTO messages (msg_id, sender_id, sender_name, platform, message_text, suggested_reply)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg["msg_id"], msg["sender_id"], msg["sender_name"],
             msg["platform"], msg["message_text"], suggested)
        )
        conn.commit()
        db_id = cur.lastrowid

        # שלח לטלגרם
        try:
            tg_msg = await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=build_telegram_text(msg),
                parse_mode="HTML",
                reply_markup=build_keyboard(db_id),
            )
            conn.execute(
                "UPDATE messages SET telegram_msg_id=? WHERE id=?",
                (tg_msg.message_id, db_id)
            )
            conn.commit()
            new_count += 1
        except Exception as e:
            logger.error(f"Telegram send error: {type(e).__name__}")

    conn.close()
    set_last_scan(now)

    if new_count > 0:
        logger.info(f"Sent {new_count} messages to Telegram")

# ─── Telegram handlers ────────────────────────────────────────────────────────
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # רק דניאל יכול להשתמש
    if query.from_user.id != TELEGRAM_CHAT_ID:
        return

    action, msg_id = query.data.split(":")
    msg_id = int(msg_id)

    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    conn.close()

    if not row or row["status"] not in ("pending",):
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if action == "send":
        success = await send_meta_message(row["sender_id"], row["suggested_reply"], row["platform"])
        status_line = "✅ נשלח!" if success else "❌ שגיאה בשליחה"
        new_text = build_telegram_text(dict(row)) + f"\n\n{status_line}"
        await query.edit_message_text(new_text, parse_mode="HTML")
        conn = get_db()
        conn.execute("UPDATE messages SET status=? WHERE id=?",
                     ("sent" if success else "error", msg_id))
        conn.commit()
        conn.close()

    elif action == "edit":
        context.user_data["editing_id"] = msg_id
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="✏️ כתוב את התשובה שאתה רוצה לשלוח:"
        )

    elif action == "skip":
        new_text = build_telegram_text(dict(row)) + "\n\n⏭️ דולג"
        await query.edit_message_text(new_text, parse_mode="HTML")
        conn = get_db()
        conn.execute("UPDATE messages SET status='skipped' WHERE id=?", (msg_id,))
        conn.commit()
        conn.close()


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מקבל טקסט כשדניאל עורך תשובה."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return

    editing_id = context.user_data.pop("editing_id", None)
    if not editing_id:
        return

    new_reply = update.message.text.strip()
    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE id=?", (editing_id,)).fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("❌ לא מצאתי את ההודעה")
        return

    success = await send_meta_message(row["sender_id"], new_reply, row["platform"])
    if success:
        await update.message.reply_text("✅ נשלח!")
        conn = get_db()
        conn.execute(
            "UPDATE messages SET status='sent', suggested_reply=? WHERE id=?",
            (new_reply, editing_id)
        )
        conn.commit()
        conn.close()
    else:
        await update.message.reply_text("❌ שגיאה בשליחה — נסה שוב")
        context.user_data["editing_id"] = editing_id  # נסה שוב


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /scan לסריקה ידנית."""
    user_id = update.effective_user.id if update.effective_user else None
    logger.info(f"cmd_scan called by user_id={user_id}, expected={TELEGRAM_CHAT_ID}")
    if user_id != TELEGRAM_CHAT_ID:
        logger.warning(f"Unauthorized /scan from {user_id}")
        return
    await update.message.reply_text("🔍 סורק הודעות חדשות...")
    await scan_and_notify(context.bot)
    await update.message.reply_text("✅ סריקה הושלמה")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /status — מציגה סטטיסטיקה."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return
    conn = get_db()
    pending = conn.execute("SELECT COUNT(*) FROM messages WHERE status='pending'").fetchone()[0]
    sent    = conn.execute("SELECT COUNT(*) FROM messages WHERE status='sent'").fetchone()[0]
    skipped = conn.execute("SELECT COUNT(*) FROM messages WHERE status='skipped'").fetchone()[0]
    last    = get_last_scan()
    conn.close()
    await update.message.reply_text(
        f"📊 סטטוס\n"
        f"⏳ ממתין: {pending}\n"
        f"✅ נשלח: {sent}\n"
        f"⏭️ דולג: {skipped}\n"
        f"🕐 סריקה אחרונה: {last.strftime('%d/%m %H:%M')}"
    )

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    init_db()
    logger.info("DB initialized")

    # בנה את אפליקציית הטלגרם
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduler לסריקה אוטומטית
    scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")
    scheduler.add_job(
        scan_and_notify,
        "cron",
        hour="9,21",   # 9 בבוקר ו-9 בערב
        kwargs={"bot": app.bot},
    )
    scheduler.start()
    logger.info(f"Scheduler started — scanning at 09:00 and 21:00 Israel time")

    # הפעל את הבוט עם polling
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()  # שמור רץ לנצח

if __name__ == "__main__":
    asyncio.run(main())
