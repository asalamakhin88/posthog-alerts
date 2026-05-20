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
from psycopg2.extras import RealDictCursor

# 🔑 НАСТРОЙКИ
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("⚠️ Добавьте TG_BOT_TOKEN!")

ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 105918840))
moscow_tz = pytz.timezone('Europe/Moscow')
WEBHOOK_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://posthog-alerts.onrender.com")

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
                    watch_time INTEGER)''')
    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")

init_db()

def add_redirect(session_id, platform, watch_time):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now(moscow_tz)
        c.execute('''INSERT INTO redirects (timestamp, session_id, platform, watch_time) 
                     VALUES (%s, %s, %s, %s)''', 
                  (now, session_id, platform, watch_time))
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
        conn.close()
        return total, unique
    except:
        return 0, 0

# 🔹 Telegram бот (WEBHOOK вместо polling)
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

@bot.message_handler(commands=['start', 'stats', 'today', 'period', 'reset'])
def cmd_handler(m):
    if m.chat.id != ADMIN_CHAT_ID:
        return
    
    if m.text == '/start':
        bot.reply_to(m, "🤖 Бот активен (Webhook).\n\n/stats — всё время\n/today — сегодня\n/period YYYY-MM-DD YYYY-MM-DD — период")
    
    elif m.text == '/reset':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('DELETE FROM redirects')
        conn.commit()
        conn.close()
        bot.reply_to(m, "✅ База очищена!")
    
    elif m.text == '/stats':
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM redirects')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects')
        unique = c.fetchone()[0]
        conn.close()
        bot.reply_to(m, f"📊 <b>Всего:</b>\n🔄 {total}\n👤 {unique}", parse_mode="HTML")
    
    elif m.text == '/today':
        today = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0)
        tomorrow = today + timedelta(days=1)
        total, unique = get_stats(today, tomorrow)
        bot.reply_to(m, f"📊 <b>За сегодня:</b>\n🔄 {total}\n👤 {unique}", parse_mode="HTML")
    
    elif m.text.startswith('/period'):
        parts = m.text.split()
        if len(parts) == 3:
            start = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=moscow_tz)
            end = datetime.strptime(parts[2], "%Y-%m-%d").replace(tzinfo=moscow_tz) + timedelta(days=1)
            total, unique = get_stats(start, end)
            bot.reply_to(m, f"📊 {parts[1]} - {parts[2]}:\n🔄 {total}\n👤 {unique}")

# 🔹 FLASK
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/')
def home():
    return "✅ Bot is alive! (Webhook mode)"

# Webhook от Telegram
@app.route(f"/{BOT_TOKEN}", methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_json(force=True))
    bot.process_new_updates([update])
    return '', 200

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
    
    add_redirect(session_id, platform, watch_time)
    print(f"📥 {session_id}")
    
    if request.method == 'GET':
        img = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(img), mimetype='image/png')
    
    return jsonify({"ok": True})

# 🔹 ЗАПУСК
def set_webhook():
    time.sleep(5)
    webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(webhook_url)
    print(f"✅ Webhook установлен: {webhook_url}")

threading.Thread(target=set_webhook, daemon=True).start()

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)

run_flask()
