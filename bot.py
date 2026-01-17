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
BOT_TOKEN = os.environ.get('BOT_TOKEN')
GROUP_ID = os.environ.get('GROUP_ID')
# เพิ่มตัวแปรห้องแอดมินสำหรับแจ้งเตือน
ADMIN_LOG_GROUP = os.environ.get('ADMIN_LOG_GROUP', '-1003548598788') 
SHEET_NAME = os.environ.get('SHEET_NAME', 'Kick24H')

bot = telebot.TeleBot(BOT_TOKEN)

# --- 3. เชื่อมต่อ Google Sheets ---
def get_sheet():
    try:
        creds_json = os.environ.get('GOOGLE_KEY_JSON')
        if not creds_json:
            print("❌ ไม่เจอ Google Key")
            return None
        
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
        return sheet
    except Exception as e:
        print(f"❌ เชื่อมต่อ Sheet ไม่ได้: {e}")
        return None

# --- 4. ฟังก์ชันเช็คว่าเคยมีประวัติไหม ---
def check_history(user_id, sheet):
    try:
        # ดึงข้อมูลคอลัมน์ A (User ID) ทั้งหมดมาเช็ค
        user_ids = sheet.col_values(1)
        # ถ้า ID นี้มีอยู่ในรายการมากกว่า 0 ครั้ง (ไม่นับครั้งปัจจุบันที่จะเพิ่ม)
        if str(user_id) in user_ids:
            return True
        return False
    except:
        return False

# --- 5. ฟังก์ชันจับคนเข้ากลุ่ม ---
@bot.message_handler(content_types=['new_chat_members'])
def on_join(message):
    # เช็คว่าเป็นกลุ่มที่เราต้องการไหม
    if str(message.chat.id) == str(GROUP_ID):
        try:
            sheet = get_sheet()
            
            for user in message.new_chat_members:
                if user.is_bot: continue # ข้ามบอท

                # 1. รวมชื่อ + นามสกุล
                full_name = user.first_name
                if user.last_name:
                    full_name += f" {user.last_name}"
                
                print(f"👤 คนเข้าใหม่: {full_name}")

                # 2. คำนวณเวลา
                tz = pytz.timezone('Asia/Bangkok')
                now = datetime.datetime.now(tz)
                kick_time = now + datetime.timedelta(hours=24)
                
                join_str = now.strftime("%Y-%m-%d %H:%M:%S")
                kick_str = kick_time.strftime("%Y-%m-%d %H:%M:%S")
                
                user_id = str(user.id)
                username = f"@{user.username}" if user.username else "-"

                # 3. เช็คประวัติ (ลูกค้าเก่า/ใหม่)
                is_old_user = False
                if sheet:
                    is_old_user = check_history(user_id, sheet)
                
                user_type_text = "🔄 ลูกค้าเก่า (Re-join)" if is_old_user else "🟢 ลูกค้าใหม่ (New)"

                # 4. บันทึกลง Sheet
                if sheet:
                    sheet.append_row([user_id, full_name, username, join_str, kick_str, "Active"])
                    print(f"💾 บันทึกข้อมูลคุณ {full_name} เรียบร้อย")

                # 5. ส่งแจ้งเตือนเข้าห้องแอดมิน (แทนการพิมในกลุ่ม)
                log_msg = (
                    f"📢 <b>มีคนเข้าห้องทดลอง 24 ชม.</b>\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"👤 <b>ชื่อ:</b> {full_name}\n"
                    f"🏷 <b>สถานะ:</b> {user_type_text}\n"
                    f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                    f"🔗 <b>User:</b> {username}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📥 <b>เข้าตอน:</b> {join_str}\n"
                    f"💣 <b>จะโดนเตะ:</b> {kick_str}"
                )
                
                try:
                    bot.send_message(ADMIN_LOG_GROUP, log_msg, parse_mode='HTML')
                except Exception as e:
                    print(f"ส่งเข้าห้องแอดมินไม่ได้: {e}")

        except Exception as e:
            print(f"Join Error: {e}")

# --- 6. ระบบวนลูปตรวจจับและเตะคน ---
def kick_loop():
    print("⏳ เริ่มระบบนับเวลาถอยหลัง...")
    while True:
        try:
            sheet = get_sheet()
            if sheet:
                records = sheet.get_all_records()
                tz = pytz.timezone('Asia/Bangkok')
                now = datetime.datetime.now(tz).replace(tzinfo=None)

                for i, row in enumerate(records, start=2):
                    
                    status = row.get('Status')
                    kick_str = row.get('Kick Date')
                    uid = str(row.get('User ID'))
                    name = row.get('Name')

                    # ข้ามคนที่โดนเตะไปแล้ว หรือข้อมูลไม่ครบ
                    if status != 'Active' or not kick_str:
                        continue
                    
                    try:
                        kick_date = datetime.datetime.strptime(kick_str, "%Y-%m-%d %H:%M:%S")

                        if now > kick_date:
                            print(f"🚫 หมดเวลาแล้ว: {name}")

                            # 1. เตะออก
                            try:
                                bot.ban_chat_member(GROUP_ID, uid)
                            except Exception as e:
                                print(f"เตะไม่ได้: {e}")

                            # 2. ปลดแบนทันที
                            try:
                                bot.unban_chat_member(GROUP_ID, uid)
                            except Exception as e:
                                print(f"ปลดแบนไม่ได้: {e}")

                            # 3. อัปเดต Sheet
                            sheet.update_cell(i, 6, 'Kicked')
                            
                            # 4. แจ้งแอดมินว่าเตะแล้ว
                            try:
                                bot.send_message(
                                    ADMIN_LOG_GROUP, 
                                    f"🧹 <b>หมดเวลา 24 ชม.</b>\nเตะคุณ: {name}\nสถานะ: ปลดแบนแล้ว (เข้าใหม่ได้)", 
                                    parse_mode='HTML'
                                )
                            except: pass

                    except ValueError:
                        continue

            time.sleep(60)

        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(60)

# --- 7. รันบอท ---
if __name__ == "__main__":
    t1 = threading.Thread(target=run_web_server)
    t1.daemon = True
    t1.start()

    t2 = threading.Thread(target=kick_loop)
    t2.daemon = True
    t2.start()

    print("🚀 Bot Started...")
    bot.infinity_polling()
