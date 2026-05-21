import os
import telebot
import json
import time
import threading
import io
from flask import Flask, request, send_file, make_response, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz
import psycopg2

# 🔑 НАСТРОЙКИ
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("⚠️ Добавьте TG_BOT_TOKEN!")

ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 105918840))
moscow_tz = pytz.timezone('Europe/Moscow')

# 🔹 PostgreSQL
def get_db_connection():
    conn = psycopg2.connect(os.environ.get("DATABASE_URL"))
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS redirects (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP WITH TIME ZONE,
                    session_id TEXT,
                    platform TEXT,
                    watch_time INTEGER,
                    redirect_type TEXT DEFAULT 'auto')''')
    c.execute("ALTER TABLE redirects ADD COLUMN IF NOT EXISTS redirect_type TEXT DEFAULT 'auto'")
    conn.commit()
    conn.close()
    print("✅ База данных готова")

init_db()

def add_redirect(session_id, platform, watch_time, redirect_type='auto'):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now(moscow_tz)
        c.execute('''INSERT INTO redirects (timestamp, session_id, platform, watch_time, redirect_type) 
                     VALUES (%s, %s, %s, %s, %s)''', 
                  (now, session_id, platform, watch_time, redirect_type))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

def get_stats(start_date, end_date):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM redirects WHERE timestamp >= %s AND timestamp < %s', 
                  (start_date, end_date))
        total = c.fetchone()[0]
        
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects WHERE timestamp >= %s AND timestamp < %s', 
                  (start_date, end_date))
        unique = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM redirects WHERE timestamp >= %s AND timestamp < %s AND redirect_type = %s', 
                  (start_date, end_date, 'auto'))
        auto_total = c.fetchone()[0]
        
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects WHERE timestamp >= %s AND timestamp < %s AND redirect_type = %s', 
                  (start_date, end_date, 'auto'))
        auto_unique = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM redirects WHERE timestamp >= %s AND timestamp < %s AND redirect_type = %s', 
                  (start_date, end_date, 'button'))
        button_total = c.fetchone()[0]
        
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects WHERE timestamp >= %s AND timestamp < %s AND redirect_type = %s', 
                  (start_date, end_date, 'button'))
        button_unique = c.fetchone()[0]
        
        conn.close()
        return {
            'total': total, 'unique': unique,
            'auto_total': auto_total, 'auto_unique': auto_unique,
            'button_total': button_total, 'button_unique': button_unique
        }
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {'total': 0, 'unique': 0, 'auto_total': 0, 'auto_unique': 0, 'button_total': 0, 'button_unique': 0}

# 🔹 Планировщик
def check_schedule():
    while True:
        now = datetime.now(moscow_tz)
        if now.strftime("%H:%M") == "00:00":
            send_daily_report()
            time.sleep(60)
        time.sleep(30)

def send_daily_report():
    today = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    stats = get_stats(yesterday, today)
    
    msg = f"📊 <b>Отчёт за {yesterday.strftime('%d.%m.%Y')}</b>\n\n"
    msg += f"<b>🔄 Автоматические:</b>\n  🔄 {stats['auto_total']}\n  👤 {stats['auto_unique']}\n\n"
    msg += f"<b> По кнопке:</b>\n  🔄 {stats['button_total']}\n  👤 {stats['button_unique']}\n\n"
    msg += f"<b>📈 Всего:</b>\n  🔄 <b>{stats['total']}</b>\n  👤 <b>{stats['unique']}</b>"
    
    try:
        bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except:
        pass

#  Telegram бот
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start', 'stats', 'today', 'period'])
def cmd_handler(m):
    if m.chat.id != ADMIN_CHAT_ID:
        return
    
    if m.text == '/start':
        bot.reply_to(m, " Бот активен.\n/stats — всё время\n/today — сегодня\n/period YYYY-MM-DD YYYY-MM-DD")
    
    elif m.text == '/stats':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM redirects'); total = c.fetchone()[0]
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects'); unique = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM redirects WHERE redirect_type='auto'"); auto_total = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT session_id) FROM redirects WHERE redirect_type='auto'"); auto_unique = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM redirects WHERE redirect_type='button'"); button_total = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT session_id) FROM redirects WHERE redirect_type='button'"); button_unique = c.fetchone()[0]
        conn.close()
        
        msg = f"📊 <b>За всё время:</b>\n\n"
        msg += f"<b>🔄 Авто:</b>\n  🔄 {auto_total}\n  👤 {auto_unique}\n\n"
        msg += f"<b> Кнопка:</b>\n  🔄 {button_total}\n  👤 {button_unique}\n\n"
        msg += f"<b> Итого:</b>\n  🔄 <b>{total}</b>\n  👤 <b>{unique}</b>"
        bot.reply_to(m, msg, parse_mode="HTML")
    
    elif m.text == '/today':
        today_start = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        stats = get_stats(today_start, tomorrow)
        
        msg = f"📊 <b>За сегодня:</b>\n\n"
        msg += f"<b>🔄 Авто:</b>\n   {stats['auto_total']}\n   {stats['auto_unique']}\n\n"
        msg += f"<b>🔵 Кнопка:</b>\n  🔄 {stats['button_total']}\n  👤 {stats['button_unique']}\n\n"
        msg += f"<b>📈 Всего:</b>\n  🔄 <b>{stats['total']}</b>\n   <b>{stats['unique']}</b>"
        bot.reply_to(m, msg, parse_mode="HTML")
    
    elif m.text.startswith('/period'):
        parts = m.text.split()
        if len(parts) == 3:
            start = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=moscow_tz)
            end = datetime.strptime(parts[2], "%Y-%m-%d").replace(tzinfo=moscow_tz) + timedelta(days=1)
            stats = get_stats(start, end)
            
            msg = f"📊 {parts[1]} - {parts[2]}:\n\n"
            msg += f"<b>🔄 Авто:</b>\n  🔄 {stats['auto_total']}\n  👤 {stats['auto_unique']}\n\n"
            msg += f"<b>🔵 Кнопка:</b>\n  🔄 {stats['button_total']}\n  👤 {stats['button_unique']}\n\n"
            msg += f"<b> Всего:</b>\n  🔄 <b>{stats['total']}</b>\n  👤 <b>{stats['unique']}</b>"
            bot.reply_to(m, msg, parse_mode="HTML")

#  FLASK
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/')
def home():
    return "✅ Bot is alive!"

@app.route('/track', methods=['GET', 'POST', 'OPTIONS'])
def track_redirect():
    if request.method == 'OPTIONS':
        return '', 200
    
    session_id = request.args.get('session_id', 'unknown') if request.method == 'GET' else \
                 (request.get_json(force=True, silent=True) or {}).get('session_id', 'unknown')
    platform = request.args.get('platform', 'unknown') if request.method == 'GET' else \
               (request.get_json(force=True, silent=True) or {}).get('platform', 'unknown')
    watch_time = request.args.get('watch_time', 0) if request.method == 'GET' else \
                 (request.get_json(force=True, silent=True) or {}).get('watch_time', 0)
    
    redirect_type = 'button' if (request.method == 'GET' and request.args.get('vk_button') == 'true') or \
                                  (request.method == 'POST' and (request.get_json(force=True, silent=True) or {}).get('vk_button')) else 'auto'
    
    add_redirect(session_id, platform, watch_time, redirect_type)
    
    if request.method == 'GET':
        img = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(img), mimetype='image/png')
    
    return jsonify({"ok": True})

# 🔹 ЗАПУСК В ПОТОКАХ
threading.Thread(target=check_schedule, daemon=True).start()

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

threading.Thread(target=run_flask, daemon=True).start()

print("🟢 Бот запущен!")
# 🔹 УДАЛЯЕМ WEBHOOK ЧТОБЫ РАБОТАЛ POLLING
bot.remove_webhook()
bot.infinity_polling()
