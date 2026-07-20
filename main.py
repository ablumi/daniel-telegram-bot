"""
הלוחש לצמחים — Telegram DM Bot
================================
סורק Instagram + Facebook כל 12 שעות,
שולח הצעות תשובה לדניאל בטלגרם עם אפשרות ערוך/שלח/דלג.
"""

import asyncio
import logging
import os
import re
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
DANIEL_PROMPT = """אתה דניאל בנטל — "הלוחש לצמחים". אתה עונה על DM מעוקבים בשם דניאל.

═══ כללי ברזל ═══
• קצר מאוד — הודעה אחת, עד 3 משפטים קצרים. לפעמים 4 מילים מספיקות.
• שפה שיחתית כמו WhatsApp — בלי פיסוק מיותר, בלי פורמליות
• אם אתה מבין את הבעיה — עצה ישירה בלי הקדמות
• אם צריך מידע — שאלה אחת בלבד
• אסור: "שמחתי לשמוע" / "תודה על השאלה" / "אני ממליץ ש" / "שלום" / "ערב טוב" / לחזור על מה שנכתב / פסקאות ארוכות

═══ 5 סוגי תגובות ═══

1. עצה ישירה — כשהבעיה ברורה:
   "כן לשים אותו במקום מואר יותר מסכנציק"
   "זה נשמע כמו השקיה יתרה, תנסי להשקות רק כש-2/3 מהאדמה מתייבשת"

2. שאלה אבחנתית — כשצריך עוד מידע (שאלה אחת!):
   "איזה תולעת?" / "יש לו מספיק אור?" / "כמה זמן יש לך אותו?" / "כמה פעמים בשבוע את משקה?"

3. הפנייה לסרטון — כשהנושא מכוסה בסרטון:
   "העליתי סרטון על זה לא מזמן, כנסי לעמוד 🌱"
   סרטונים קיימים: נענע, פיקוס כינורי, אלוקסיה, פילודנדרון, בזיליקום, air layering, כנימה קמחית, זחל המודד, מונסטרה, קולאוס, סחלב, דשן מבננה, ביצן, שתייה מצמחים

4. הפנייה לייעוץ — כשמורכב מדי לDM:
   "היי [שם], כדי שאוכל לאבחן נכון צריך לראות — יש ייעוץ וידאו חצי שעה ב-99₪, אם מתאים נקבע 🌱"

5. תגובה רגשית — כשמישהו שותף הצלחה / כותב דברים נחמדים:
   "באהבה 🙂" / "חחח יאלה" / "כיף לשמוע"

═══ ידע מקצועי ═══
עלים צהובים = השקיית יתר (90% מהמקרים)
קצות חומים = יובש / מזגן / מים קשים
עלים נופלים על פיקוס = הזזה/רוח (לא לזוז ממקומו)
כנימה קמחית = מטלית לחה במים בלבד (לא מגבון לח! כימיקלים), אחר כך ריסוס מים+סבון כלים
אקריות (עכבישיות) = שמן נים, ריסוס: ליטר מים + כפית סבון + חצי כפית שמן נים
פיקוס כינורי = שונא הזזה, להשקות רק כש-50% מתייבש, אור עקיף חזק
מונסטרה = צריך עמוד מוס, עלים חדשים = מים
סחלב = השקיה בטבילה 10 דק' פעם בשבוע, אחר כך לנקז לגמרי
השרשה = כוס מים, אור עקיף, להחליף מים כל יומיים"""

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
async def fetch_new_messages(since: datetime) -> tuple[list[dict], bool]:
    """מושך הודעות חדשות מ-Instagram ו-Facebook מאז זמן נתון.
    מחזיר (הודעות, הצלחה) — הצלחה=True רק אם לפחות פלטפורמה אחת הצליחה."""
    messages = []
    any_success = False

    async def fetch_all_pages(client, url, params):
        """מושך את כל הדפים של conversations עם pagination."""
        results = []
        next_url = url
        next_params = params.copy()
        page = 0
        while page < 20:  # מקסימום 20 דפים (500 שיחות)
            resp = await client.get(next_url, params=next_params)
            data = resp.json()
            if "error" in data:
                logger.error(f"Meta API error: {data['error']}")
                raise Exception(data["error"].get("message", "API error"))
            batch = data.get("data", [])
            results.extend(batch)
            page += 1
            logger.info(f"  pagination page {page}: got {len(batch)} convs, total={len(results)}")

            # בדוק אם יש עמוד הבא — תומך גם ב-next URL וגם ב-cursor
            paging = data.get("paging", {})
            next_url_candidate = paging.get("next")
            if next_url_candidate:
                next_url = next_url_candidate
                next_params = {}  # next כבר מכיל את כל הפרמטרים
            else:
                # נסה cursor-based pagination
                after_cursor = paging.get("cursors", {}).get("after")
                if after_cursor:
                    next_url = url
                    next_params = {**params, "after": after_cursor}
                else:
                    break  # אין עמוד הבא

            # אם הדף האחרון ריק — עצור
            if not batch:
                break
        return results

    async with httpx.AsyncClient(timeout=30) as client:

        # Instagram
        if INSTAGRAM_ACCOUNT_ID:
            try:
                url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/conversations"
                params = {
                    "platform": "instagram",
                    "access_token": META_PAGE_TOKEN,
                    "fields": "messages{id,message,from,created_time}",
                    "limit": 25,
                }
                convs = await fetch_all_pages(client, url, params)
                any_success = True
                for conv in convs:
                    for msg in conv.get("messages", {}).get("data", []):
                        created = datetime.fromisoformat(
                            msg["created_time"].replace("Z", "+00:00")
                        )
                        if created <= since:
                            continue
                        if msg.get("from", {}).get("id") == INSTAGRAM_ACCOUNT_ID:
                            continue
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
                    "limit": 25,
                }
                convs = await fetch_all_pages(client, url, params)
                any_success = True
                for conv in convs:
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

    return messages, any_success

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

