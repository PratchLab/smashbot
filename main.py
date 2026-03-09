from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os, json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime

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
    days_ahead = 3 - now.weekday()  # พฤหัส = 3
    if days_ahead <= 0:
        days_ahead += 7
    next_thu = now.replace(day=now.day + days_ahead)
    return next_thu.strftime("%-d %b")

def send_wednesday_invite():
    data = load_data()
    thu_date = get_next_thursday()
    msg = (f"🏸 สวัสดีตอนเช้า!\n"
           f"พรุ่งนี้พฤหัสแล้ว มาตีแบดกันนะ 💪\n\n"
           f"พิมพ์ ไป → ลงชื่อ\n"
           f"พิมพ์ ไม่ไป → ถอนชื่อ\n"
           f"พิมพ์ ใคร → ดูรายชื่อ")
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
    text = event.message.text.strip().lower()
    user_id = event.source.user_id

    data = load_data()

    # เก็บ group_id อัตโนมัติ
    if event.source.type == "group":
        gid = event.source.group_id
        if gid not in data["group_ids"]:
            data["group_ids"].append(gid)
            save_data(data)

    # ดึงชื่อ
    try:
        source_type = event.source.type
        if source_type == "group":
            member = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
            name = member.display_name
        elif source_type == "room":
            member = line_bot_api.get_room_member_profile(event.source.room_id, user_id)
            name = member.display_name
        else:
            profile = line_bot_api.get_profile(user_id)
            name = profile.display_name
    except:
        name = "ไม่ทราบชื่อ"

    # หาวันพฤหัสถัดไป
    now = datetime.now(THAILAND_TZ)
    days_ahead = (3 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    from datetime import timedelta
    next_thu = now + timedelta(days=days_ahead)
    thu_label = next_thu.strftime("%-d %b")

    players = data["players"]

    if text in ["ไป", "+", "in"]:
        if not any(p["id"] == user_id for p in players):
            players.append({"id": user_id, "name": name})
            save_data(data)
            reply = f"✅ {name} ลงชื่อแล้ว!\n🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน"
        else:
            reply = f"⚠️ {name} ลงชื่อไว้แล้วนะ!"

    elif text in ["ไม่ไป", "-", "out"]:
        before = len(players)
        data["players"] = [p for p in players if p["id"] != user_id]
        if len(data["players"]) < before:
            save_data(data)
            reply = f"❌ {name} ถอนชื่อแล้ว\n🏸 เหลือ {len(data['players'])} คน"
        else:
            reply = f"ยังไม่ได้ลงชื่อเลยนะ {name}"

    elif text in ["ใคร", "รายชื่อ", "list"]:
        if players:
            names = "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(players)])
            reply = f"🏸 พฤหัส {thu_label} มี {len(players)} คน:\n{names}"
        else:
            reply = "ยังไม่มีใครลงชื่อเลย 😅"

    elif text in ["เคลียร์", "clear", "reset"]:
        data["players"] = []
        save_data(data)
        reply = "🗑️ เคลียร์รายชื่อแล้ว!"

    elif text in ["help", "ช่วยเหลือ", "?"]:
        reply = ("🏸 คำสั่ง Bot ตีแบด:\n"
                 "พิมพ์ ไป / + → ลงชื่อ\n"
                 "พิมพ์ ไม่ไป / - → ถอนชื่อ\n"
                 "พิมพ์ ใคร / รายชื่อ → ดูรายชื่อ\n"
                 "พิมพ์ เคลียร์ → ล้างรายชื่อ")
    else:
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )
