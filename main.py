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

THAI_MONTHS = {
    1: "ม.ค.", 2: "ก.พ.", 3: "มี.ค.", 4: "เม.ย.",
    5: "พ.ค.", 6: "มิ.ย.", 7: "ก.ค.", 8: "ส.ค.",
    9: "ก.ย.", 10: "ต.ค.", 11: "พ.ย.", 12: "ธ.ค."
}

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
    next_thu = now + timedelta(days=days_ahead)
    return f"{next_thu.day} {THAI_MONTHS[next_thu.month]}"

def parse_single_line(line):
    """
    แยกคำสั่งและชื่อจากบรรทัดเดียว
    รองรับ: "ไป", "ไป ชื่อ", "ชื่อ ไป", "ไม่ไป", "ไม่ไป ชื่อ", "ชื่อ ไม่ไป"
    คืนค่า: (action, proxy_name) หรือ (None, None)
    """
    t = line.strip()
    if not t:
        return (None, None)
    t_lower = t.lower()

    # คำสั่งเดี่ยวไม่มีชื่อ
    if t_lower in ["ไป", "+", "in"]:
        return ("ไป", None)
    if t_lower in ["ไม่ไป", "-", "out"]:
        return ("ไม่ไป", None)
    if t_lower in ["ใคร", "รายชื่อ", "list"]:
        return ("ใคร", None)
    if t_lower in ["เคลียร์", "clear", "reset"]:
        return ("เคลียร์", None)
    if t_lower in ["help", "ช่วยเหลือ", "?"]:
        return ("help", None)

    # "ไป ชื่อ" หรือ "ไม่ไป ชื่อ"
    if t_lower.startswith("ไป "):
        return ("ไป", t[3:].strip())
    if t_lower.startswith("ไม่ไป "):
        return ("ไม่ไป", t[6:].strip())

    # "ชื่อ ไป" หรือ "ชื่อ ไม่ไป"
    parts = t.rsplit(" ", 1)
    if len(parts) == 2:
        name_part, cmd_part = parts[0].strip(), parts[1].strip().lower()
        if cmd_part in ["ไป", "+"]:
            return ("ไป", name_part)
        if cmd_part in ["ไม่ไป", "-"]:
            return ("ไม่ไป", name_part)

    return (None, None)

