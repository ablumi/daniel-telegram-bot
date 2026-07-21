"""
הלוחש לצמחים — Telegram DM Bot
================================
סורק Instagram + Facebook כל 12 שעות,
שולח הצעות תשובה לדניאל בטלגרם עם אפשרות ערוך/שלח/דלג.
"""

import asyncio
import html
import json
import logging
import os
import re
import sqlite3
import hmac
import hashlib
from datetime import datetime, timezone, timedelta

import httpx
from anthropic import AsyncAnthropic
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

# נמענים: TELEGRAM_CHAT_IDS="123,456" (אבירם, דניאל).
# תאימות לאחור — אם מוגדר רק TELEGRAM_CHAT_ID הישן, משתמשים בו.
_raw_ids = os.environ.get("TELEGRAM_CHAT_IDS") or os.environ.get("TELEGRAM_CHAT_ID", "")
CHAT_IDS = [int(x.strip()) for x in _raw_ids.split(",") if x.strip()]
if not CHAT_IDS:
    raise RuntimeError("חסר TELEGRAM_CHAT_IDS (או TELEGRAM_CHAT_ID) בסביבה")
AUTHORIZED_IDS = set(CHAT_IDS)
TELEGRAM_CHAT_ID = CHAT_IDS[0]   # הנמען הראשי — להודעות מערכת חד-פעמיות

# שמות תצוגה לנמענים: TELEGRAM_CHAT_NAMES="אבירם,דניאל" (אופציונלי, לפי הסדר)
_raw_names = os.environ.get("TELEGRAM_CHAT_NAMES", "")
CHAT_NAMES = {
    cid: name.strip()
    for cid, name in zip(CHAT_IDS, _raw_names.split(","))
    if name.strip()
}

META_PAGE_TOKEN      = os.environ["META_PAGE_ACCESS_TOKEN"]
ANTHROPIC_API_KEY    = os.environ["ANTHROPIC_API_KEY"]
INSTAGRAM_ACCOUNT_ID = os.environ.get("INSTAGRAM_ACCOUNT_ID", "")
FACEBOOK_PAGE_ID     = os.environ.get("FACEBOOK_PAGE_ID", "")
DB_PATH              = os.environ.get("DB_PATH", "messages.db")
SCAN_HOURS           = int(os.environ.get("SCAN_HOURS", "12"))

def display_name(user) -> str:
    """שם לתצוגה של מי שביצע פעולה."""
    return CHAT_NAMES.get(user.id) or user.first_name or str(user.id)