# ─── Thank-you detection ─────────────────────────────────────────────────────
_THANKS_WORDS = [
    'תודה', 'תודות', 'תנקיו', 'תנקס',
    'thanks', 'thank you', 'thank u', 'thanku', 'ty', 'thx', 'tyvm', 'tysm',
    'merci', 'gracias', 'danke',
]
_EMOJI_RE = re.compile(
    r'[\U00010000-\U0010FFFF☀-➿︀-️‍⃣\U0001FA00-\U0001FA9F]',
    re.UNICODE
)

def is_thank_you_only(text: str) -> bool:
    """מחזיר True אם ההודעה היא רק תודה/אמוג'י ואין בה שאלה או בקשה נוספת."""
    if not text or not text.strip():
        return False
    stripped = text.strip()

    # אם יש סימן שאלה — יש שאלה, צריך תגובה
    if '?' in stripped or '؟' in stripped:
        return False

    # הסר אמוג'י, סימני פיסוק ורווחים
    no_emoji = _EMOJI_RE.sub('', stripped).strip()
    no_punct = re.sub(r'[!.,;:\'"()\-–—]', '', no_emoji).strip().lower()

    # הודעת אמוג'י בלבד — לייק
    if not no_punct:
        return True

    # אם ארוך מ-60 תווים אחרי ניקוי — כנראה יש תוכן נוסף
    if len(no_punct) > 60:
        return False

    # בדוק אם מתחיל בביטוי תודה וכלום חשוב אחריו
    for word in _THANKS_WORDS:
        if no_punct == word or no_punct.startswith(word + ' ') or no_punct.startswith(word + '!'):
            # וודא שמה שאחרי זה גם תודה (תודה תודה תודה) ולא משפט חדש
            rest = no_punct[len(word):].strip().lstrip('!')
            if not rest or all(
                rest.startswith(w) or rest == w
                for w in _THANKS_WORDS
                if rest.startswith(w)
            ):
                return True
            # אם מה שנשאר הוא עוד תודות — בסדר
            rest_clean = re.sub(r'\b(' + '|'.join(_THANKS_WORDS) + r')\b', '', rest).strip()
            if not rest_clean:
                return True
    return False


async def send_meta_like(message_id: str, sender_id: str, platform: str) -> bool:
    """שולח לייק ❤️ על הודעה ב-Instagram או Facebook."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if platform == "instagram":
                url = f"https://graph.facebook.com/v19.0/{message_id}/likes"
                resp = await client.post(url, params={"access_token": META_PAGE_TOKEN})
            else:
                # Facebook Messenger — react to message
                url = "https://graph.facebook.com/v19.0/me/messages"
                payload = {
                    "recipient": {"id": sender_id},
                    "sender_action": "react",
                    "payload": {"message_id": message_id, "reaction": "love"},
                }
                resp = await client.post(
                    url, json=payload,
                    headers={"Authorization": f"Bearer {META_PAGE_TOKEN}"}
                )
            if resp.status_code == 200:
                return True
            logger.warning(f"Like API {resp.status_code}: {resp.text[:120]}")
            return False
    except Exception as e:
        logger.error(f"Meta like error: {type(e).__name__}: {e}")
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

    messages, success = await fetch_new_messages(since)
    logger.info(f"Found {len(messages)} new messages (api_success={success})")

    if not messages:
        return

    conn = get_db()
    new_count = 0
    liked_names = []  # סיכום לייקים אוטומטיים

    for msg in messages:
        # בדוק שלא עיבדנו כבר
        exists = conn.execute(
            "SELECT id FROM messages WHERE msg_id=?", (msg["msg_id"],)
        ).fetchone()
        if exists:
            continue

        # ─── לייק אוטומטי להודעות תודה ───────────────────────────────────
        if is_thank_you_only(msg["message_text"]):
            liked = await send_meta_like(msg["msg_id"], msg["sender_id"], msg["platform"])
            status = "liked" if liked else "skipped"
            conn.execute(
                """INSERT INTO messages (msg_id, sender_id, sender_name, platform, message_text, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (msg["msg_id"], msg["sender_id"], msg["sender_name"],
                 msg["platform"], msg["message_text"], status)
            )
            conn.commit()
            logger.info(f"Auto-liked message from {msg['sender_name']} ({msg['platform']}): {msg['message_text'][:40]}")
            if liked:
                liked_names.append(msg.get("sender_name") or "משתמש")
            continue

        # ─── עיבוד רגיל: ייצר תשובה ושלח לטלגרם ─────────────────────────
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

    # שלח סיכום לייקים אם היו
    if liked_names:
        names_str = ", ".join(liked_names[:15])
        suffix = f" ועוד {len(liked_names)-15}" if len(liked_names) > 15 else ""
        try:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"❤️ לייק אוטומטי נשלח ל-{len(liked_names)} הודעות תודה:\n{names_str}{suffix}"
            )
        except Exception as e:
            logger.error(f"Telegram liked summary error: {type(e).__name__}")

    # מקדם last_scan רק אם ה-API הצליח — כדי לא לדלג על הודעות בזמן תקלות
    if success:
        set_last_scan(now)
        logger.info(f"last_scan updated to {now.isoformat()}")
    else:
        logger.warning("Skipping last_scan update — all API calls failed")

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


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /reset [ימים] — מאפס את חלון הסריקה N ימים אחורה (ברירת מחדל: 30)."""
    if update.effective_user.id != TELEGRAM_CHAT_ID:
        return
    days = 30
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ שימוש: /reset [מספר ימים]")
            return
    new_since = datetime.now(timezone.utc) - timedelta(days=days)
    set_last_scan(new_since)
    await update.message.reply_text(
        f"🔄 חלון הסריקה אופס ל-{days} ימים אחורה.\n"
        f"הסריקה הבאה תמשוך הודעות מאז {new_since.strftime('%d/%m/%Y %H:%M')} UTC.\n"
        f"הרץ /scan עכשיו כדי לסרוק מיד."
    )


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
    app.add_handler(CommandHandler("reset", cmd_reset))
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
