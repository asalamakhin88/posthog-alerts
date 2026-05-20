import os
import telebot
import json
import time
import threading
import sqlite3
import io
from flask import Flask, request, send_file, make_response, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import pytz

# 🔑 НАСТРОЙКИ
BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("⚠️ Добавьте TG_BOT_TOKEN в Replit Secrets!")

ADMIN_CHAT_ID = 105918840  # Твой ID
bot = telebot.TeleBot(BOT_TOKEN)

DB_FILE = "analytics.db"
moscow_tz = pytz.timezone('Europe/Moscow')

#  Инициализация Базы Данных
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Создаем таблицу, если нет
    c.execute('''CREATE TABLE IF NOT EXISTS redirects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    session_id TEXT,
                    platform TEXT,
                    watch_time INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# 🔹 Функции работы с БД
def add_redirect(session_id, platform, watch_time):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now(moscow_tz).isoformat()
    c.execute('INSERT INTO redirects (timestamp, session_id, platform, watch_time) VALUES (?, ?, ?, ?)', 
              (now, session_id, platform, watch_time))
    conn.commit()
    conn.close()

def get_stats(start_date, end_date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Считаем общие редиректы
    c.execute('SELECT COUNT(*) FROM redirects WHERE timestamp >= ? AND timestamp < ?', 
              (start_date, end_date))
    total = c.fetchone()[0]

    # Считаем уникальных (по session_id)
    c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects WHERE timestamp >= ? AND timestamp < ?', 
              (start_date, end_date))
    unique = c.fetchone()[0]

    conn.close()
    return total, unique

# 🔹 Планировщик ежедневного отчета (00:00 МСК)
def check_schedule():
    while True:
        now = datetime.now(moscow_tz)
        if now.strftime("%H:%M") == "00:00":
            send_daily_report()
            time.sleep(60) # Спим минуту, чтобы не отправить дважды
        time.sleep(30)

def send_daily_report():
    # Статистика за вчерашний день (или за последние 24 часа, смотря как настроишь)
    # Для простоты берем "Вчера"
    today = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)

    total, unique = get_stats(yesterday.isoformat(), today.isoformat())

    msg = f"📊 <b>Отчёт за {yesterday.strftime('%d.%m.%Y')}</b>\n\n"
    msg += f"🔄 Всего редиректов: <b>{total}</b>\n"
    msg += f"👤 Уникальных: <b>{unique}</b>"

    try:
        bot.send_message(ADMIN_CHAT_ID, msg, parse_mode="HTML")
    except:
        pass

# 🔹 Команды бота
@bot.message_handler(commands=['start'])
def cmd_start(m):
    if m.chat.id == ADMIN_CHAT_ID:
        bot.reply_to(m, "🤖 Бот активен.\n\n📊 Доступные команды:\n/stats — за всё время\n/today — за сегодня\n/period YYYY-MM-DD YYYY-MM-DD — за период")

@bot.message_handler(commands=['stats'])
def cmd_all_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM redirects')
        total = c.fetchone()[0]
        c.execute('SELECT COUNT(DISTINCT session_id) FROM redirects')
        unique = c.fetchone()[0]
        conn.close()

        bot.reply_to(m, f"📊 <b>Всего за всё время:</b>\n🔄 Редиректов: {total}\n👤 Уникальных: {unique}", parse_mode="HTML")

@bot.message_handler(commands=['today'])
def cmd_today_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        today_start = datetime.now(moscow_tz).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        tomorrow_start = (datetime.now(moscow_tz) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

        total, unique = get_stats(today_start, tomorrow_start)
        bot.reply_to(m, f"📊 <b>Статистика за СЕГОДНЯ:</b>\n🔄 Редиректов: {total}\n👤 Уникальных: {unique}", parse_mode="HTML")

@bot.message_handler(commands=['period'])
def cmd_period_stats(m):
    if m.chat.id == ADMIN_CHAT_ID:
        try:
            # Формат: /period 2024-05-01 2024-05-20
            parts = m.text.split()
            if len(parts) != 3:
                bot.reply_to(m, "❌ Формат: `/period YYYY-MM-DD YYYY-MM-DD`\nПример: `/period 2024-05-01 2024-05-20`", parse_mode="Markdown")
                return

            start_str = parts[1]
            end_str = parts[2]

            # Преобразуем в datetime с учетом конца дня
            start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=moscow_tz, hour=0, minute=0, second=0)
            end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(tzinfo=moscow_tz, hour=23, minute=59, second=59)

            # Сдвигаем end_dt на следующий день 00:00 для корректного SQL запроса
            end_dt_query = (end_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0)

            total, unique = get_stats(start_dt.isoformat(), end_dt_query.isoformat())

            msg = f" <b>Статистика за период:</b>\n📅 {start_str} — {end_str}\n\n"
            msg += f"🔄 Редиректов: <b>{total}</b>\n👤 Уникальных: <b>{unique}</b>"
            bot.reply_to(m, msg, parse_mode="HTML")

        except Exception as e:
            bot.reply_to(m, f"❌ Ошибка: {e}\nИспользуйте формат YYYY-MM-DD")

# 🔹 FLASK СЕРВЕР
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

@app.route('/')
def home():
    return "✅ Bot is alive!"

@app.route('/track', methods=['GET', 'POST', 'OPTIONS'])
def track_redirect():
    if request.method == 'OPTIONS':
        return '', 200

    session_id = 'unknown'
    platform = 'unknown'
    watch_time = 0

    if request.method == 'GET':
        session_id = request.args.get('session_id', 'unknown')
        platform = request.args.get('platform', 'unknown')
        watch_time = request.args.get('watch_time', 0)
    elif request.method == 'POST':
        try:
            data = request.get_json(force=True, silent=True) or {}
            session_id = data.get('session_id', 'unknown')
            platform = data.get('platform', 'unknown')
            watch_time = data.get('watch_time', 0)
        except:
            pass

    #  ЗАПИСЬ В БАЗУ ДАННЫХ
    add_redirect(session_id, platform, watch_time)
    print(f"📥 Записано в БД: {session_id}")

    # Возврат картинки
    if request.method == 'GET':
        img_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        return send_file(io.BytesIO(img_bytes), mimetype='image/png')

    return make_response(jsonify({"ok": True}), 200)

# 🔹 ЗАПУСК
threading.Thread(target=check_schedule, daemon=True).start()

def run_flask():
    print(" Запуск сервера...")
    app.run(host='0.0.0.0', port=5000, debug=False)

threading.Thread(target=run_flask, daemon=True).start()

print("🟢 Бот запущен с поддержкой SQLite!")
bot.infinity_polling()