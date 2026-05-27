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
                    redirect_type TEXT DEFAULT 'auto',
                    video_id TEXT DEFAULT 'unknown')''')
    c.execute("ALTER TABLE redirects ADD COLUMN IF NOT EXISTS redirect_type TEXT DEFAULT 'auto'")
    c.execute("ALTER TABLE redirects ADD COLUMN IF NOT EXISTS video_id TEXT DEFAULT 'unknown'")
    conn.commit()
    conn.close()
    print("✅ База данных готова")

init_db()

def add_redirect(session_id, platform, watch_time, redirect_type='auto', video_id='unknown'):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        now = datetime.now(moscow_tz)
        c.execute('''INSERT INTO redirects (timestamp, session_id, platform, watch_time, redirect_type, video_id) 
                     VALUES (%s, %s, %s, %s, %s, %s)''', 
                  (now, session_id, platform, watch_time, redirect_type, video_id))
        conn.commit()
        conn.close()
        print(f"✅ Записано: {session_id} | {video_id} | {redirect_type}")
    except Exception as e:
        print(f"❌ Ошибка БД: {e}")

def get_stats(start_date, end_date, video_id=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        # Базовые запросы
        if video_id and video_id != 'all':
            base_query = ' WHERE timestamp >= %s AND timestamp < %s AND video_id = %s'
            params = (start_date, end_date, video_id)
            params_distinct = (start_date, end_date, video_id)
        else:
            base_query = ' WHERE timestamp >= %s AND timestamp < %s'
            params = (start_date, end_date)
            params_distinct = (start_date, end_date)
        
        c.execute(f'SELECT COUNT(*) FROM redirects{base_query}', params)
        total = c.fetchone()[0]
        
        c.execute(f'SELECT COUNT(DISTINCT session_id) FROM redirects{base_query}', params_distinct)
        unique = c.fetchone()[0]
        
        c.execute(f'SELECT COUNT(*) FROM redirects{base_query} AND redirect_type = %s', params + ('auto',))
        auto_total = c.fetchone()[0]
        
        c.execute(f'SELECT COUNT(DISTINCT session_id) FROM redirects{base_query} AND redirect_type = %s', params_distinct + ('auto',))
        auto_unique = c.fetchone()[0]
        
        c.execute(f'SELECT COUNT(*) FROM redirects{base_query} AND redirect_type = %s', params + ('button',))
        button_total = c.fetchone()[0]
        
        c.execute(f'SELECT COUNT(DISTINCT session_id) FROM redirects{base_query} AND redirect_type = %s', params_distinct + ('button',))
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

def get_all_videos_stats(start_date, end_date):
    """Получить статистику по всем видео"""
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT DISTINCT video_id FROM redirects WHERE timestamp >= %s AND timestamp < %s''', 
                  (start_date, end_date))
        videos = [row[0] for row in c.fetchall()]
        conn.close()
        
        video_stats = {}
        for vid in videos:
            video_stats[vid] = get_stats(start_date, end_date, vid)
        return video_stats
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {}

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
    video_stats = get_all_videos_stats(yesterday, today)
    
    msg = f"📊 <b>Отчёт за {yesterday.strftime('%d.%m.%Y')}</b>\n\n"
    
    for vid, stats in video_stats.items():
        msg += f"<b>🎬 Видео: {vid}</b>\n"
        msg += f"  🔄 Авто: {stats['auto_total']} | 👤 {stats['auto_unique']}\n"
        msg += f"  🔵 Кнопка: {stats['button_total']} | 👤 {stats['button_unique']}\n"
        msg += f"  📈 Всего: <b>{stats['total']}</b> | 👤 <b>{stats['unique']}</b>\n\n"
    
    try:
        bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except:
        pass

# 🔹 Telegram бот
bot = telebot.TeleBot(BOT_TOKEN)

