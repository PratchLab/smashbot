from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os, json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime, timedelta

app = FastAPI()

LINE_TOKEN = os.environ.get("LINE_TOKEN")
LINE_SECRET = os.environ.get("LINE_SECRET")

line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

THAILAND_TZ = pytz.timezone("Asia/Bangkok")
DATA_FILE = "/tmp/badminton_data.json"

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {"players": [], "group_ids": []}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False)

def get_next_thursday():
    now = datetime.now(THAILAND_TZ)
    days_ahead = (3 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    next_thu = now + timedelta(days=days_ahead)
    return next_thu.strftime("%-d %b")

def send_wednesday_invite():
    data = load_data()
    msg = ("🏸 สวัสดีตอนเช้า!\n"
           "พรุ่งนี้พฤหัสแล้ว มาตีแบดกันนะ 💪\n\n"
           "พิมพ์ ไป → ลงชื่อตัวเอง\n"
           "พิมพ์ ไป ตุ๊ก → ลงชื่อแทนคนอื่น\n"
           "พิมพ์ ไม่ไป → ถอนชื่อ\n"
           "พิมพ์ ใคร → ดูรายชื่อ")
    for gid in data["group_ids"]:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
        except Exception as e:
            print(f"Error: {e}")

def reset_thursday():
    data = load_data()
    count = len(data["players"])
    data["players"] = []
    save_data(data)
    msg = f"🗑️ ล้างรายชื่อแล้ว ({count} คน)\nพบกันใหม่สัปดาห์หน้านะ! 🏸"
    for gid in data["group_ids"]:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
        except Exception as e:
            print(f"Error: {e}")

scheduler = BackgroundScheduler(timezone=THAILAND_TZ)
scheduler.add_job(send_wednesday_invite, CronTrigger(day_of_week="wed", hour=8, minute=0, timezone=THAILAND_TZ))
scheduler.add_job(reset_thursday, CronTrigger(day_of_week="thu", hour=22, minute=0, timezone=THAILAND_TZ))
scheduler.start()

@app.get("/")
def root():
    data = load_data()
    return {"status": "Badminton Bot is running!", "players": len(data["players"])}

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

    data = load_data()

    # เก็บ group_id อัตโนมัติ
    if event.source.type == "group":
        gid = event.source.group_id
        if gid not in data["group_ids"]:
            data["group_ids"].append(gid)
            save_data(data)

    # ดึงชื่อผู้ส่ง
    try:
        source_type = event.source.type
        if source_type == "group":
            member = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
            sender_name = member.display_name
        elif source_type == "room":
            member = line_bot_api.get_room_member_profile(event.source.room_id, user_id)
            sender_name = member.display_name
        else:
            profile = line_bot_api.get_profile(user_id)
            sender_name = profile.display_name
    except:
        sender_name = "ไม่ทราบชื่อ"

    thu_label = get_next_thursday()
    players = data["players"]

    # --- ไป (ลงชื่อตัวเอง) ---
    if text_lower in ["ไป", "+", "in"]:
        if not any(p["id"] == user_id for p in players):
            players.append({"id": user_id, "name": sender_name})
            save_data(data)
            reply = f"✅ {sender_name} ลงชื่อแล้ว!\n🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน"
        else:
            reply = f"⚠️ {sender_name} ลงชื่อไว้แล้วนะ!"

    # --- ไป ชื่อ (ลงชื่อแทนคนอื่น) ---
    elif text_lower.startswith("ไป ") and len(text) > 3:
        proxy_name = text[3:].strip()  # ตัด "ไป " ออก เอาแค่ชื่อ
        # เช็คว่าชื่อนี้ลงไว้แล้วหรือยัง (เช็คจากชื่อ)
        if not any(p["name"].lower() == proxy_name.lower() for p in players):
            # ใช้ id พิเศษสำหรับคนที่ถูกลงแทน
            players.append({"id": f"proxy_{proxy_name}", "name": proxy_name})
            save_data(data)
            reply = f"✅ ลงชื่อ {proxy_name} แทนแล้ว (โดย {sender_name})\n🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน"
        else:
            reply = f"⚠️ {proxy_name} ลงชื่อไว้แล้วนะ!"

    # --- ไม่ไป (ถอนชื่อตัวเอง) ---
    elif text_lower in ["ไม่ไป", "-", "out"]:
        before = len(players)
        data["players"] = [p for p in players if p["id"] != user_id]
        if len(data["players"]) < before:
            save_data(data)
            reply = f"❌ {sender_name} ถอนชื่อแล้ว\n🏸 เหลือ {len(data['players'])} คน"
        else:
            reply = f"ยังไม่ได้ลงชื่อเลยนะ {sender_name}"

    # --- ไม่ไป ชื่อ (ถอนชื่อแทนคนอื่น) ---
    elif text_lower.startswith("ไม่ไป ") and len(text) > 6:
        proxy_name = text[6:].strip()
        before = len(players)
        data["players"] = [p for p in players if p["name"].lower() != proxy_name.lower()]
        if len(data["players"]) < before:
            save_data(data)
            reply = f"❌ ถอนชื่อ {proxy_name} แล้ว (โดย {sender_name})\n🏸 เหลือ {len(data['players'])} คน"
        else:
            reply = f"ไม่พบชื่อ {proxy_name} ในรายชื่อ"

    # --- ดูรายชื่อ ---
    elif text_lower in ["ใคร", "รายชื่อ", "list"]:
        if players:
            names = "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(players)])
            reply = f"🏸 พฤหัส {thu_label} มี {len(players)} คน:\n{names}"
        else:
            reply = "ยังไม่มีใครลงชื่อเลย 😅"

    # --- เคลียร์ ---
    elif text_lower in ["เคลียร์", "clear", "reset"]:
        data["players"] = []
        save_data(data)
        reply = "🗑️ เคลียร์รายชื่อแล้ว!"

    # --- help ---
    elif text_lower in ["help", "ช่วยเหลือ", "?"]:
        reply = ("🏸 คำสั่ง Bot ตีแบด:\n"
                 "ไป → ลงชื่อตัวเอง\n"
                 "ไป ตุ๊ก → ลงชื่อแทนคนอื่น\n"
                 "ไม่ไป → ถอนชื่อตัวเอง\n"
                 "ไม่ไป ตุ๊ก → ถอนชื่อแทนคนอื่น\n"
                 "ใคร / รายชื่อ → ดูรายชื่อ\n"
                 "เคลียร์ → ล้างรายชื่อทั้งหมด")
    else:
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )
