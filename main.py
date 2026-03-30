from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os, json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from datetime import datetime, timedelta
import urllib.request
import urllib.error

app = FastAPI()

LINE_TOKEN = os.environ.get("LINE_TOKEN")
LINE_SECRET = os.environ.get("LINE_SECRET")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

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

def send_wednesday_invite():
    data = load_data()
    msg = ("🏸 สวัสดีตอนเช้า!\n"
           "พรุ่งนี้พฤหัสแล้ว มาตีแบดกันนะ 💪\n\n"
           "พิมพ์ ไป → ลงชื่อตัวเอง\n"
           "พิมพ์ ตุ๊ก ไป หรือ ไป ตุ๊ก → ลงชื่อแทน\n"
           "พิมพ์ AA,BB ไป → ลงหลายคนพร้อมกัน\n"
           "พิมพ์ ใคร → ดูรายชื่อ")
    for gid in data["group_ids"]:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
            print(f"[Invite] Sent to {gid}")
        except Exception as e:
            print(f"[Invite] Error {gid}: {e}")

def reset_thursday():
    data = load_data()
    count = len(data["players"])
    data["players"] = []
    save_data(data)
    msg = f"🗑️ ล้างรายชื่อแล้ว ({count} คน)\nพบกันใหม่สัปดาห์หน้านะ! 🏸"
    for gid in data["group_ids"]:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
            print(f"[Reset] Sent to {gid}")
        except Exception as e:
            print(f"[Reset] Error {gid}: {e}")

scheduler = BackgroundScheduler(timezone=THAILAND_TZ)
scheduler.add_job(send_wednesday_invite, CronTrigger(day_of_week="wed", hour=8, minute=0, timezone=THAILAND_TZ))
scheduler.add_job(reset_thursday, CronTrigger(day_of_week="thu", hour=22, minute=0, timezone=THAILAND_TZ))
scheduler.start()
print("[Scheduler] Started — Wed 08:00 invite, Thu 22:00 reset")

@app.get("/")
def root():
    data = load_data()
    now = datetime.now(THAILAND_TZ)
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)} for j in scheduler.get_jobs()]
    return {
        "status": "running",
        "players": len(data["players"]),
        "time_bangkok": now.strftime("%Y-%m-%d %H:%M %Z"),
        "scheduler_jobs": jobs,
        "ai_enabled": bool(ANTHROPIC_API_KEY)
    }

@app.get("/data")
def view_data():
    data = load_data()
    return {
        "players": data["players"],
        "total": len(data["players"]),
        "group_ids": data["group_ids"],
        "next_thursday": get_next_thursday()
    }

@app.get("/test/invite")
def test_invite():
    send_wednesday_invite()
    return {"status": "sent invite message"}

@app.get("/test/reset")
def test_reset():
    reset_thursday()
    return {"status": "reset done"}

@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return "OK"

# ==================== PARSE FUNCTIONS ====================

def expand_names(raw):
    return [n.strip() for n in raw.split(",") if n.strip()]

def parse_with_rules(line):
    t = line.strip()
    if not t:
        return (None, [])
    t_lower = t.lower()

    if t_lower in ["ไป", "+", "in"]:
        return ("ไป", [])
    if t_lower in ["ไม่ไป", "-", "out",
                   "ไม่ไปละ", "ไม่ไปนะ", "ไม่ไปแล้ว", "ไม่ไปด้วย",
                   "ไปไม่ได้", "ไปไม่ได้ครับ", "ไปไม่ได้ค่ะ"]:
        return ("ไม่ไป", [])
    if t_lower in ["ใคร", "รายชื่อ", "list"]:
        return ("ใคร", [])
    if t_lower in ["เคลียร์", "clear", "reset"]:
        return ("เคลียร์", [])
    if t_lower in ["help", "ช่วยเหลือ", "?"]:
        return ("help", [])

    if t_lower.startswith("ไป "):
        return ("ไป", expand_names(t[3:]))
    if t_lower.startswith("ไม่ไป "):
        return ("ไม่ไป", expand_names(t[6:]))

    parts = t.rsplit(" ", 1)
    if len(parts) == 2:
        name_part, cmd = parts[0].strip(), parts[1].strip().lower()
        if cmd in ["ไป", "+"]:
            return ("ไป", expand_names(name_part))
        if cmd in ["ไม่ไป", "-"]:
            return ("ไม่ไป", expand_names(name_part))

    return (None, [])

def parse_with_ai(text):
    if not ANTHROPIC_API_KEY:
        return None

    prompt = (
        "วิเคราะห์ข้อความในกลุ่มไลน์ว่าเกี่ยวกับการตีแบดมินตันวันพฤหัสไหม\n"
        "ตอบ JSON เท่านั้น: {action: ไป/ไม่ไป/ใคร/null, names: []}\n\n"
        "== มาตีแบด (action:ไป) ==\n"
        "ไปด้วย / อยากไป / ไปได้นะ / ไปก็ได้ / เอาด้วย / นับด้วย / ขอร่วมด้วย\n\n"
        "== ไม่มา (action:ไม่ไป) ==\n"
        "ไม่ว่าง / ติดธุระ / ไปไม่ได้ / ขอพักก่อน / คงไม่ได้ไป\n"
        "อาจจะยัง / ยังไม่แน่ / ไม่แน่ใจ / น่าจะไปไม่ได้ / คงไม่ไป\n"
        "หมายเหตุ: คำที่แสดงความไม่แน่ใจหรือโอกาสน้อย ให้เป็น ไม่ไป\n\n"
        "== ไม่เกี่ยว (action:null) ==\n"
        "อาหารอร่อย / อากาศดี / ขอบคุณ / โอเค / 555\n\n"
        "== มีชื่อคนอื่น ==\n"
        "พาตุ๊กไปด้วย -> {action:ไป,names:[ตุ๊ก]}\n\n"
        f"ข้อความ: {text}"
    )


    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 60,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            raw_text = ""
            for block in result.get("content", []):
                if block.get("type") == "text":
                    raw_text = block["text"].strip()
                    break
            if not raw_text or raw_text in ["null", "None"]:
                return (None, [])
            # หา JSON object ใน response
            start_j = raw_text.find("{")
            end_j = raw_text.rfind("}") + 1
            if start_j >= 0 and end_j > start_j:
                raw_text = raw_text[start_j:end_j]
            else:
                return (None, [])
            parsed = json.loads(raw_text)
            action = parsed.get("action")
            names = parsed.get("names", [])
            print(f"[AI] {text!r} -> action={action} names={names}")
            if action in ["ไป", "ไม่ไป", "ใคร", "เคลียร์", "help", None]:
                return (action, names)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        print(f"[AI] HTTPError {e.code}: {body[:200]}")
    except Exception as e:
        print(f"[AI] Error: {type(e).__name__}: {e}")
    return None
def parse_single_line(line):
    result = parse_with_rules(line)
    if result[0] is not None:
        return result
    ai_result = parse_with_ai(line)
    if ai_result:
        return ai_result
    return (None, [])

# ==================== PROCESS ACTION ====================

def process_action(action, names, user_id, sender_name, data):
    added, removed, already, not_found = [], [], [], []
    players = data["players"]

    if action == "ไป":
        targets = names if names else [None]
        for name in targets:
            display = name if name else sender_name
            pid = f"proxy_{display}" if name else user_id
            if not any(p["name"].lower() == display.lower() for p in players):
                players.append({"id": pid, "name": display})
                added.append(display)
            else:
                already.append(display)

    elif action == "ไม่ไป":
        targets = names if names else [None]
        for name in targets:
            display = name if name else sender_name
            before = len(data["players"])
            if name:
                data["players"] = [p for p in data["players"] if p["name"].lower() != display.lower()]
            else:
                data["players"] = [p for p in data["players"] if p["id"] != user_id]
            if len(data["players"]) < before:
                removed.append(display)
            else:
                not_found.append(display)

    return added, removed, already, not_found

# ==================== HANDLER ====================

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    data = load_data()

    if event.source.type == "group":
        gid = event.source.group_id
        if gid not in data["group_ids"]:
            data["group_ids"].append(gid)
            save_data(data)

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
    lines = text.splitlines()
    valid = [(a, n) for a, n in [parse_single_line(l) for l in lines] if a is not None]

    if not valid:
        return

    first_action = valid[0][0]

    if first_action == "ใคร":
        players = data["players"]
        if players:
            names_str = "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(players)])
            reply = f"🏸 พฤหัส {thu_label} มี {len(players)} คน:\n{names_str}"
        else:
            reply = "ยังไม่มีใครลงชื่อเลย 😅"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if first_action == "เคลียร์":
        data["players"] = []
        save_data(data)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🗑️ เคลียร์รายชื่อแล้ว!"))
        return

    if first_action == "help":
        reply = ("🏸 คำสั่ง SmashBot:\n"
                 "ไป → ลงชื่อตัวเอง\n"
                 "ตุ๊ก ไป / ไป ตุ๊ก → ลงชื่อแทน\n"
                 "AA,BB ไป → ลงหลายคนพร้อมกัน\n"
                 "ไม่ไป → ถอนชื่อตัวเอง\n"
                 "ตุ๊ก ไม่ไป / AA,BB ไม่ไป → ถอนชื่อแทน\n"
                 "ใคร / รายชื่อ → ดูรายชื่อ\n"
                 "เคลียร์ → ล้างรายชื่อ")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    all_added, all_removed, all_already, all_not_found = [], [], [], []
    for action, names in valid:
        if action not in ["ไป", "ไม่ไป"]:
            continue
        a, r, al, nf = process_action(action, names, user_id, sender_name, data)
        all_added += a
        all_removed += r
        all_already += al
        all_not_found += nf

    save_data(data)

    parts = []
    if all_added:
        parts.append("✅ ลงชื่อแล้ว: " + ", ".join(all_added))
    if all_removed:
        parts.append("❌ ถอนชื่อแล้ว: " + ", ".join(all_removed))
    if all_already:
        parts.append("⚠️ ลงชื่อไว้แล้ว: " + ", ".join(all_already))
    if all_not_found:
        parts.append("❓ ไม่พบในรายชื่อ: " + ", ".join(all_not_found))
    parts.append(f"🏸 พฤหัส {thu_label} ตอนนี้มี {len(data['players'])} คน")

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text="\n".join(parts)))
