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

# 🔹 Утилиты
def format_watch_time(seconds):
    if not seconds or seconds < 0:
        return "0 сек"
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m} мин {s} сек" if m > 0 else f"{s} сек"

def get_stats(start_date, end_date, video_id=None):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        
        if video_id and video_id != 'all':
            where = "WHERE timestamp >= %s AND timestamp < %s AND video_id = %s"
            params = (start_date, end_date, video_id)
        else:
            where = "WHERE timestamp >= %s AND timestamp < %s"
            params = (start_date, end_date)
        
        # Общие + среднее время
        c.execute(f'SELECT COUNT(*), COUNT(DISTINCT session_id), AVG(watch_time) FROM redirects {where}', params)
        total, unique, avg_time = c.fetchone()
        avg_time = avg_time or 0
        
        # Авто
        c.execute(f'SELECT COUNT(*), COUNT(DISTINCT session_id) FROM redirects {where} AND redirect_type = %s', params + ('auto',))
        auto_total, auto_unique = c.fetchone()
        
        # Кнопка
        c.execute(f'SELECT COUNT(*), COUNT(DISTINCT session_id) FROM redirects {where} AND redirect_type = %s', params + ('button',))
        button_total, button_unique = c.fetchone()
        
        conn.close()
        return {
            'total': total, 'unique': unique, 'avg_time': avg_time,
            'auto_total': auto_total, 'auto_unique': auto_unique,
            'button_total': button_total, 'button_unique': button_unique
        }
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return {'total': 0, 'unique': 0, 'avg_time': 0, 'auto_total': 0, 'auto_unique': 0, 'button_total': 0, 'button_unique': 0}

def get_all_videos_stats(start_date, end_date):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''SELECT DISTINCT video_id FROM redirects WHERE timestamp >= %s AND timestamp < %s''', 
                  (start_date, end_date))
        videos = [row[0] for row in c.fetchall()]
        conn.close()
        
        return {vid: get_stats(start_date, end_date, vid) for vid in videos}
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
    for vid, s in video_stats.items():
        msg += f"<b>🎬 {vid}</b>\n"
        msg += f"  🔄 Авто: {s['auto_total']} | 👤 {s['auto_unique']} | ⏱ {format_watch_time(s['avg_time'])}\n"
        msg += f"  🔵 Кнопка: {s['button_total']} | 👤 {s['button_unique']}\n"
        msg += f"  📈 Всего: <b>{s['total']}</b> | 👤 <b>{s['unique']}</b>\n\n"
    
    try:
        bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except:
        pass

# 🔹 Telegram бот
bot = telebot.TeleBot(BOT_TOKEN)

def fmt_stats_block(s):
    return (f"  🔄 Авто: {s['auto_total']} | 👤 {s['auto_unique']} | ⏱ {format_watch_time(s['avg_time'])}\n"
            f"   Кнопка: {s['button_total']} | 👤 {s['button_unique']}\n"
            f"  📈 Всего: <b>{s['total']}</b> | 👤 <b>{s['unique']}</b>")

@bot.message_handler(commands=['start'])
def cmd_start(m):
    if m.chat.id == ADMIN_CHAT_ID:
        msg = "🤖 <b>Бот аналитики видео</b>\n\n"
        msg += "<b>Команды:</b>\n"
        msg += "/today — за сегодня\n"
        msg += "/stats — за всё время\n"
        msg += "/video VIDEO_ID — по конкретному видео\n"
        msg += "/period YYYY-MM-DD YYYY-MM-DD — за период\n"
        msg += "/all — все видео кратко"
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['today'])
def cmd_today(m):
    if m.chat.id == ADMIN_CHAT_ID:
        t = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        stats = get_all_videos_stats(t, t + timedelta(days=1))
        msg = "📊 <b>Статистика за сегодня:</b>\n\n"
        msg += "\n".join(f"<b>🎬 {v}</b>\n{fmt_stats_block(s)}" for v, s in stats.items()) or "Нет данных"
        bot.reply_to(m, msg, parse_mode="HTML")

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT MIN(timestamp) FROM redirects')
        first = c.fetchone()[0]
        conn.close()
        
        if first:
            start = first.replace(hour=0, minute=0, second=0, microsecond=0)
            stats = get_all_videos_stats(start, datetime.now(moscow_tz) + timedelta(days=1))
            msg = "📊 <b>Статистика за всё время:</b>\n\n"
            msg += "\n".join(f"<b>🎬 {v}</b>\n{fmt_stats_block(s)}" for v, s in stats.items())
            bot.reply_to(m, msg, parse_mode="HTML")
        else:
            bot.reply_to(m, "📊 Пока нет данных")

@bot.message_handler(commands=['video'])
def cmd_video(m):
    if m.chat.id == ADMIN_CHAT_ID:
        parts = m.text.split()
        if len(parts) != 2:
            bot.reply_to(m, "❌ Формат: /video VIDEO_ID\nПример: /video promo1", parse_mode="HTML")
            return
        
        vid = parts[1]
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('SELECT MIN(timestamp) FROM redirects WHERE video_id = %s', (vid,))
        first = c.fetchone()[0]
        conn.close()
        
        if first:
            start = first.replace(hour=0, minute=0, second=0, microsecond=0)
            s = get_stats(start, datetime.now(moscow_tz) + timedelta(days=1), vid)
            msg = f"📊 <b>Видео: {vid}</b>\n\n{fmt_stats_block(s)}"
            bot.reply_to(m, msg, parse_mode="HTML")
        else:
            bot.reply_to(m, f"📊 Нет данных для: {vid}")

@bot.message_handler(commands=['period'])
def cmd_period(m):
    if m.chat.id == ADMIN_CHAT_ID:
        parts = m.text.split()
        if len(parts) != 3:
            bot.reply_to(m, "❌ Формат: /period YYYY-MM-DD YYYY-MM-DD\nПример: /period 2024-05-01 2024-05-20", parse_mode="HTML")
            return
        try:
            start = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=moscow_tz)
            end = datetime.strptime(parts[2], "%Y-%m-%d").replace(tzinfo=moscow_tz) + timedelta(days=1)
            stats = get_all_videos_stats(start, end)
            msg = f"📊 <b>Период: {parts[1]} — {parts[2]}</b>\n\n"
            msg += "\n".join(f"<b> {v}</b>\n{fmt_stats_block(s)}" for v, s in stats.items()) or "Нет данных"
            bot.reply_to(m, msg, parse_mode="HTML")
        except Exception as e:
            bot.reply_to(m, f"❌ Ошибка: {e}", parse_mode="HTML")

@bot.message_handler(commands=['all'])
def cmd_all(m):
    if m.chat.id == ADMIN_CHAT_ID:
        t = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
        stats = get_all_videos_stats(t, t + timedelta(days=1))
        msg = "📊 <b>Все видео (сегодня):</b>\n\n"
        msg += "\n".join(f"<b>🎬 {v}</b>: {s['total']} ({s['unique']} uniq) |  {format_watch_time(s['avg_time'])}" for v, s in stats.items()) or "Нет активных видео"
        bot.reply_to(m, msg, parse_mode="HTML")

# 🔹 FLASK
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