# Async — הקריאה ל-Claude לא חוסמת את הבוט (הכפתורים בטלגרם נשארים מגיבים בזמן סריקה)
anthropic = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# ─── System prompt ────────────────────────────────────────────────────────────
DANIEL_PROMPT = """אתה דניאל בנטל — "הלוחש לצמחים". כותב DM קצר וישיר בעברית ישראלית יומיומית.

══ חוקי ברזל ══
• מקסימום 1-2 משפטים. לפעמים 4 מילים מספיקות.
• לא "שמחתי", לא "תודה על השאלה", לא "שלום", לא "ערב טוב", לא לחזור על מה שנשאל.
• לא "חברי", לא חיבוקים, לא פתיחות מנומסות.
• לא לציין מחירים אלא אם שאלו ישירות.

══ מה לכתוב ══
בעיה ברורה → עצה ספציפית אחת ישר: "זה השקיה יתרה, להשקות רק כש-2/3 מהאדמה יבשה"
חסר מידע → שאלה אחת בלבד: "כמה פעמים אתה משקה?" / "יש לו חלון?"
נושא עם סרטון → "העליתי על זה סרטון, כנס לעמוד 🌱"
שאלה מורכבת → "היי [שם], כדי לאבחן נכון צריך לראות — ייעוץ וידאו חצי שעה 99₪, אם מתאים נקבע 🌱"
תודה / נחמד → "באהבה 🙂" / "כיף לשמוע!" / "חחח"

══ ידע ══
עלים צהובים=השקיה יתרה | קצות חומים=יובש/מזגן | פיקוס מפיל עלים=הזזה
כנימה קמחית: מטלית מים → ריסוס מים+סבון | אקריות: מים+סבון+שמן נים
פיקוס כינורי: להשקות כש-50% יבש, שונא הזזה | מונסטרה: עמוד מוס | סחלב: טבילה 10 דק' פעם בשבוע, שורשים ירוקים=לא להשקות, חובה ניקוז
צמחי מאכל: רק מי סבון (שמן נים מותר עם המתנה) | קונפידור בהגמעה: רק לא-מאכל
אין פרחים=חסר שמש+דשן | דשן: כל נוזלי ייעודי ממשתלה, 6-2-6 לירקות כל שבועיים פבר'-אוק' | כלי: חובה חורי ניקוז
מחירים: ייעוץ וידאו 30 דק' 99₪ (+30₪ מדריך וסיכום), רשימת צמחים PDF 99₪ | גינות/ביקור בית → וואטסאפ 0549799314

══ נושאים עם סרטונים ══
נענע, פיקוס כינורי, אלוקסיה, פילודנדרון, בזיליקום, כנימה קמחית, זחל המודד, מונסטרה, קולאוס, סחלב, דשן מבננה, ביצן, השרשת אוויר

══ דוגמאות אמיתיות — ככה דניאל עונה (חקה את הסגנון בדיוק) ══

לקוח: מה קרה [תמונת צמח מיובש]
דניאל: התייבש חסר מים

לקוח: איך לעזור ולהציל את הבחור הזה? [דקל מדולדל]
דניאל: כן לשים אותו במקום מואר יותר מסכנצ'יק

לקוח: איך גורמים לאנתריום ליצר פרחים?
דניאל: מלא מלא אור ולא שמש ישירה ודשן. ולרוב הוא מגיע לבגרות ואז פורח, לא יפרח כשהוא צעיר

לקוח: שמתי בלובי את העציץ הזה. הוא עצוב ממש. איך אני מציל אותו?
דניאל: מסכן הוא נראה בלי עייף. יש לו שם אור?

לקוח: אני משקה ואחר כך חלק מהעלים צהובים, מה לעשות?
דניאל: נשמע שזה אובר השקיה. תנסי לחכות בין השקיות תשקי כש2/3 מהאדמה מתייבשת. איך את יודעת? בודקת עם האצבע או שיפוד עץ - יצא יבש משקים

לקוח: כל כמה זמן להשקות צמחי בית?
דניאל: המדד הוא לא כל כמה זמן אלא כמה אדמה לחה הוא צריך

לקוח: אפשר להשריש גבעול של אוזן פיל?
דניאל: בוודאי! אבל לא עלה, חייב את הגבעול עצמו

לקוח: אני גר בדירת קרקע בלי אור טבעי, יש צמחים שיכולים להחזיק?
דניאל: בהחלט יש צמחים שמתאימים לתאורה נמוכה כמו זמיה קוקוס, סנסיווריה, פוטוס. אבל גם הם צריכים אור כלשהו יכול לצלם לי באור יום ואגיד לך אם יש מספיק

לקוח: תוכל לעשות סרטון על עץ זית שמתייבש ללא סיבה?
דניאל: חחח אין דבר כזה ללא סיבה. עץ זית שמתייבש כנראה לא סיפקו לו מספיק מים, צריך אדמה לחה ושמש ישירה לפחות 3 שעות

לקוח: [תמונת דקל מת לגמרי]
דניאל: האמת שהוא נראה גמור חח. לפעמים כדאי להתחיל מההתחלה חבל על הזמן

לקוח: אפשר לשלוח לך תמונות ולהתייעץ איתך בבקשה?
דניאל: היי ברור אני עושה שיחות ייעוץ. בשיחה את מראה לי את הצמחים, מספרת על בעיות, שואלת שאלות, מראה לי את המיקומים ביחס לאור ואני בודק תאורה, מזיקים והשקיה. זה 99₪ ויש אפשרות למדריך טיפול וסיכום שיחה בתוספת 30₪. רוצה שנקבע?

לקוח: תעזור לצמחים שלי פליזזזז [תמונה]
דניאל: היי [שם] בשמחה! כדי שאוכל לאבחן אותם אני צריך לשאול שאלות ולהבין את אופן הטיפול, אני עושה שיחות ייעוץ של חצי שעה רוצה נקבע?

לקוח: אתה מגיע גם לבתים פרטיים / לעשות גינות ומרפסות?
דניאל: היי [שם] כמובן 🙂 מה הצורך? יכולה לכתוב לי ווטצאפ אני יותר זמין שם 0549799314

לקוח: [תיאור ארוך של בעיה בלי תמונה]
דניאל: אני צריך לראות את הצמח בתמונה ולראות את המיקום בו גדל ביחס לאור

לקוח: גוזמים מתחת לניצנים או מעליהם?
דניאל: מעליהם

לקוח: האם אתה מומחה בעצי זית נוי ותוכל לייעץ לי?
דניאל: היי האמת שלא מומחה לעצי פרי אבל מה הבעיה?

לקוח: יש לי צמח עם כנימת (לבן ונדבק) מה אפשר לעשות?
דניאל: היוש, להסיר ידנית ולקלח כאקט ראשוני. ואז או להגמיע בקונפידור אם זה לא צמח מאכל. או לרסס בשמן נים או מי סבון

לקוח: אשמח גם לטיפול בקולאוס
דניאל: תגיבי קולאוס בפוסט זה יש לך אלייך אוטומטית

לקוח: מרגישה שאני מדברת עם סלב 🥰
דניאל: באהבה"""

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
            offered_consult INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (datetime('now'))
        )
    """)
    # מיגרציה ל-DB קיים
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN offered_consult INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE messages ADD COLUMN original_suggestion TEXT")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    # העתק של כל הודעה אצל כל נמען — כדי לעדכן את כולם כשאחד מגיב
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            message_id      INTEGER NOT NULL,
            chat_id         INTEGER NOT NULL,
            telegram_msg_id INTEGER NOT NULL,
            PRIMARY KEY (message_id, chat_id)
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

        def build_conv_history(all_msgs: list, page_id: str, since: datetime) -> list[dict]:
            """בונה היסטוריית שיחה מהודעות לפני since — רק אם יש תגובה אמיתית מדניאל."""
            history = []
            for m in all_msgs:
                if not m.get("message"):
                    continue
                created = datetime.fromisoformat(m["created_time"].replace("Z", "+00:00"))
                if created >= since:
                    continue  # הודעות חדשות — לא היסטוריה
                from_id = m.get("from", {}).get("id", "")
                is_daniel = (from_id == page_id)
                history.append({
                    "from": "דניאל" if is_daniel else m.get("from", {}).get("name", ""),
                    "text": m["message"],
                    "is_daniel": is_daniel,
                })
            # history מגיע בסדר הפוך (חדש→ישן), נהפוך לכרונולוגי ונשמור 8 אחרונות
            history = list(reversed(history))[-8:]
            # נחזיר רק אם יש תגובה קצרה מדניאל (לא מדריך)
            has_real_reply = any(m["is_daniel"] and len(m["text"]) < 200 for m in history)
            return history if has_real_reply else []

        # Instagram
        if INSTAGRAM_ACCOUNT_ID:
            try:
                url = f"https://graph.facebook.com/v19.0/{INSTAGRAM_ACCOUNT_ID}/conversations"
                params = {
                    "platform": "instagram",
                    "access_token": META_PAGE_TOKEN,
                    # limit(100) — מכסה גם שיחות ארוכות בסריקות עמוקות (ברירת מחדל: 25)
                    "fields": "messages.limit(100){id,message,from,created_time}",
                    "limit": 25,
                }
                convs = await fetch_all_pages(client, url, params)
                any_success = True
                for conv in convs:
                    all_conv_msgs = conv.get("messages", {}).get("data", [])
                    conv_history = build_conv_history(all_conv_msgs, INSTAGRAM_ACCOUNT_ID, since)
                    for msg in all_conv_msgs:
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
                            "conv_history": conv_history,
                        })
            except Exception as e:
                # לא מדפיסים את e — שגיאות httpx כוללות את ה-URL עם ה-access_token
                logger.error(f"Instagram fetch error: {type(e).__name__}")

        # Facebook
        if FACEBOOK_PAGE_ID:
            try:
                url = f"https://graph.facebook.com/v19.0/{FACEBOOK_PAGE_ID}/conversations"
                params = {
                    "access_token": META_PAGE_TOKEN,
                    "fields": "messages.limit(100){id,message,from,created_time}",
                    "limit": 25,
                }
                convs = await fetch_all_pages(client, url, params)
                any_success = True
                for conv in convs:
                    all_conv_msgs = conv.get("messages", {}).get("data", [])
                    conv_history = build_conv_history(all_conv_msgs, FACEBOOK_PAGE_ID, since)
                    for msg in all_conv_msgs:
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
                            "conv_history": conv_history,
                        })
            except Exception as e:
                logger.error(f"Facebook fetch error: {type(e).__name__}")

    return messages, any_success

# ─── Claude reply generation ──────────────────────────────────────────────────
async def generate_reply(sender_name: str, messages_list: list[str],
                         conv_history: list[dict] | None = None,
                         avoid: str | None = None) -> str:
    """מקבל הודעות חדשות + היסטוריה אופציונלית ומחזיר תגובה קצרה בסגנון דניאל.
    avoid — ניסוח קודם שיש לנסח אחרת (לכפתור 'נסח מחדש')."""
    name = sender_name or "הלקוח"

    # בנה הקשר שיחה קודמת (רק אם יש)
    history_block = ""
    if conv_history:
        lines = [f"{'דניאל' if m['is_daniel'] else name}: {m['text']}" for m in conv_history]
        history_block = "=== שיחה קודמת ===\n" + "\n".join(lines) + "\n\n"

    # בנה את ההודעה הנוכחית
    if len(messages_list) == 1:
        current = f"{name}: {messages_list[0]}"
    else:
        msgs_str = "\n".join(f"- {m}" for m in messages_list)
        current = f"{name} שלח:\n{msgs_str}"

    content = history_block + current
    if avoid:
        content += f"\n\n(נסח תשובה שונה מהניסוח הזה: \"{avoid}\")"

    try:
        resp = await anthropic.messages.create(
            model="claude-sonnet-5",
            max_tokens=200,
            system=DANIEL_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        logger.info(f"Claude blocks: {[b.type for b in resp.content]}")
        for block in resp.content:
            if block.type == "text":
                return block.text.strip()
        logger.warning("Claude returned no text block")
        return ""
    except Exception as e:
        logger.error(f"Claude error: {type(e).__name__}: {e}")
        return ""

# ─── Consult-offer detection (מעקב המרות) ────────────────────────────────────
def is_consult_offer(reply: str) -> bool:
    """מזהה אם התשובה מציעה ייעוץ בתשלום."""
    if not reply:
        return False
    return "99" in reply or "ייעוץ" in reply

# ─── Message filtering ────────────────────────────────────────────────────────
_SYSTEM_MSGS = {
    'להתחלה', 'get started', 'התחל', 'start', 'started', 'מתחיל', 'begin',
    'hi', 'hello', 'hey',
}
# ביטויים מרובי מילים של מערכת פייסבוק/אינסטגרם
_SYSTEM_PHRASES = [
    'you missed a call',
    'missed a call from',
    'you can call',
    'within the next',
    'sent an attachment',
    'שלח/ה קובץ',
    'liked your message',
]
_SPAM_WORDS = [
    'seo', 'digital marketing', 'שיתוף פעולה עסקי', 'להציע שיתוף',
    'האתר שלנו', 'מוצר שלנו', 'שירות שלנו', 'קידום אתרים',
    'casino', 'crypto', 'bitcoin', 'investment', 'השקעה מובטחת',
    'הלוואה', 'רווח מהיר',
]

def should_skip_message(text: str) -> tuple[bool, str]:
    """מחזיר (לדלג, סיבה). True = אין צורך לענות."""
    if not text or not text.strip():
        return True, 'empty'
    stripped = text.strip()
    lower = stripped.lower()

    # הודעות מערכת של פייסבוק / קצרות מדי ללא תוכן
    if lower in _SYSTEM_MSGS or len(stripped) <= 2:
        return True, 'system_message'

    # ביטויי מערכת מרובי מילים
    for phrase in _SYSTEM_PHRASES:
        if phrase in lower:
            return True, 'system_message'

    # ספאם / מכירות
    for word in _SPAM_WORDS:
        if word in lower:
            return True, 'spam'

    return False, ''

# ─── Meta API — send ──────────────────────────────────────────────────────────
def explain_meta_error(status: int, body: str) -> str:
    """מתרגם שגיאת Meta להסבר קצר בעברית — מה באמת קרה ומה עושים."""
    try:
        err = json.loads(body).get("error", {})
    except Exception:
        err = {}
    msg  = err.get("message", "") or body[:200]
    code = err.get("code")
    sub  = err.get("error_subcode")

    low = msg.lower()
    if "not admins, developers or testers" in low or "pages_messaging" in low:
        hint = "האפליקציה במצב פיתוח — אפשר להתכתב רק עם אדמין/מפתח/טסטר. צריך אישור pages_messaging ב-App Review"
    elif "outside of allowed window" in low or "24" in low and "window" in low:
        hint = "עברו 24 שעות מההודעה של הלקוח — חלון המענה נסגר"
    elif code == 190 or "access token" in low:
        hint = "הטוקן פג או בוטל — צריך לחדש את META_PAGE_ACCESS_TOKEN"
    elif code == 10 or code == 200:
        hint = "חסרה הרשאה על הדף"
    elif code == 613 or "rate limit" in low:
        hint = "חריגה ממכסת הקריאות — לנסות שוב מאוחר יותר"
    else:
        hint = msg[:150] or f"HTTP {status}"

    detail = f"code={code}" + (f"/{sub}" if sub else "")
    return f"{hint} ({detail})" if code else hint


async def send_meta_message(sender_id: str, text: str, platform: str) -> tuple[bool, str]:
    """שולח הודעה ללקוח. מחזיר (הצליח, סיבת הכישלון בעברית)."""
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
            if resp.status_code == 200:
                return True, ""
            reason = explain_meta_error(resp.status_code, resp.text)
            logger.error(
                f"Meta send failed [{platform}] HTTP {resp.status_code}: {resp.text[:400]}"
            )
            return False, reason
    except Exception as e:
        logger.error(f"Meta send error: {type(e).__name__}: {e}")
        return False, f"שגיאת רשת ({type(e).__name__})"

# ─── Thank-you detection ─────────────────────────────────────────────────────
_THANKS_WORDS = [
    'תודה', 'תודות', 'תנקיו', 'תנקס',
    'thanks', 'thank you', 'thank u', 'thanku', 'ty', 'thx', 'tyvm', 'tysm',
    'merci', 'gracias', 'danke',
]
# קריאות/אישורים שיכולים לבוא לפני "תודה" בלי לשנות את המשמעות
_POSITIVE_EXCL = [
    'וואו', 'wow', 'יופי', 'מעולה', 'נהדר', 'כיף', 'מגניב',
    'אחלה', 'סבבה', 'ממש', 'מדהים', 'מושלם', 'נכון', 'בדיוק',
    'אוקי', 'אוקיי', 'ok', 'okay', 'great',
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

    # הסר קריאות חיוביות מתחילת ההודעה (וואו. תודה רבה → תודה רבה)
    temp = no_punct
    for excl in _POSITIVE_EXCL:
        if temp.startswith(excl):
            temp = temp[len(excl):].strip()
            break  # הסר רק אחת

    # בדוק אם מה שנשאר הוא תודה בלבד
    no_punct = temp

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
            logger.warning(
                f"Like failed [{platform}] HTTP {resp.status_code}: "
                f"{explain_meta_error(resp.status_code, resp.text)} | {resp.text[:300]}"
            )
            return False
    except Exception as e:
        logger.error(f"Meta like error: {type(e).__name__}: {e}")
        return False


# ─── Telegram message formatting ──────────────────────────────────────────────
PLATFORM_EMOJI = {"instagram": "📸", "facebook": "💙"}

def build_telegram_text(msg: dict) -> str:
    emoji = PLATFORM_EMOJI.get(msg["platform"], "💬")
    platform_name = "Instagram" if msg["platform"] == "instagram" else "Facebook"
    # escape — טקסט מהמשתמש עלול להכיל < > & שישברו את parse_mode=HTML (או יזייפו עיצוב)
    name = html.escape(msg["sender_name"] or "משתמש")
    all_msgs = [html.escape(m) for m in msg.get("all_messages", [msg["message_text"]])]
    reply = html.escape(msg["suggested_reply"] or "") or "⏳ מייצר תשובה..."

    if len(all_msgs) > 1:
        msgs_block = "\n".join(f"▸ {m}" for m in all_msgs)
        header = f"{emoji} <b>{platform_name}</b> • {name} <i>({len(all_msgs)} הודעות)</i>"
    else:
        msgs_block = all_msgs[0]
        header = f"{emoji} <b>{platform_name}</b> • {name}"

    return (
        f"{header}\n"
        f"─────────────────\n"
        f"{msgs_block}\n"
        f"─────────────────\n"
        f"💬 <b>תשובה מוצעת:</b>\n"
        f"{reply}"
    )

def build_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ שלח", callback_data=f"send:{msg_id}"),
            InlineKeyboardButton("✏️ ערוך ושלח", callback_data=f"edit:{msg_id}"),
            InlineKeyboardButton("⏭️ דלג", callback_data=f"skip:{msg_id}"),
        ],
        [InlineKeyboardButton("🔄 נסח מחדש", callback_data=f"regen:{msg_id}")],
    ])

# ─── Broadcast ────────────────────────────────────────────────────────────────
async def broadcast(bot, text: str, **kwargs) -> list[tuple[int, int]]:
    """שולח הודעה לכל הנמענים. מחזיר [(chat_id, telegram_msg_id), ...]."""
    sent = []
    for cid in CHAT_IDS:
        try:
            m = await bot.send_message(chat_id=cid, text=text, **kwargs)
            sent.append((cid, m.message_id))
        except Exception as e:
            logger.error(f"Telegram send error to {cid}: {type(e).__name__}: {e}")
    return sent

def record_deliveries(conn, db_id: int, sent: list[tuple[int, int]]):
    conn.executemany(
        "INSERT OR REPLACE INTO deliveries (message_id, chat_id, telegram_msg_id) VALUES (?,?,?)",
        [(db_id, cid, mid) for cid, mid in sent]
    )
    conn.commit()

async def sync_others(bot, db_id: int, text: str, except_chat_id: int,
                      keyboard: InlineKeyboardMarkup | None = None):
    """מעדכן את ההעתקים אצל שאר הנמענים (בלי מי שביצע את הפעולה)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT chat_id, telegram_msg_id FROM deliveries WHERE message_id=? AND chat_id!=?",
        (db_id, except_chat_id)
    ).fetchall()
    conn.close()
    for r in rows:
        try:
            await bot.edit_message_text(
                chat_id=r["chat_id"], message_id=r["telegram_msg_id"],
                text=text, parse_mode="HTML", reply_markup=keyboard
            )
        except Exception as e:
            # "message is not modified" ודומיו — לא קריטי
            logger.info(f"sync_others skip {r['chat_id']}: {type(e).__name__}")

