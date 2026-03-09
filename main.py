from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime, timedelta

app = FastAPI()

LINE_TOKEN = os.environ.get("LINE_TOKEN")
LINE_SECRET = os.environ.get("LINE_SECRET")

line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

players = []
group_ids = set()

THAILAND_TZ = pytz.timezone("Asia/Bangkok")

THAI_MONTHS = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค."
}

def get_next_thursday():
    """หาวันพฤหัสที่ใกล้ที่สุด"""
    now = datetime.now(THAILAND_TZ)
    days_ahead = 3 - now.weekday()  # พฤหัส = weekday 3
    if days_ahead <= 0:
        days_ahead += 7
    next_thu = now + timedelta(days=days_ahead)
    return next_thu

def format_thursday():
    """แปลงวันพฤหัสเป็นข้อความภาษาไทย เช่น พฤหัส 13 มี.ค."""
    thu = get_next_thursday()
    return f"พฤหัส {thu.day} {THAI_MONTHS[thu.month]}"

def get_display_name(event):
    user_id = event.source.user_id
    try:
        source_type = event.source.type
        if source_type == "group":
            member = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
            return member.display_name
        elif source_type == "room":
            member = line_bot_api.get_room_member_profile(event.source.room_id, user_id)
            return member.display_name
        else:
            profile = line_bot_api.get_profile(user_id)
            return profile.display_name
    except:
        return "ไม่ทราบชื่อ"

def send_wednesday_invite():
    thu_label = format_thursday()
    msg = (f"🏸 สวัสดีตอนเช้า!\n"
           f"พรุ่งนี้ {thu_label} มาตีแบดกันนะ 💪\n\n"
           f"พิมพ์ ไป → ลงชื่อ\n"
           f"พิมพ์ ไป ชื่อ → ลงชื่อแทนเพื่อน\n"
           f"พิมพ์ ไม่ไป → ถอนชื่อ\n"
           f"พิมพ์ ใคร → ดูรายชื่อ")
    for gid in group_ids:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
        except Exception as e:
            print(f"Error sending invite to {gid}: {e}")

def reset_thursday():
    count = len(players)
    players.clear()
    msg = f"🗑️ ล้างรายชื่อแล้ว ({count} คน)\nพบกันใหม่สัปดาห์หน้านะ! 🏸"
    for gid in group_ids:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
        except Exception as e:
            print(f"Error sending reset to {gid}: {e}")

scheduler = BackgroundScheduler(timezone=THAILAND_TZ)
scheduler.add_job(send_wednesday_invite, CronTrigger(day_of_week="wed", hour=8, minute=0, timezone=THAILAND_TZ))
scheduler.add_job(reset_thursday, CronTrigger(day_of_week="thu", hour=22, minute=0, timezone=THAILAND_TZ))
scheduler.start()

@app.get("/")
def root():
    return {"status": "Badminton Bot is running!"}

@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    text_lower = text.lower()
    user_id = event.source.user_id

    if event.source.type == "group":
        group_ids.add(event.source.group_id)

    my_name = get_display_name(event)
    thu_label = format_thursday()

    # --- ลงชื่อตัวเอง ---
    if text_lower in ["ไป", "+", "in"]:
        if not any(p["id"] == user_id for p in players):
            players.append({"id": user_id, "name": my_name, "by": None})
            reply = f"✅ {my_name} ลงชื่อแล้ว!\n🏸 {thu_label} ตอนนี้มี {len(players)} คน"
        else:
            reply = f"⚠️ {my_name} ลงชื่อไว้แล้วนะ!"

    # --- ลงชื่อแทนเพื่อน: "ไป ชื่อเพื่อน" ---
    elif text_lower.startswith("ไป ") and len(text) > 3:
        friend_name = text[3:].strip()
        if not friend_name:
            reply = "❓ ระบุชื่อเพื่อนด้วยนะ เช่น ไป สมชาย"
        elif any(p["name"].lower() == friend_name.lower() for p in players):
            reply = f"⚠️ {friend_name} ลงชื่อไว้แล้วนะ!"
        else:
            players.append({"id": f"guest_{friend_name}", "name": friend_name, "by": my_name})
            reply = f"✅ {my_name} ลงชื่อให้ {friend_name} แล้ว!\n🏸 {thu_label} ตอนนี้มี {len(players)} คน"

    # --- ถอนชื่อตัวเอง ---
    elif text_lower in ["ไม่ไป", "-", "out"]:
        before = len(players)
        players[:] = [p for p in players if p["id"] != user_id]
        if len(players) < before:
            reply = f"❌ {my_name} ถอนชื่อแล้ว\n🏸 {thu_label} เหลือ {len(players)} คน"
        else:
            reply = f"ยังไม่ได้ลงชื่อเลยนะ {my_name}"

    # --- ถอนชื่อแทนเพื่อน: "ไม่ไป ชื่อเพื่อน" ---
    elif text_lower.startswith("ไม่ไป ") and len(text) > 6:
        friend_name = text[6:].strip()
        before = len(players)
        players[:] = [p for p in players if p["name"].lower() != friend_name.lower()]
        if len(players) < before:
            reply = f"❌ {my_name} ถอนชื่อให้ {friend_name} แล้ว\n🏸 {thu_label} เหลือ {len(players)} คน"
        else:
            reply = f"ไม่เจอชื่อ {friend_name} ในรายชื่อนะ"

    # --- ดูรายชื่อ ---
    elif text_lower in ["ใคร", "รายชื่อ", "list"]:
        if players:
            lines = []
            for i, p in enumerate(players):
                if p["by"]:
                    lines.append(f"{i+1}. {p['name']} (ลงให้โดย {p['by']})")
                else:
                    lines.append(f"{i+1}. {p['name']}")
            reply = f"🏸 {thu_label} มี {len(players)} คน:\n" + "\n".join(lines)
        else:
            reply = f"ยังไม่มีใครลงชื่อ {thu_label} เลย 😅"

    # --- เคลียร์ ---
    elif text_lower in ["เคลียร์", "clear", "reset"]:
        players.clear()
        reply = "🗑️ เคลียร์รายชื่อแล้ว!"

    # --- help ---
    elif text_lower in ["help", "ช่วยเหลือ", "?"]:
        reply = (f"🏸 คำสั่ง Bot ตีแบด ({thu_label}):\n"
                 "ไป → ลงชื่อตัวเอง\n"
                 "ไป ชื่อ → ลงชื่อแทนเพื่อน\n"
                 "ไม่ไป → ถอนชื่อตัวเอง\n"
                 "ไม่ไป ชื่อ → ถอนชื่อแทนเพื่อน\n"
                 "ใคร → ดูรายชื่อทั้งหมด\n"
                 "เคลียร์ → ล้างรายชื่อ")
    else:
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )
