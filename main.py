from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os

app = FastAPI()

LINE_TOKEN = os.environ.get("LINE_TOKEN")
LINE_SECRET = os.environ.get("LINE_SECRET")

line_bot_api = LineBotApi(LINE_TOKEN)
handler = WebhookHandler(LINE_SECRET)

players = []  # เก็บรายชื่อชั่วคราว

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
    text = event.message.text.strip().lower()
    user_id = event.source.user_id

    try:
        source_type = event.source.type
        if source_type == "group":
            group_id = event.source.group_id
            member = line_bot_api.get_group_member_profile(group_id, user_id)
            name = member.display_name
        elif source_type == "room":
            room_id = event.source.room_id
            member = line_bot_api.get_room_member_profile(room_id, user_id)
            name = member.display_name
        else:
            profile = line_bot_api.get_profile(user_id)
            name = profile.display_name
    except:
        name = "ไม่ทราบชื่อ"

    if text in ["ไป", "+", "in"]:
        if not any(p["id"] == user_id for p in players):
            players.append({"id": user_id, "name": name})
            reply = f"✅ {name} ลงชื่อแล้ว!\n🏸 ตอนนี้มี {len(players)} คน"
        else:
            reply = f"⚠️ {name} ลงชื่อไว้แล้วนะ!"

    elif text in ["ไม่ไป", "-", "out"]:
        before = len(players)
        players[:] = [p for p in players if p["id"] != user_id]
        if len(players) < before:
            reply = f"❌ {name} ถอนชื่อแล้ว\n🏸 เหลือ {len(players)} คน"
        else:
            reply = f"ยังไม่ได้ลงชื่อเลยนะ {name}"

    elif text in ["ใคร", "รายชื่อ", "list"]:
        if players:
            names = "\n".join([f"{i+1}. {p['name']}" for i, p in enumerate(players)])
            reply = f"🏸 พฤหัสนี้มี {len(players)} คน:\n{names}"
        else:
            reply = "ยังไม่มีใครลงชื่อเลย 😅"

    elif text in ["เคลียร์", "clear", "reset"]:
        players.clear()
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