# ─── Scanner ──────────────────────────────────────────────────────────────────
async def scan_and_notify(bot, since_override: datetime | None = None):
    """הסריקה הראשית — מושכת DMs חדשים ושולחת לטלגרם."""
    logger.info("Starting scan...")
    since = since_override if since_override is not None else get_last_scan()
    now = datetime.now(timezone.utc)

    messages, success = await fetch_new_messages(since)
    logger.info(f"Found {len(messages)} new messages (api_success={success})")

    if not messages:
        return

    conn = get_db()
    new_count = 0
    liked_names = []

    # ─── קיבוץ לפי שולח+פלטפורמה ────────────────────────────────────────
    # הודעות מגיעות מהחדשה לישנה; קובצות לפי שולח, מוצגות מהישנה לחדשה
    from collections import OrderedDict
    groups: OrderedDict[tuple, list] = OrderedDict()
    for msg in messages:
        key = (msg["sender_id"], msg["platform"])
        groups.setdefault(key, []).append(msg)

    for (sender_id, platform), group_msgs in groups.items():
        sender_name = group_msgs[0].get("sender_name", "")

        # סנן הודעות שכבר עובדו
        new_msgs = [
            m for m in group_msgs
            if not conn.execute(
                "SELECT 1 FROM messages WHERE msg_id=?", (m["msg_id"],)
            ).fetchone()
        ]
        if not new_msgs:
            continue

        # הצג מהישנה לחדשה
        new_msgs_asc = list(reversed(new_msgs))
        all_texts = [m["message_text"] for m in new_msgs_asc]
        combined_text = " | ".join(all_texts)

        # ─── פילטר: מערכת / ספאם ──────────────────────────────────────
        skip, reason = should_skip_message(combined_text)
        if skip:
            for m in new_msgs:
                conn.execute(
                    "INSERT OR IGNORE INTO messages "
                    "(msg_id,sender_id,sender_name,platform,message_text,status) "
                    "VALUES (?,?,?,?,?,'skipped')",
                    (m["msg_id"], sender_id, sender_name, platform, m["message_text"])
                )
            conn.commit()
            logger.info(f"Skipped ({reason}): {combined_text[:50]}")
            continue

        # ─── לייק אוטומטי אם כולן תודה ───────────────────────────────
        if all(is_thank_you_only(t) for t in all_texts):
            liked = await send_meta_like(new_msgs[0]["msg_id"], sender_id, platform)
            status = "liked" if liked else "skipped"
            for m in new_msgs:
                conn.execute(
                    "INSERT OR IGNORE INTO messages "
                    "(msg_id,sender_id,sender_name,platform,message_text,status) "
                    "VALUES (?,?,?,?,?,?)",
                    (m["msg_id"], sender_id, sender_name, platform, m["message_text"], status)
                )
            conn.commit()
            if liked:
                liked_names.append(sender_name or "משתמש")
            continue

        # ─── ייצר תגובה אחת לכל ההודעות יחד ────────────────────────
        conv_history = group_msgs[0].get("conv_history") or []
        suggested = await generate_reply(sender_name or "הלקוח", all_texts, conv_history)

        # שמור את ההודעה הראשונה (הכי חדשה) כ-primary ב-DB
        primary = new_msgs[0]
        cur = conn.execute(
            "INSERT INTO messages "
            "(msg_id,sender_id,sender_name,platform,message_text,suggested_reply,offered_consult) "
            "VALUES (?,?,?,?,?,?,?)",
            (primary["msg_id"], sender_id, sender_name, platform,
             combined_text, suggested, int(is_consult_offer(suggested)))
        )
        conn.commit()
        db_id = cur.lastrowid

        # סמן שאר ההודעות כ-grouped
        for m in new_msgs[1:]:
            conn.execute(
                "INSERT OR IGNORE INTO messages "
                "(msg_id,sender_id,sender_name,platform,message_text,status) "
                "VALUES (?,?,?,?,?,'grouped')",
                (m["msg_id"], sender_id, sender_name, platform, m["message_text"])
            )
        conn.commit()

        # שלח לטלגרם עם כל ההודעות גלויות
        display_msg = {
            "msg_id": primary["msg_id"],
            "sender_id": sender_id,
            "sender_name": sender_name,
            "platform": platform,
            "message_text": combined_text,
            "all_messages": all_texts,
            "suggested_reply": suggested,
        }
        sent = await broadcast(
            bot,
            build_telegram_text(display_msg),
            parse_mode="HTML",
            reply_markup=build_keyboard(db_id),
        )
        if sent:
            record_deliveries(conn, db_id, sent)
            conn.execute(
                "UPDATE messages SET telegram_msg_id=? WHERE id=?",
                (sent[0][1], db_id)
            )
            conn.commit()
            new_count += 1

    conn.close()

    # שלח סיכום לייקים אם היו
    if liked_names:
        names_str = ", ".join(liked_names[:15])
        suffix = f" ועוד {len(liked_names)-15}" if len(liked_names) > 15 else ""
        await broadcast(
            bot,
            f"❤️ לייק אוטומטי נשלח ל-{len(liked_names)} הודעות תודה:\n{names_str}{suffix}"
        )

    # מקדם last_scan רק אם ה-API הצליח — כדי לא לדלג על הודעות בזמן תקלות
    if success:
        set_last_scan(now)
        logger.info(f"last_scan updated to {now.isoformat()}")
    else:
        logger.warning("Skipping last_scan update — all API calls failed")

    if new_count > 0:
        logger.info(f"Sent {new_count} messages to Telegram")

