import telebot
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import datetime
import pytz
import time
import threading
import os
import json
from flask import Flask

# --- 1. ตั้งค่า Server หลอกๆ (เพื่อให้ Render ไม่หลับ) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot 24H Kick is Running..."

def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

# --- 2. ตั้งค่าข้อมูลบอท ---
# ดึงค่าจาก Render (เดี๋ยวเราไปตั้งค่าในเว็บ Render กัน)
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROUP_ID = os.environ.get('GROUP_ID')
SHEET_NAME = os.environ.get('SHEET_NAME', 'Kick24H')

bot = telebot.TeleBot(BOT_TOKEN)

# --- 3. เชื่อมต่อ Google Sheets ---
def get_sheet():
    try:
        creds_json = os.environ.get('GOOGLE_KEY_JSON')
        if not creds_json:
            print("❌ ไม่เจอ Google Key")
            return None
        
        # แปลงข้อมูล JSON ให้ถูกต้อง
        try:
            creds_dict = json.loads(creds_json)
        except:
            fixed_json = creds_json.replace('\n', '\\n')
            creds_dict = json.loads(fixed_json)

        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        
        # เปิด Sheet
        sheet = client.open(SHEET_NAME).worksheet('Members')
        print("✅ เชื่อมต่อ Google Sheet สำเร็จ!")
        return sheet
    except Exception as e:
        print(f"❌ เชื่อมต่อ Sheet ไม่ได้: {e}")
        return None

# --- 4. ฟังก์ชันจับคนเข้ากลุ่ม ---
@bot.message_handler(content_types=['new_chat_members'])
def on_join(message):
    # เช็คว่าเป็นกลุ่มที่เราต้องการไหม
    if str(message.chat.id) == str(GROUP_ID):
        try:
            for user in message.new_chat_members:
                if user.is_bot: continue # ข้ามบอท

                print(f"👤 คนเข้าใหม่: {user.first_name}")

                # เวลาปัจจุบัน (ไทย)
                tz = pytz.timezone('Asia/Bangkok')
                now = datetime.datetime.now(tz)
                
                # เวลาที่จะโดนเตะ (อีก 24 ชม.)
                kick_time = now + datetime.timedelta(hours=24)

                # เตรียมข้อมูลลง Sheet
                user_id = str(user.id)
                name = user.first_name
                username = f"@{user.username}" if user.username else "-"
                join_str = now.strftime("%Y-%m-%d %H:%M:%S")
                kick_str = kick_time.strftime("%Y-%m-%d %H:%M:%S")

                # บันทึก
                sheet = get_sheet()
                if sheet:
                    sheet.append_row([user_id, name, username, join_str, kick_str, "Active"])
                    print(f"💾 บันทึกข้อมูลคุณ {name} เรียบร้อย")
                    
                    # ทักทายในกลุ่ม (ถ้าต้องการปิด ให้ลบบรรทัดล่างทิ้ง)
                    bot.reply_to(message, f"ยินดีต้อนรับคุณ {name} เข้าสู่ห้องทดลอง 24 ชม. ครับ ⏳")

        except Exception as e:
            print(f"Join Error: {e}")

# --- 5. ระบบวนลูปตรวจจับและเตะคน (Check Loop) ---
def kick_loop():
    print("⏳ เริ่มระบบนับเวลาถอยหลัง...")
    while True:
        try:
            sheet = get_sheet()
            if sheet:
                records = sheet.get_all_records()
                tz = pytz.timezone('Asia/Bangkok')
                now = datetime.datetime.now(tz).replace(tzinfo=None) # ตัด timezone เพื่อเทียบสตริง

                for i, row in enumerate(records, start=2): # เริ่มแถว 2 (เพราะแถว 1 คือหัวข้อ)
                    
                    status = row.get('Status')
                    kick_str = row.get('Kick Date')
                    uid = str(row.get('User ID'))
                    name = row.get('Name')

                    # ข้ามคนที่โดนเตะไปแล้ว หรือข้อมูลไม่ครบ
                    if status != 'Active' or not kick_str:
                        continue
                    
                    try:
                        # แปลงข้อความเวลา เป็นตัวเลขเวลา
                        kick_date = datetime.datetime.strptime(kick_str, "%Y-%m-%d %H:%M:%S")

                        # ถ้าเวลาปัจจุบัน เลยเวลาเตะแล้ว
                        if now > kick_date:
                            print(f"🚫 หมดเวลาแล้ว: {name}")

                            # 1. เตะออก (Ban)
                            try:
                                bot.ban_chat_member(GROUP_ID, uid)
                                print(f"🔨 เตะคุณ {name} เรียบร้อย")
                            except Exception as e:
                                print(f"เตะไม่ได้ (อาจจะออกไปแล้ว): {e}")

                            # 2. ปลดแบนทันที (Unban) เพื่อให้เข้าใหม่ได้รอบหน้า
                            try:
                                bot.unban_chat_member(GROUP_ID, uid)
                                print(f"🔓 ปลดแบนคุณ {name} เรียบร้อย")
                            except Exception as e:
                                print(f"ปลดแบนไม่ได้: {e}")

                            # 3. อัปเดตใน Sheet ว่าเตะแล้ว (Kicked)
                            sheet.update_cell(i, 6, 'Kicked')
                    
                    except ValueError:
                        continue # ข้ามถ้ารูปแบบวันที่ผิด

            time.sleep(60) # ตรวจทุกๆ 1 นาที

        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(60)

# --- 6. รันบอท ---
if __name__ == "__main__":
    # แยกเธรด 1: รัน Server หลอก
    t1 = threading.Thread(target=run_web_server)
    t1.daemon = True
    t1.start()

    # แยกเธรด 2: รันระบบเตะ
    t2 = threading.Thread(target=kick_loop)
    t2.daemon = True
    t2.start()

    # รันบอทหลัก
    print("🚀 Bot Started...")
    bot.infinity_polling()