@bot.message_handler(commands=['start'])
def cmd_start(m):
    if m.chat.id == ADMIN_CHAT_ID:
        msg = "🤖 <b>Бот аналитики видео</b>\n\n"
        msg += "<b>Команды:</b>\n"
        msg += "/today — статистика за сегодня\n"
        msg += "/stats — статистика за всё время\n"
        msg += "/video VIDEO_ID — статистика по конкретному видео\n"
        msg += "/all — все видео со статистикой"
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['today'])
def cmd_today(m):
    if m.chat.id == ADMIN_CHAT_ID:
        today_start = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        video_stats = get_all_videos_stats(today_start, tomorrow)
        
        msg = "📊 <b>Статистика за сегодня:</b>\n\n"
        for vid, stats in video_stats.items():
            msg += f"<b>🎬 {vid}</b>\n"
            msg += f"  🔄 Авто: {stats['auto_total']} | 👤 {stats['auto_unique']}\n"
            msg += f"  🔵 Кнопка: {stats['button_total']} | 👤 {stats['button_unique']}\n"
            msg += f"  📈 Всего: <b>{stats['total']}</b> | 👤 <b>{stats['unique']}</b>\n\n"
        
        if not video_stats:
            msg += "Нет данных за сегодня"
        
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        # Статистика за всё время
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT MIN(timestamp) FROM redirects')
        first_record = c.fetchone()[0]
        conn.close()
        
        if first_record:
            start_date = first_record.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = datetime.now(moscow_tz) + timedelta(days=1)
            video_stats = get_all_videos_stats(start_date, end_date)
            
            msg = "📊 <b>Статистика за всё время:</b>\n\n"
            for vid, stats in video_stats.items():
                msg += f"<b>🎬 {vid}</b>\n"
                msg += f"  🔄 Авто: {stats['auto_total']} | 👤 {stats['auto_unique']}\n"
                msg += f"  🔵 Кнопка: {stats['button_total']} | 👤 {stats['button_unique']}\n"
                msg += f"  📈 Всего: <b>{stats['total']}</b> | 👤 <b>{stats['unique']}</b>\n\n"
            
            bot.reply_to(m, msg, parse_mode="HTML")
        else:
            bot.reply_to(m, "📊 Пока нет данных")

@bot.message_handler(commands=['video'])
def cmd_video(m):
    if m.chat.id == ADMIN_CHAT_ID:
        parts = m.text.split()
        if len(parts) != 2:
            bot.reply_to(m, "❌ <b>Ошибка:</b> Используйте\n/video VIDEO_ID\n\nПример:\n/video video1", parse_mode="HTML")
            return
        
        video_id = parts[1]
        
        # За всё время
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT MIN(timestamp) FROM redirects WHERE video_id = %s', (video_id,))
        first_record = c.fetchone()[0]
        conn.close()
        
        if first_record:
            start_date = first_record.replace(hour=0, minute=0, second=0, microsecond=0)
            end_date = datetime.now(moscow_tz) + timedelta(days=1)
            stats = get_stats(start_date, end_date, video_id)
            
            msg = f"📊 <b>Статистика по видео: {video_id}</b>\n\n"
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
        else:
            bot.reply_to(m, f"📊 Нет данных для видео: {video_id}")

@bot.message_handler(commands=['all'])
def cmd_all(m):
    if m.chat.id == ADMIN_CHAT_ID:
        today_start = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today_start + timedelta(days=1)
        video_stats = get_all_videos_stats(today_start, tomorrow)
        
        msg = "📊 <b>Все видео (за сегодня):</b>\n\n"
        for vid, stats in video_stats.items():
            msg += f"<b>🎬 {vid}</b>: {stats['total']} ({stats['unique']} uniq)\n"
        
        if not video_stats:
            msg += "Нет активных видео"
        
        bot.reply_to(m, msg, parse_mode="HTML")

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
    
    session_id = request.args.get('session_id', 'unknown')
    platform = request.args.get('platform', 'unknown')
    watch_time = request.args.get('watch_time', 0)
    video_id = request.args.get('video_id', 'unknown')
    redirect_type = 'button' if request.args.get('vk_button') == 'true' else 'auto'
    
    add_redirect(session_id, platform, watch_time, redirect_type, video_id)
    
    if request.method == 'GET':
        img = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(img), mimetype='image/png')
    
    return jsonify({"ok": True})

# 🔹 ЗАПУСК
threading.Thread(target=check_schedule, daemon=True).start()

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    print(f"🌐 Запуск сервера на порту {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)

threading.Thread(target=run_flask, daemon=True).start()

print("🟢 Бот запущен!")
bot.remove_webhook()
bot.infinity_polling()