def send_wednesday_invite():
    data = load_data()
    msg = ("🏸 สวัสดีตอนเช้า!\n"
           "พรุ่งนี้พฤหัสแล้ว มาตีแบดกันนะ 💪\n\n"
           "พิมพ์ ไป → ลงชื่อตัวเอง\n"
           "พิมพ์ ไป ตุ๊ก หรือ ตุ๊ก ไป → ลงชื่อแทน\n"
           "ลงหลายคนพร้อมกันได้:\n"
           "AA ไป\nBB ไป\nCC ไป\n"
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
        if event.source.type == "group":
            member = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
            sender_name = member.display_name
        elif event.source.type == "room":
            member = line_bot_api.get_room_member_profile(event.source.room_id, user_id)
            sender_name = member.display_name
        else:
            profile = line_bot_api.get_profile(user_id)
            sender_name = profile.display_name
    except:
        sender_name = "ไม่ทราบชื่อ"

    thu_label = get_next_thursday()
    players = data["players"]

    # แยกข้อความเป็นบรรทัด รองรับทั้งหลายบรรทัดและบรรทัดเดียว
    lines = text.splitlines()
    
    # วิเคราะห์แต่ละบรรทัด
    parsed_lines = [(parse_single_line(line), line.strip()) for line in lines]
    valid_commands = [(action, proxy, raw) for (action, proxy), raw in parsed_lines if action is not None]

    # ถ้าไม่มีคำสั่งที่รู้จักเลย ไม่ตอบ
    if not valid_commands:
        return

    # ถ้ามีแค่บรรทัดเดียว ใช้ logic เดิม (ตอบแบบ single)
    if len(valid_commands) == 1:
        action, proxy_name, _ = valid_commands[0]

        # คำสั่งพิเศษที่ไม่เกี่ยวกับลงชื่อ
        if action == "ใคร":
            if players:
                names = "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(players)])
                reply = f"🏸 พฤหัส {thu_label} มี {len(players)} คน:\n{names}"
            else:
                reply = "ยังไม่มีใครลงชื่อเลย 😅"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        if action == "เคลียร์":
            data["players"] = []
            save_data(data)
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ เคลียร์รายชื่อแล้ว!"))
            return

        if action == "help":
            reply = ("🏸 คำสั่ง Bot ตีแบด:\n"
                     "ไป → ลงชื่อตัวเอง\n"
                     "ไป ตุ๊ก / ตุ๊ก ไป → ลงชื่อแทน\n"
                     "ไม่ไป → ถอนชื่อตัวเอง\n"
                     "ไม่ไป ตุ๊ก / ตุ๊ก ไม่ไป → ถอนชื่อแทน\n"
                     "ลงหลายคนพร้อมกัน:\nAA ไป\nBB ไป\n"
                     "ใคร / รายชื่อ → ดูรายชื่อ\n"
                     "เคลียร์ → ล้างรายชื่อ")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

        if action == "ไป":
            if proxy_name:
                if not any(p["name"].lower() == proxy_name.lower() for p in players):
                    players.append({"id": f"proxy_{proxy_name}", "name": proxy_name})
                    save_data(data)
                    reply = f"✅ ลงชื่อ {proxy_name} แทนแล้ว (โดย {sender_name})\n🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน"
                else:
                    reply = f"⚠️ {proxy_name} ลงชื่อไว้แล้วนะ!"
            else:
                if not any(p["id"] == user_id for p in players):
                    players.append({"id": user_id, "name": sender_name})
                    save_data(data)
                    reply = f"✅ {sender_name} ลงชื่อแล้ว!\n🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน"
                else:
                    reply = f"⚠️ {sender_name} ลงชื่อไว้แล้วนะ!"

        elif action == "ไม่ไป":
            if proxy_name:
                before = len(players)
                data["players"] = [p for p in players if p["name"].lower() != proxy_name.lower()]
                if len(data["players"]) < before:
                    save_data(data)
                    reply = f"❌ ถอนชื่อ {proxy_name} แล้ว (โดย {sender_name})\n🏸 เหลือ {len(data['players'])} คน"
                else:
                    reply = f"ไม่พบชื่อ {proxy_name} ในรายชื่อ"
            else:
                before = len(players)
                data["players"] = [p for p in players if p["id"] != user_id]
                if len(data["players"]) < before:
                    save_data(data)
                    reply = f"❌ {sender_name} ถอนชื่อแล้ว\n🏸 เหลือ {len(data['players'])} คน"
                else:
                    reply = f"ยังไม่ได้ลงชื่อเลยนะ {sender_name}"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # === หลายบรรทัด: ประมวลผลทีเดียว ===
    added = []
    removed = []
    already = []
    not_found = []

    for action, proxy_name, raw in valid_commands:
        if action == "ไป":
            name = proxy_name if proxy_name else sender_name
            pid = f"proxy_{name}" if proxy_name else user_id
            # reload players ทุกครั้งเพราะอาจมีการเปลี่ยนแปลง
            players = data["players"]
            if not any(p["name"].lower() == name.lower() for p in players):
                players.append({"id": pid, "name": name})
                added.append(name)
            else:
                already.append(name)

        elif action == "ไม่ไป":
            name = proxy_name if proxy_name else sender_name
            players = data["players"]
            before = len(players)
            if proxy_name:
                data["players"] = [p for p in players if p["name"].lower() != name.lower()]
            else:
                data["players"] = [p for p in players if p["id"] != user_id]
            if len(data["players"]) < before:
                removed.append(name)
            else:
                not_found.append(name)

    save_data(data)
    players = data["players"]

    # สร้างข้อความตอบกลับ
    reply_parts = []
    if added:
        reply_parts.append("✅ ลงชื่อแล้ว: " + ", ".join(added))
    if removed:
        reply_parts.append("❌ ถอนชื่อแล้ว: " + ", ".join(removed))
    if already:
        reply_parts.append("⚠️ ลงชื่อไว้แล้ว: " + ", ".join(already))
    if not_found:
        reply_parts.append("❓ ไม่พบในรายชื่อ: " + ", ".join(not_found))

    reply_parts.append(f"🏸 พฤหัส {thu_label} ตอนนี้มี {len(players)} คน")

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(reply_parts)))
