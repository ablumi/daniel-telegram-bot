# מדריך הגדרה — טלגרם DM Bot
## הלוחש לצמחים

הבוט סורק Instagram + Facebook פעמיים ביום (9:00 + 21:00), מייצר תשובות מוצעות, ושולח לדניאל בטלגרם עם כפתורים לאישור.

---

## ✅ ערכים מאושרים (כבר ידועים)

| משתנה | ערך |
|---|---|
| `FACEBOOK_PAGE_ID` | `1103082102889183` |
| `INSTAGRAM_ACCOUNT_ID` | `753951067792932` |
| Business ID | `3949184355323776` |
| Meta App ID | `1390706479789623` |
| `TELEGRAM_CHAT_ID` | `8997252631` (Daniel's Telegram ID) |

---

## שלב 1: צור/חדש בוט טלגרם

> ⚠️ הטוקן הישן נחשף — **חייב ליצור חדש**

1. פתח טלגרם וחפש: **@BotFather**
2. שלח `/revoke` ← בחר את הבוט הישן → אשר (מבטל את הטוקן הישן)
3. שלח `/token` ← בחר את הבוט → קבל **Bot Token חדש**
   (או `/newbot` אם תרצה בוט חדש לגמרי)
4. שמור את ה-Token החדש ל-`TELEGRAM_BOT_TOKEN`

---

## שלב 2: קבל Page Access Token (הכי חשוב!)

**אבירם בלומי** צריך לעשות זאת מה-browser שלו (לא של דניאל):

1. פתח: `https://developers.facebook.com/tools/explorer/?app_id=1390706479789623`
   - ודא שאתה מחובר כ-**Aviram Blumi** (לא כ-Daniel)
2. תחת "Meta App" — בחר **lochesh-plants-bot**
3. תחת "User or Page" — בחר **User Token**
4. תחת Permissions, הוסף:
   - ✅ `pages_messaging`
   - ✅ `pages_show_list`
   - ✅ `pages_read_engagement`
5. לחץ **"Generate Access Token"**
6. בפופאפ שנפתח — אשר את כל ההרשאות ובחר את דף **"דניאל הלוחש לצמחים"**
7. חזור ל-Explorer, שנה URL ל: `me/accounts`
8. לחץ **Submit**
9. בתשובה תראה את דף "דניאל הלוחש לצמחים" עם שדה `access_token`
10. **זהו ה-`META_PAGE_ACCESS_TOKEN`** — שמור אותו!

> **למה אבירם ולא דניאל?** אבירם הוא Admin של ה-Meta App. בחשבון של אבירם, `/me/accounts` יחזיר את דף "דניאל הלוחש לצמחים" כי אבירם הוא גם Full Access Admin של הדף.

### המרה ל-Long-lived Token (60 יום):

```bash
curl "https://graph.facebook.com/v19.0/oauth/access_token\
?grant_type=fb_exchange_token\
&client_id=1390706479789623\
&client_secret=YOUR_APP_SECRET\
&fb_exchange_token=PAGE_TOKEN_FROM_ABOVE"
```

App Secret נמצא ב: developers.facebook.com → lochesh-plants-bot → App settings → Basic

---

## שלב 3: Deploy על Render

1. העלה את תיקיית `telegram-bot/` ל-GitHub
2. פתח https://render.com → "New" → **"Background Worker"** (לא Web Service)
3. חבר ל-GitHub repo שהעלת
4. Render יזהה את `render.yaml` אוטומטית
5. **הגדר Environment Variables** (Settings → Environment):

| שם משתנה | ערך |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token חדש מ-BotFather |
| `TELEGRAM_CHAT_ID` | `8997252631` |
| `META_PAGE_ACCESS_TOKEN` | Long-lived token מ-שלב 2 |
| `INSTAGRAM_ACCOUNT_ID` | `753951067792932` |
| `FACEBOOK_PAGE_ID` | `1103082102889183` |
| `ANTHROPIC_API_KEY` | מ-console.anthropic.com |

6. לחץ **"Deploy"**

> ✅ Background Worker על Render **לא נרדם** — רץ 24/7 בחינם.

---

## שלב 4: App Review לאינסטגרם (חובה לפרודקשן)

כרגע הבוט עובד עם **Facebook Messenger DMs** בלבד.  
לגישה ל-**Instagram DMs** — Meta דורשת App Review:

1. developers.facebook.com → lochesh-plants-bot → App Review → Requests
2. בקש: `instagram_manage_messages`
3. המתן לאישור Meta (בדרך כלל 1-5 ימי עסקים)
4. לאחר אישור — הבוט יסרוק גם Instagram DMs

> בינתיים, הבוט סורק רק **Facebook Messenger** (דניאל הלוחש לצמחים).  
> דניאל מקבל כ-3 Facebook Messenger DMs לפי מה שרואים ב-Business Suite.

---

## בדיקה ראשונה

לאחר Deploy:
1. שלח `/scan` לבוט בטלגרם
2. אם יש DMs שלא נענו — הם יגיעו מיד
3. נסה ללחוץ "שלח" על אחד מהם ובדוק שהגיע

---

## דוגמה להודעה בטלגרם

```
📘 Facebook Messenger • מיכל כהן
─────────────────
הפיקוס שלי מפיל עלים מה עושים?
─────────────────
💬 תשובה מוצעת:
פיקוס שמפיל עלים זה לרוב שינוי מקום או רוח. אם הזזת אותו לאחרונה — החזר. אם לא — בדוק שאין מזגן ישיר עליו.

[✅ שלח] [✏️ ערוך ושלח] [⏭️ דלג]
```

**לחץ שלח** — התשובה נשלחת ישירות ל-Facebook Messenger  
**לחץ ערוך** — הבוט מבקש ממך תשובה חדשה  
**לחץ דלג** — מסמן כדולג ועובר הלאה

### פקודות ידניות:
- `/scan` — סרוק הודעות עכשיו
- `/status` — כמה הודעות ממתינות / נשלחו / דולגו

---

## עדכון Token אחרי 60 יום

```bash
curl "https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=1390706479789623&client_secret=APP_SECRET&fb_exchange_token=TOKEN_הישן"
```

עדכן ב-Render → Environment → `META_PAGE_ACCESS_TOKEN` → Deploy אוטומטי.

---

## בעיות נפוצות

**הבוט לא מגיב בטלגרם:**
- בדוק שה-TELEGRAM_BOT_TOKEN נכון ב-Render
- בדוק לוגים: Render Dashboard → Logs

**לא מוצא הודעות:**
- ודא שה-IDs נכונים (ראה טבלה למעלה)
- Token עלול להיות פג — חדש אותו

**שגיאה "Forbidden" בשליחה:**
- Token פג — חדש אותו
- ודא ש-pages_messaging גרנטד על הדף