# ─── Weekly digest ────────────────────────────────────────────────────────────
async def send_weekly_digest(bot):
    """סיכום שבועי: השאלות הנפוצות + רעיונות לסרטונים על בסיס מה שאנשים שואלים."""
    conn = get_db()
    rows = conn.execute(
        "SELECT message_text FROM messages "
        "WHERE created_at >= datetime('now','-7 days') AND status != 'grouped' "
        "ORDER BY created_at DESC LIMIT 150"
    ).fetchall()
    conn.close()

    texts = [r["message_text"] for r in rows if r["message_text"] and r["message_text"].strip()]
    if len(texts) < 3:
        await broadcast(bot, "📋 דוח שבועי: פחות מ-3 הודעות השבוע — אין מספיק נתונים לסיכום.")
        return

    joined = "\n".join(f"- {t[:200]}" for t in texts)
    prompt = (
        "אלה הודעות DM שקיבל דניאל ('הלוחש לצמחים') מהעוקבים בשבוע האחרון:\n\n"
        f"{joined}\n\n"
        "כתוב סיכום קצר בעברית:\n"
        "1. 3-5 הנושאים/שאלות הכי נפוצים (עם ספירה משוערת)\n"
        "2. 3 רעיונות לסרטונים שיענו על השאלות האלה (כל רעיון בשורה, עם הוק מוצע)\n"
        "3. תובנה אחת מעניינת אם יש\n"
        "קצר וישיר, בלי פתיחות."
    )
    try:
        resp = await anthropic.messages.create(
            model="claude-sonnet-5",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = next((b.text for b in resp.content if b.type == "text"), "")
    except Exception as e:
        logger.error(f"Digest Claude error: {type(e).__name__}")
        summary = ""

    if not summary:
        await broadcast(bot, "❌ שגיאה ביצירת הדוח השבועי")
        return

    # בלי parse_mode — הטקסט מבוסס על הודעות משתמשים
    await broadcast(
        bot,
        f"📋 דוח שבועי — {len(texts)} הודעות ב-7 הימים האחרונים\n\n{summary}"
    )

# ─── Telegram handlers ────────────────────────────────────────────────────────
async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # רק נמענים מורשים
    if query.from_user.id not in AUTHORIZED_IDS:
        return

    actor = display_name(query.from_user)
    # מציינים מי טיפל רק כששניים או יותר מחוברים
    by = f" (על ידי {html.escape(actor)})" if len(CHAT_IDS) > 1 else ""

    action, msg_id = query.data.split(":")
    msg_id = int(msg_id)

    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
    conn.close()

    if not row or row["status"] not in ("pending",):
        await query.edit_message_reply_markup(reply_markup=None)
        return

    if action == "send":
        # אטומי — תופס את ההודעה לפני השליחה, מונע שליחה כפולה בלחיצה מהירה פעמיים
        conn = get_db()
        cur = conn.execute(
            "UPDATE messages SET status='sending' WHERE id=? AND status='pending'",
            (msg_id,)
        )
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return  # כבר טופלה

        success, reason = await send_meta_message(
            row["sender_id"], row["suggested_reply"], row["platform"]
        )
        status_line = (
            f"✅ נשלח!{by}" if success
            else f"❌ שגיאה בשליחה{by}\n<i>{html.escape(reason)}</i>"
        )
        new_text = build_telegram_text(dict(row)) + f"\n\n{status_line}"
        await query.edit_message_text(new_text, parse_mode="HTML")
        await sync_others(context.bot, msg_id, new_text, query.from_user.id)
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
        # מיידעים את השני שמישהו עורך — אבל משאירים לו כפתורים,
        # למקרה שהעורך יתחרט. שליחה כפולה נמנעת ממילא ע"י נעילת ה-status.
        if by:
            await sync_others(
                context.bot, msg_id,
                build_telegram_text(dict(row)) + f"\n\n✏️ {html.escape(actor)} עורך תשובה...",
                query.from_user.id, build_keyboard(msg_id)
            )

    elif action == "regen":
        # נסח מחדש — מבקש מ-Claude ניסוח חלופי ומעדכן את ההודעה בטלגרם
        texts = row["message_text"].split(" | ")
        new_reply = await generate_reply(
            row["sender_name"] or "הלקוח", texts, avoid=row["suggested_reply"]
        )
        if not new_reply:
            await context.bot.send_message(
                chat_id=query.message.chat_id, text="❌ שגיאה בניסוח מחדש — נסה שוב"
            )
            return
        conn = get_db()
        conn.execute(
            "UPDATE messages SET suggested_reply=?, offered_consult=? WHERE id=?",
            (new_reply, int(is_consult_offer(new_reply)), msg_id)
        )
        conn.commit()
        conn.close()
        display = dict(row)
        display["suggested_reply"] = new_reply
        display["all_messages"] = texts
        regen_text = build_telegram_text(display)
        await query.edit_message_text(
            regen_text, parse_mode="HTML",
            reply_markup=build_keyboard(msg_id)
        )
        await sync_others(context.bot, msg_id, regen_text, query.from_user.id,
                          build_keyboard(msg_id))

    elif action == "skip":
        new_text = build_telegram_text(dict(row)) + f"\n\n⏭️ דולג{by}"
        await query.edit_message_text(new_text, parse_mode="HTML")
        await sync_others(context.bot, msg_id, new_text, query.from_user.id)
        conn = get_db()
        conn.execute("UPDATE messages SET status='skipped' WHERE id=?", (msg_id,))
        conn.commit()
        conn.close()


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מקבל טקסט כשדניאל (או אבירם) עורך תשובה."""
    if update.effective_user.id not in AUTHORIZED_IDS:
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

    # אם הנמען השני כבר טיפל בהודעה בזמן שכתבת — לא שולחים פעמיים
    conn = get_db()
    cur = conn.execute(
        "UPDATE messages SET status='sending' WHERE id=? AND status='pending'",
        (editing_id,)
    )
    conn.commit()
    conn.close()
    if cur.rowcount == 0:
        await update.message.reply_text("⚠️ ההודעה כבר טופלה — לא נשלח שוב")
        return

    success, reason = await send_meta_message(row["sender_id"], new_reply, row["platform"])
    if success:
        await update.message.reply_text("✅ נשלח!")
        conn = get_db()
        # שומר את ההצעה המקורית של הבוט — חומר למידה (/learn)
        conn.execute(
            "UPDATE messages SET status='sent', original_suggestion=suggested_reply, "
            "suggested_reply=?, offered_consult=? WHERE id=?",
            (new_reply, int(is_consult_offer(new_reply)), editing_id)
        )
        conn.commit()
        conn.close()
        # מעדכן את כל ההעתקים (כולל של העורך) — התשובה שנשלחה בפועל, בלי כפתורים
        actor = display_name(update.effective_user)
        by = f" (על ידי {html.escape(actor)})" if len(CHAT_IDS) > 1 else ""
        display = dict(row)
        display["suggested_reply"] = new_reply
        await sync_others(
            context.bot, editing_id,
            build_telegram_text(display) + f"\n\n✅ נשלח (נערך){by}",
            except_chat_id=0
        )
    else:
        await update.message.reply_text(f"❌ שגיאה בשליחה — {reason}\nנסה שוב")
        conn = get_db()
        conn.execute("UPDATE messages SET status='pending' WHERE id=?", (editing_id,))
        conn.commit()
        conn.close()
        context.user_data["editing_id"] = editing_id  # נסה שוב


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /scan — מציגה תפריט סריקה."""
    if update.effective_user.id not in AUTHORIZED_IDS:
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱️ מאז הסריקה האחרונה", callback_data="scan:auto")],
        [InlineKeyboardButton("🕐 24 שעות אחרונות",    callback_data="scan:1")],
        [InlineKeyboardButton("📅 שבוע אחרון",          callback_data="scan:7")],
        [InlineKeyboardButton("🗓️ חודש אחרון (30 יום)", callback_data="scan:30")],
        [InlineKeyboardButton("📦 סריקה מלאה (90 יום)", callback_data="scan:90")],
    ])
    last = get_last_scan()
    await update.message.reply_text(
        f"🔍 <b>בחר טווח סריקה</b>\n"
        f"סריקה אחרונה: {last.strftime('%d/%m %H:%M')}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def handle_scan_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בבחירת טווח הסריקה."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in AUTHORIZED_IDS:
        return

    choice = query.data.split(":")[1]
    labels = {"auto": "מאז הסריקה האחרונה", "1": "24 שעות", "7": "שבוע", "30": "חודש", "90": "90 יום"}

    if choice == "auto":
        since = None  # scan_and_notify ישתמש ב-last_scan
    else:
        since = datetime.now(timezone.utc) - timedelta(days=int(choice))

    await query.edit_message_text(f"🔍 סורק — {labels.get(choice, choice)}...")
    await scan_and_notify(context.bot, since_override=since)
    await broadcast(context.bot, "✅ סריקה הושלמה")


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /reset [ימים] — מאפס את חלון הסריקה N ימים אחורה (ברירת מחדל: 30)."""
    if update.effective_user.id not in AUTHORIZED_IDS:
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


async def cmd_clear_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /clear_db — מוחק את כל ההודעות השמורות במסד הנתונים ומאפס את הסריקה."""
    if update.effective_user.id not in AUTHORIZED_IDS:
        return
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.execute("DELETE FROM messages")
    conn.commit()
    days = 90
    if context.args:
        try:
            days = int(context.args[0])
        except ValueError:
            pass
    new_since = datetime.now(timezone.utc) - timedelta(days=days)
    set_last_scan(new_since)
    await update.message.reply_text(
        f"🗑️ נמחקו {count} הודעות מהמסד.\n"
        f"חלון הסריקה אופס ל-{days} ימים אחורה.\n"
        f"הרץ /scan עכשיו כדי לסרוק מחדש."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /status — מציגה סטטיסטיקה."""
    if update.effective_user.id not in AUTHORIZED_IDS:
        return
    conn = get_db()
    pending = conn.execute("SELECT COUNT(*) FROM messages WHERE status='pending'").fetchone()[0]
    sent    = conn.execute("SELECT COUNT(*) FROM messages WHERE status='sent'").fetchone()[0]
    skipped = conn.execute("SELECT COUNT(*) FROM messages WHERE status='skipped'").fetchone()[0]
    liked   = conn.execute("SELECT COUNT(*) FROM messages WHERE status='liked'").fetchone()[0]
    consult_sent = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status='sent' AND offered_consult=1"
    ).fetchone()[0]
    consult_month = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE status='sent' AND offered_consult=1 "
        "AND created_at >= datetime('now','-30 days')"
    ).fetchone()[0]
    last    = get_last_scan()
    conn.close()
    await update.message.reply_text(
        f"📊 סטטוס\n"
        f"⏳ ממתין: {pending}\n"
        f"✅ נשלח: {sent}\n"
        f"⏭️ דולג: {skipped}\n"
        f"❤️ לייקים: {liked}\n"
        f"💰 הצעות ייעוץ שנשלחו: {consult_sent} (החודש: {consult_month})\n"
        f"🕐 סריקה אחרונה: {last.strftime('%d/%m %H:%M')}"
    )

async def cmd_learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /learn — מציגה את התיקונים האחרונים של דניאל (הבוט הציע ≠ דניאל שלח).
    זה חומר הלמידה לריענון בנק הדוגמאות בפרומפט."""
    if update.effective_user.id not in AUTHORIZED_IDS:
        return
    conn = get_db()
    rows = conn.execute(
        "SELECT sender_name, message_text, original_suggestion, suggested_reply, created_at "
        "FROM messages WHERE original_suggestion IS NOT NULL AND status='sent' "
        "AND original_suggestion != suggested_reply "
        "ORDER BY created_at DESC LIMIT 30"
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text(
            "📚 אין עדיין תיקונים.\n"
            "מעכשיו, כל פעם שתלחץ ✏️ ותשנה תשובה — התיקון יישמר כאן.\n"
            "פעם בחודש שלח את הפלט של /learn לאבירם לריענון הפרומפט."
        )
        return

    blocks = []
    for r in rows:
        blocks.append(
            f"❓ {r['message_text'][:200]}\n"
            f"🤖 הבוט הציע: {r['original_suggestion'][:200]}\n"
            f"✅ דניאל שלח: {r['suggested_reply'][:200]}"
        )
    text = (
        f"📚 {len(rows)} תיקונים אחרונים — העתק ושלח לאבירם לריענון הפרומפט:\n\n"
        + "\n──────────\n".join(blocks)
    )
    # טלגרם מוגבל ל-4096 תווים להודעה — פיצול
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i + 4000])


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודה /digest — מפיק דוח שבועי מיידי."""
    if update.effective_user.id not in AUTHORIZED_IDS:
        return
    await update.message.reply_text("📋 מכין דוח שבועי...")
    await send_weekly_digest(context.bot)

# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    init_db()
    logger.info("DB initialized")

    # בנה את אפליקציית הטלגרם
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CallbackQueryHandler(handle_scan_choice, pattern=r"^scan:"))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("clear_db", cmd_clear_db))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("learn", cmd_learn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Scheduler לסריקה אוטומטית
    scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")
    scheduler.add_job(
        scan_and_notify,
        "cron",
        hour="9,21",   # 9 בבוקר ו-9 בערב
        kwargs={"bot": app.bot},
    )
    # דוח שבועי — יום ראשון 09:30
    scheduler.add_job(
        send_weekly_digest,
        "cron",
        day_of_week="sun",
        hour=9, minute=30,
        kwargs={"bot": app.bot},
    )
    scheduler.start()
    logger.info(f"Scheduler started — scans 09:00/21:00, weekly digest Sun 09:30 Israel time")

    # הפעל את הבוט עם polling
    async with app:
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("Bot is running. Press Ctrl+C to stop.")
        await asyncio.Event().wait()  # שמור רץ לנצח

if __name__ == "__main__":
    asyncio.run(main())
