# מדריך הגדרה — טלגרם DM Bot
## הלוחש לצמחים

הבוט סורק Instagram + Facebook פעמיים ביום (9:00 + 21:00 שעון ישראל), מייצר תשובות מוצעות,
ושולח אותן בטלגרם עם כפתורי אישור. אפשר להגדיר כמה נמענים — כולם מקבלים, כל אחד יכול לענות.

---

## איפה זה רץ

| | |
|---|---|
| פלטפורמה | **Railway** (`railway.com`) |
| חשבון | aviram.blumi@gmail.com |
| פרויקט | `joyful-youthfulness` → סביבה `production` |
| שירות | `daniel-telegram-bot` |
| ריפו | `github.com/ablumi/daniel-telegram-bot`, ענף `main` |
| דיפלוי | אוטומטי בכל push ל-`main` |
| Builder | Railpack (מזהה Python לבד, `python@3.13.14`) |
| אזור | US West |
| Volume | `daniel-telegram-bot-db`, מותקן ב-`/data`, 500MB |
| Restart | On Failure |

> ⚠️ **לא Render.** בעבר תוכנן דיפלוי לרנדר ונשארו שרידים בקוד ובמדריך — זה בוטל.
> בחשבון Render אין שום שירות.

אין קובץ config-as-code (`railway.json`) — כל ההגדרות יושבות בדשבורד של ריילוויי.

---

## ✅ ערכים מאושרים

| משתנה | ערך |
|---|---|
| `FACEBOOK_PAGE_ID` | `1103082102889183` |
| `INSTAGRAM_ACCOUNT_ID` | `753951067792932` |
| Business ID | `3949184355323776` |
| Meta App ID | `1390706479789623` |
| `TELEGRAM_CHAT_IDS` | `68081535` (אבירם) — נמענים נוספים מופרדים בפסיק |

---

## משתני סביבה

בריילוויי: השירות → לשונית **Variables**.

| שם משתנה | ערך |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token מ-BotFather |
| `TELEGRAM_CHAT_IDS` | `68081535` (או כמה, מופרדים בפסיק) |
| `TELEGRAM_CHAT_NAMES` | אופציונלי — שמות לתצוגה באותו סדר, למשל `אבירם,דניאל` |
| `META_PAGE_ACCESS_TOKEN` | Long-lived Page Token (ראה למטה) |
| `INSTAGRAM_ACCOUNT_ID` | `753951067792932` |
| `FACEBOOK_PAGE_ID` | `1103082102889183` |
| `ANTHROPIC_API_KEY` | מ-console.anthropic.com |
| `DB_PATH` | `/data/messages.db` (על ה-volume — לא למחוק, שם יושבות ההודעות) |
| `SCAN_HOURS` | אופציונלי, ברירת מחדל 12 |

`TELEGRAM_CHAT_ID` הישן (יחיד) עדיין נתמך בקוד כתאימות לאחור, ומוגדר כרשת ביטחון.

**שינוי משתנה:** עורכים → Railway מציג "Apply N changes" → לוחצים **Deploy**. הבוט עולה מחדש תוך כדקה.

---

## הוספת נמען נוסף לבוט

כל נמען מקבל את אותן הצעות ויכול לשלוח/לערוך/לדלג. מי שמגיב ראשון מנצח —
אצל השני ההודעה מתעדכנת ל"✅ נשלח (על ידי X)" והכפתורים נעלמים. שליחה כפולה חסומה ברמת ה-DB.

1. הנמען החדש פותח את הבוט בטלגרם ולוחץ **Start**.
   חובה — בלי זה טלגרם חוסם שליחה אליו, ואין שגיאה בולטת, פשוט שקט.
2. הוא שולח `/start` ל-**@userinfobot** ומקבל את ה-ID המספרי שלו.
3. Railway → `daniel-telegram-bot` → Variables:
   - `TELEGRAM_CHAT_IDS` = `68081535,<ID החדש>`
   - `TELEGRAM_CHAT_NAMES` = `אבירם,דניאל` (אותו סדר)
4. **Deploy**.
5. בדיקה: מהחשבון החדש שולחים `/status` לבוט. אם ענה — הוא מחובר.

**להסרת נמען:** מוחקים את ה-ID מהרשימה ו-Deploy.

---

## Page Access Token של Meta

**אבירם** צריך לעשות זאת מהדפדפן שלו (לא דניאל) — הוא ה-Admin של ה-Meta App.

1. פתח: `https://developers.facebook.com/tools/explorer/?app_id=1390706479789623`
   - ודא שאתה מחובר כ-**Aviram Blumi**
2. Meta App → **lochesh-plants-bot**
3. User or Page → **User Token**
4. Permissions: `pages_messaging`, `pages_show_list`, `pages_read_engagement`
5. **Generate Access Token** → אשר → בחר את דף **"דניאל הלוחש לצמחים"**
6. שנה URL ל-`me/accounts` → **Submit**
7. בתשובה, השדה `access_token` של הדף — **זהו ה-`META_PAGE_ACCESS_TOKEN`**

### המרה ל-Long-lived (60 יום)

```bash
curl "https://graph.facebook.com/v19.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=1390706479789623\
&client_secret=YOUR_APP_SECRET\
&fb_exchange_token=PAGE_TOKEN_FROM_ABOVE"
```

App Secret: developers.facebook.com → lochesh-plants-bot → App settings → Basic

**כל 60 יום:** מחדשים ומעדכנים את `META_PAGE_ACCESS_TOKEN` בריילוויי → Deploy.

---

## Instagram — App Review

כרגע הבוט סורק **Facebook Messenger** בלבד. לגישה ל-Instagram DMs צריך אישור של Meta:

1. developers.facebook.com → lochesh-plants-bot → App Review → Requests
2. בקש `instagram_manage_messages`
3. אישור לוקח בדרך כלל 1-5 ימי עסקים

---

## דוגמה להודעה בטלגרם

```
📘 Facebook Messenger • מיכל כהן
─────────────────
הפיקוס שלי מפיל עלים מה עושים?
─────────────────
💬 תשובה מוצעת:
פיקוס שמפיל עלים זה לרוב שינוי מקום או רוח. אם הזזת אותו לאחרונה — החזר.

[✅ שלח] [✏️ ערוך ושלח] [⏭️ דלג]
[🔄 נסח מחדש]
```

**שלח** — נשלח ישירות ללקוח | **ערוך** — כותבים תשובה משלכם ונשלחת
**דלג** — מסמן כדולג | **נסח מחדש** — מבקש מ-Claude ניסוח חלופי

### פקודות

| פקודה | מה היא עושה |
|---|---|
| `/scan` | תפריט סריקה ידנית (מאז אחרונה / 24ש' / שבוע / חודש / 90 יום) |
| `/status` | כמה ממתינות, נשלחו, דולגו |
| `/digest` | דוח שבועי עכשיו — שאלות נפוצות + רעיונות לסרטונים |
| `/learn` | מציג איפה ערכת את הצעות הבוט — חומר לשיפור הפרומפט |
| `/reset` | מאפס את חלון הסריקה |
| `/clear_db` | מוחק את טבלת ההודעות (זהירות) |

---

## בעיות נפוצות

**הבוט לא מגיב בטלגרם**
בדוק `TELEGRAM_BOT_TOKEN` ואת הלוגים: Railway → Deployments → View logs.

**נמען חדש לא מקבל כלום**
הוא לא לחץ Start בבוט, או שה-ID שגוי. הלוגים יראו `Telegram send error to <id>`.

**לא מוצא הודעות**
ה-IDs שגויים, או שה-Page Token פג — חדש אותו.

**שגיאת "Forbidden" בשליחה**
Token פג, או ש-`pages_messaging` לא מאושר על הדף.

**השירות ירד פתאום**
בדוק את מצב החיוב בריילוויי — בטריאל מוגבל השירות נכבה כשנגמר הקרדיט.

---

## נקודות תחזוקה פתוחות

- **Railway בטריאל מוגבל** — ב-21.7.2026 נותרו 29 יום / $4.95. כשייגמר הבוט יורד.
- **הטוקן של הבוט מופיע בלוגים** — ספריית טלגרם מדפיסה URL מלא של כל קריאת API,
  והטוקן הוא חלק מה-URL. כל מי שיש לו גישה ללוגים רואה אותו.
- **רשימת "נושאים עם סרטונים" בפרומפט** (`main.py`) — לרענן פעם בחודש
  מתוך `brain/09_יומן_סרטונים.md`.
