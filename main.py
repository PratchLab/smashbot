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
import re

app = FastAPI()

LINE_TOKEN = os.environ.get("LINE_TOKEN")
LINE_SECRET = os.environ.get("LINE_SECRET")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

THAILAND_TZ = pytz.timezone("Asia/Bangkok")
DATA_FILE = "/data/badminton_data.json"  # Render Disk — ไม่หายตอน deploy

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
        return {"players": [], "group_ids": [], "last_invite_date": "", "last_reset_date": "", "holidays": []}

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
    # เช็คว่าพฤหัสหน้าเป็นวันหยุดไหม
    now = datetime.now(THAILAND_TZ)
    days_ahead = (3 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    next_thu = now + timedelta(days=days_ahead)
    next_thu_str = next_thu.strftime("%Y-%m-%d")
    thu_label = f"{next_thu.day} {THAI_MONTHS[next_thu.month]}"

    holidays = data.get("holidays", [])
    holiday_info = next((h for h in holidays if h["date"] == next_thu_str), None)

    if holiday_info:
        msg = (f"🚫 สัปดาห์นี้ไม่มีตีแบดนะครับ\n"
               f"วันพฤหัส {thu_label} หยุด: {holiday_info['reason']}\n\n"
               f"พบกันสัปดาห์หน้า! 🏸")
    else:
        msg = ("🏸 สวัสดีตอนเช้า!\n"
               f"พรุ่งนี้พฤหัส {thu_label} มาตีแบดกันนะ 💪\n\n"
               "พิมพ์ ไป → ลงชื่อตัวเอง\n"
               "พิมพ์ ตุ๊ก ไป หรือ ไป ตุ๊ก → ลงชื่อแทน\n"
               "พิมพ์ AA,BB ไป → ลงหลายคนพร้อมกัน\n"
               "พิมพ์ ใคร → ดูรายชื่อ")
    for gid in data["group_ids"]:
        try:
            line_bot_api.push_message(gid, TextSendMessage(text=msg))
            print(f"[Invite] Sent to {gid} (holiday={bool(holiday_info)})")
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

# ตรวจสอบตอน startup: ถ้าพลาด job ไปให้รันทันที
def check_missed_jobs():
    now = datetime.now(THAILAND_TZ)
    data = load_data()
    today = now.strftime("%Y-%m-%d")
    # พุธ เลย 8:00 แล้ว และยังไม่ได้ส่งวันนี้
    if now.weekday() == 2 and now.hour >= 8:
        if data.get("last_invite_date") != today:
            print("[Startup] Missed Wednesday invite — sending now")
            data["last_invite_date"] = today
            save_data(data)
            send_wednesday_invite()
    # พฤหัส เลย 22:00 แล้ว และยังไม่ได้ reset วันนี้
    if now.weekday() == 3 and now.hour >= 22:
        if data.get("last_reset_date") != today:
            print("[Startup] Missed Thursday reset — running now")
            data["last_reset_date"] = today
            save_data(data)
            reset_thursday()

check_missed_jobs()

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

@app.get("/holidays")
def view_holidays():
    data = load_data()
    holidays = sorted(data.get("holidays", []), key=lambda h: h["date"])
    return {"holidays": holidays, "total": len(holidays)}

@app.get("/test/invite")
def test_invite():
    send_wednesday_invite()
    return {"status": "sent invite message"}

@app.get("/test/reset")
def test_reset():
    reset_thursday()
    return {"status": "reset done"}

@app.get("/ping")
def ping():
    """UptimeRobot เรียกทุก 5 นาที — ตรวจ missed jobs ด้วย"""
    now = datetime.now(THAILAND_TZ)
    today = now.strftime("%Y-%m-%d")
    data = load_data()
    triggered = []

    # พุธ 8:00-9:00 ยังไม่ได้ส่ง
    if now.weekday() == 2 and 8 <= now.hour < 9:
        if data.get("last_invite_date") != today:
            data["last_invite_date"] = today
            save_data(data)
            send_wednesday_invite()
            triggered.append("wednesday_invite")
            print(f"[Ping] Triggered wednesday invite at {now.strftime('%H:%M')}")

    # พฤหัส 22:00-23:00 ยังไม่ได้ reset
    if now.weekday() == 3 and 22 <= now.hour < 23:
        if data.get("last_reset_date") != today:
            data["last_reset_date"] = today
            save_data(data)
            reset_thursday()
            triggered.append("thursday_reset")
            print(f"[Ping] Triggered thursday reset at {now.strftime('%H:%M')}")

    return {
        "status": "ok",
        "time_bangkok": now.strftime("%Y-%m-%d %H:%M %Z"),
        "triggered": triggered
    }

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

def parse_date(text):
    """แปลง 16/4 หรือ 16/04 หรือ 16/4/68 เป็น YYYY-MM-DD"""
    import re
    now = datetime.now(THAILAND_TZ)
    # รูปแบบ dd/mm หรือ dd/mm/yy หรือ dd/mm/yyyy
    m = re.match(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", text.strip())
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year_raw = m.group(3)
        if year_raw:
            y = int(year_raw)
            # พ.ศ. -> ค.ศ.
            if y > 2500:
                y -= 543
            elif y < 100:
                y += 2000
        else:
            y = now.year
        try:
            from datetime import date
            d = date(y, month, day)
            return d.strftime("%Y-%m-%d"), f"{day} {THAI_MONTHS[month]} {y+543}"
        except:
            pass
    return None, None

def expand_names(raw):
    return [n.strip() for n in raw.split(",") if n.strip()]

def parse_with_rules(line):
    t = line.strip()
    if not t:
        return (None, [])
    t_lower = t.lower()

    if t_lower in ["ไป", "+", "in", "going", "i'm going", "im going",
                   "i'm in", "im in", "count me in", "i'll go", "ill go"]:
        return ("ไป", [])
    if t_lower in ["ไม่ไป", "-", "out",
                   "ไม่ไปละ", "ไม่ไปนะ", "ไม่ไปแล้ว", "ไม่ไปด้วย",
                   "ไปไม่ได้", "ไปไม่ได้ครับ", "ไปไม่ได้ค่ะ",
                   "not going", "can't go", "cant go", "can't make it",
                   "cant make it", "i'm out", "im out", "won't go"]:
        return ("ไม่ไป", [])
    if t_lower in ["ใคร", "รายชื่อ", "list", "who's going", "whos going",
                   "who's in", "whos in", "how many"]:
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

    # จับรูปแบบ "ชื่อไป" / "ชื่อไม่ไป" ที่ไม่มีเว้นวรรค เช่น "ยั้ไป" "ภูไป"
    # แต่กัน false positive เช่น "อยากไป" "ขอไป" "เอาไป"
    NOT_NAMES = {
        "อยาก", "ขอ", "เอา", "จะ", "ยัง", "คง", "น่าจะ", "อาจจะ",
        "ต้องการ", "สนใจ", "ได้", "ก็", "นับ", "ด้วย", "มา", "ลอง",
        "ของ", "ที่", "แค่", "เพียง", "ขอ"
    }
    # แปลง X/X เป็น % โดย:
    # - ถ้า a == b (เช่น 50/50, 1/1) = 50% (แปลว่า "ครึ่งๆ")
    # - ถ้า a != b (เช่น 1/3, 2/3) = คำนวณจริง
    def fraction_to_pct(s):
        m = re.match(r"^(\d+)/(\d+)$", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b > 0:
                if a == b:
                    return "50%"  # 50/50 = โอกาสครึ่งๆ
                return f"{round(a*100/b)}%"
        return s

    # แทนที่ทุก X/X ใน t ด้วย %
    t_normalized = re.sub(r"\b(\d+)/(\d+)\b", lambda m: fraction_to_pct(m.group(0)), t)

    # จับรูปแบบ "XX% ไป" หรือ "ชื่อ XX% ไป" — XX% คือความน่าจะเป็น ไม่ใช่ชื่อ
    # เช่น "49% ไป" → ลงชื่อตัวเอง (49%)
    # เช่น "สมชาย 80% ไป" → ลงชื่อ สมชาย (80%)
    pct_go = re.match(r"^(.*?)\s*(\d+%)\s*ไป$", t_normalized)
    if pct_go:
        prefix = pct_go.group(1).strip()
        pct = pct_go.group(2)
        if prefix and prefix not in NOT_NAMES:
            # มีชื่อนำหน้า เช่น "สมชาย 80% ไป"
            return ("ไป_pct", [prefix, pct])
        else:
            # ไม่มีชื่อ หรือชื่อเป็น keyword เช่น "49% ไป"
            return ("ไป_pct", [None, pct])

    pct_nogo = re.match(r"^(.*?)\s*(\d+%)\s*ไม่ไป$", t_normalized)
    if pct_nogo:
        prefix = pct_nogo.group(1).strip()
        pct = pct_nogo.group(2)
        if prefix and prefix not in NOT_NAMES:
            return ("ไม่ไป_pct", [prefix, pct])
        else:
            return ("ไม่ไป_pct", [None, pct])

    if t.endswith("ไม่ไป"):
        name_part = t[:-5].strip()
        if name_part and name_part not in NOT_NAMES:
            return ("ไม่ไป", expand_names(name_part))
    elif t.endswith("ไป"):
        name_part = t[:-2].strip()
        if name_part and name_part not in NOT_NAMES:
            return ("ไป", expand_names(name_part))

    return (None, [])

def parse_with_ai(text):
    if not ANTHROPIC_API_KEY:
        return None

    prompt = (
        "คุณคือ AI วิเคราะห์ข้อความในกลุ่มไลน์ตีแบดมินตัน รองรับทั้งภาษาไทยและอังกฤษ\n"
        "ตอบ JSON เท่านั้น: {action: ไป/ไม่ไป/ใคร/null, names: []}\n\n"
        "สำคัญมาก: ถ้าไม่ใช่การแจ้งลงชื่อหรือถอนชื่อชัดเจน ให้ตอบ null เสมอ\n"
        "บทสนทนาทั่วไป การถามตอบ การพูดคุย ให้เป็น null ทั้งหมด\n\n"
        "== ลงชื่อ (action:ไป) ==\n"
        "ภาษาไทย: ไปด้วย / อยากไป / ไปได้นะ / เอาด้วย / นับด้วย / พร้อม\n"
        "ภาษาอังกฤษ: I'm going / going / I'll go / count me in / i'm in / going too\n"
        "ผสม: Parmee's going / John ไปด้วย / going นะ\n\n"
        "== ถอนชื่อ (action:ไม่ไป) ==\n"
        "ภาษาไทย: ไม่ว่าง / ติดธุระ / ไปไม่ได้ / อาจจะยัง / คงไม่ไป\n"
        "ภาษาอังกฤษ: can't make it / not going / i'm out / can't go / won't be there\n\n"
        "== ใคร (action:ใคร) ==\n"
        "ใคร / รายชื่อ / who's going / how many / who's in\n\n"
        "== null (ไม่เกี่ยวกับลงชื่อ) ==\n"
        "ขอมาลอง 1 ลูกก่อน -> null\n"
        "งั้นไม่เอาละกัน ไอ้คนเสนอก็ไม่ได้มาตีด้วย -> null\n"
        "see you there / good game / gg -> null\n"
        "อาหารอร่อย / ขอบคุณ / โอเค / 555 -> null\n\n"
        "== มีชื่อคนอื่น ==\n"
        "Parmee's going -> {action:ไป,names:[Parmee]}\n"
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

    if action in ["ไป", "ไป_pct"]:
        if action == "ไป_pct":
            # names = [ชื่อ_หรือ_None, "%"]
            proxy_name = names[0] if names else None
            pct = names[1] if len(names) > 1 else ""
            raw_display = proxy_name if proxy_name else sender_name
            display = f"{raw_display} ({pct})"
            pid = f"proxy_{display}" if proxy_name else user_id
            targets = [(display, pid)]
        else:
            targets_raw = names if names else [None]
            targets = []
            for name in targets_raw:
                display = name if name else sender_name
                pid = f"proxy_{display}" if name else user_id
                targets.append((display, pid))

        for display, pid in targets:
            # เช็คชื่อ base (ไม่รวม %) ด้วยเพื่อกัน duplicate
            base_name = re.sub(r"\s*\(\d+%\)$", "", display).strip()
            if not any(
                p["name"].lower() == display.lower() or
                re.sub(r"\s*\(\d+%\)$", "", p["name"]).strip().lower() == base_name.lower()
                for p in players
            ):
                players.append({"id": pid, "name": display})
                added.append(display)
            else:
                already.append(display)

    elif action in ["ไม่ไป", "ไม่ไป_pct"]:
        if action == "ไม่ไป_pct":
            proxy_name = names[0] if names else None
            pct = names[1] if len(names) > 1 else ""
            raw_display = proxy_name if proxy_name else sender_name
            targets_raw = [proxy_name]  # ใช้ชื่อเดิมในการค้นหา
        else:
            targets_raw = names if names else [None]

        for name in targets_raw:
            display = name if name else sender_name
            before = len(data["players"])
            if name:
                # ลบทั้งชื่อปกติและชื่อที่มี (%) ต่อท้าย
                data["players"] = [
                    p for p in data["players"]
                    if re.sub(r"\s*\(\d+%\)$", "", p["name"]).strip().lower() != display.lower()
                    and p["name"].lower() != display.lower()
                ]
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

    # ===== เช็คคำสั่งวันหยุดก่อนเลย (ก่อน AI parse) =====
    raw_lower = text.strip().lower()

    if raw_lower == "วันหยุด":
        holidays = sorted(data.get("holidays", []), key=lambda h: h["date"])
        if holidays:
            lines = [f"{i+1}. พฤหัส {h['label']} — {h['reason']}" for i, h in enumerate(holidays)]
            reply = "📅 รายการวันหยุด:\n" + "\n".join(lines)
        else:
            reply = "ไม่มีวันหยุดที่ตั้งไว้ครับ"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if raw_lower.startswith("หยุด "):
        parts = text.strip().split(" ", 2)
        date_str = parts[1] if len(parts) > 1 else ""
        reason = parts[2] if len(parts) > 2 else "วันหยุด"
        date_iso, date_label = parse_date(date_str)
        if date_iso:
            holidays = data.get("holidays", [])
            if not any(h["date"] == date_iso for h in holidays):
                holidays.append({"date": date_iso, "label": date_label, "reason": reason})
                data["holidays"] = sorted(holidays, key=lambda h: h["date"])
                save_data(data)
                reply = f"✅ เพิ่มวันหยุดแล้ว\nพฤหัส {date_label} — {reason}"
            else:
                reply = f"⚠️ {date_label} มีในรายการแล้ว"
        else:
            reply = "รูปแบบวันที่ไม่ถูกต้อง เช่น หยุด 16/4 พรหมลิขิต"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if raw_lower.startswith("ยกเลิกหยุด "):
        parts = text.strip().split(" ", 1)
        date_str = parts[1] if len(parts) > 1 else ""
        date_iso, date_label = parse_date(date_str)
        if date_iso:
            before = len(data.get("holidays", []))
            data["holidays"] = [h for h in data.get("holidays", []) if h["date"] != date_iso]
            if len(data["holidays"]) < before:
                save_data(data)
                reply = f"✅ ลบวันหยุด {date_label} แล้ว"
            else:
                reply = f"ไม่พบวันหยุด {date_label} ในรายการ"
        else:
            reply = "รูปแบบวันที่ไม่ถูกต้อง เช่น ยกเลิกหยุด 16/4"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # ===== ต่อจากนี้ parse คำสั่งทั่วไป =====
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
