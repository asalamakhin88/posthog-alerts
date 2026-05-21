import os
import telebot
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
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", 105918840))
moscow_tz = pytz.timezone('Europe/Moscow')

# 🔹 PostgreSQL
def get_db_connection():
    return psycopg2.connect(os.environ.get("DATABASE_URL"))

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
        print(f"✅ Записано: {session_id} | {platform} | {redirect_type}")
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
            'total': total, 
            'unique': unique, 
            'auto_total': auto_total, 
            'auto_unique': auto_unique, 
            'button_total': button_total, 
            'button_unique': button_unique
        }
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {
            'total': 0, 
            'unique': 0, 
            'auto_total': 0, 
            'auto_unique': 0, 
            'button_total': 0, 
            'button_unique': 0
        }

# 🔹 Планировщик ежедневных отчетов
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
    msg += f"<b>🔄 Автоматические редиректы:</b>\n"
    msg += f"  🔄 Всего: {stats['auto_total']}\n"
    msg += f"  👤 Уникальных: {stats['auto_unique']}\n\n"
    msg += f"<b>🔵 Переходы по кнопке:</b>\n"
    msg += f"  🔄 Всего: {stats['button_total']}\n"
    msg += f"  👤 Уникальных: {stats['button_unique']}\n\n"
    msg += f"<b>📈 Всего:</b>\n"
    msg += f"  🔄 <b>{stats['total']}</b>\n"
    msg += f"  👤 <b>{stats['unique']}</b>"
    
    try:
        bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except Exception as e:
        print(f"❌ Не удалось отправить отчёт: {e}")

# 🔹 Telegram бот
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

@bot.message_handler(commands=['start'])
def cmd_start(m):
    if m.chat.id == ADMIN_CHAT_ID:
        msg = "🤖 <b>Бот аналитики видео</b>\n\n"
        msg += "<b>Доступные команды:</b>\n"
        msg += "/stats — статистика за всё время\n"
        msg += "/today — статистика за сегодня\n"
        msg += "/period YYYY-MM-DD YYYY-MM-DD — статистика за период"
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM redirects')
        total = c.fetchone()[0]
        
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects')
        unique = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM redirects WHERE redirect_type = 'auto'")
        auto_total = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT session_id) FROM redirects WHERE redirect_type = 'auto'")
        auto_unique = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM redirects WHERE redirect_type = 'button'")
        button_total = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT session_id) FROM redirects WHERE redirect_type = 'button'")
        button_unique = c.fetchone()[0]
        
        conn.close()
        
        msg = "📊 <b>Статистика за всё время:</b>\n\n"
        msg += "<b>🔄 Автоматические редиректы:</b>\n"
        msg += f"  🔄 Всего: {auto_total}\n"
        msg += f"  👤 Уникальных: {auto_unique}\n\n"
        msg += "<b>🔵 Переходы по кнопке:</b>\n"
        msg += f"  🔄 Всего: {button_total}\n"
        msg += f"  👤 Уникальных: {button_unique}\n\n"
        msg += "<b>📈 Всего:</b>\n"
        msg += f"  🔄 <b>{total}</b>\n"
        msg += f"  👤 <b>{unique}</b>"
        
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['today'])
def cmd_today(m):
    if m.chat.id == ADMIN_CHAT_ID:
        today_start = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        stats = get_stats(today_start, tomorrow)
        
        msg = "📊 <b>Статистика за сегодня:</b>\n\n"
        msg += "<b>🔄 Автоматические редиректы:</b>\n"
        msg += f"  🔄 Всего: {stats['auto_total']}\n"
        msg += f"  👤 Уникальных: {stats['auto_unique']}\n\n"
        msg += "<b>🔵 Переходы по кнопке:</b>\n"
        msg += f"  🔄 Всего: {stats['button_total']}\n"
        msg += f"  👤 Уникальных: {stats['button_unique']}\n\n"
        msg += "<b>📈 Всего:</b>\n"
        msg += f"  🔄 <b>{stats['total']}</b>\n"
        msg += f"  👤 <b>{stats['unique']}</b>"
        
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['period'])
def cmd_period(m):
    if m.chat.id == ADMIN_CHAT_ID:
        parts = m.text.split()
        if len(parts) != 3:
            bot.reply_to(m, "❌ <b>Ошибка:</b> Используйте формат\n/period YYYY-MM-DD YYYY-MM-DD\n\nПример:\n/period 2024-05-01 2024-05-20", parse_mode="HTML")
            return
        
        try:
            start_date = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=moscow_tz, hour=0, minute=0, second=0, microsecond=0)
            end_date = datetime.strptime(parts[2], "%Y-%m-%d").replace(tzinfo=moscow_tz, hour=23, minute=59, second=59, microsecond=999999)
            stats = get_stats(start_date, end_date + timedelta(days=1))
            
            msg = f"📊 <b>Статистика за период:</b>\n"
            msg += f"📅 {parts[1]} — {parts[2]}\n\n"
            msg += "<b>🔄 Автоматические редиректы:</b>\n"
            msg += f"  🔄 Всего: {stats['auto_total']}\n"
            msg += f"  👤 Уникальных: {stats['auto_unique']}\n\n"
            msg += "<b>🔵 Переходы по кнопке:</b>\n"
            msg += f"  🔄 Всего: {stats['button_total']}\n"
            msg += f"  👤 Уникальных: {stats['button_unique']}\n\n"
            msg += "<b>📈 Всего:</b>\n"
            msg += f"  🔄 <b>{stats['total']}</b>\n"
            msg += f"  👤 <b>{stats['unique']}</b>"
            
            bot.reply_to(m, msg, parse_mode="HTML")
        except Exception as e:
            bot.reply_to(m, f"❌ <b>Ошибка:</b> {e}\n\nИспользуйте формат YYYY-MM-DD", parse_mode="HTML")

# 🔹 FLASK сервер
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/')
def home():
    return "✅ Bot is alive!"

@app.route('/track', methods=['GET', 'POST', 'OPTIONS'])
def track():
    if request.method == 'OPTIONS':
        return '', 200
    
    # Читаем все данные из URL параметров (для GET и POST)
    session_id = request.args.get('session_id', 'unknown')
    platform = request.args.get('platform', 'unknown')
    watch_time = request.args.get('watch_time', 0)
    
    # Определяем тип редиректа
    redirect_type = 'button' if request.args.get('vk_button') == 'true' else 'auto'
    
    # Записываем в базу
    add_redirect(session_id, platform, watch_time, redirect_type)
    
    # Возвращаем картинку для GET запросов
    if request.method == 'GET':
        img = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(img), mimetype='image/png')
    
    return jsonify({"ok": True})

# 🔹 ЗАПУСК ПОТОКОВ
threading.Thread(target=check_schedule, daemon=True).start()

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Запуск сервера на порту {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)

threading.Thread(target=run_flask, daemon=True).start()

print("🟢 Бот запущен!")
bot.remove_webhook()
bot.infinity_polling(skip_pending=True)
