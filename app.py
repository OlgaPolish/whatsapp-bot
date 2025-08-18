from flask import Flask, request, jsonify
from twilio.rest import Client
import os
from dotenv import load_dotenv
import requests

# Загрузка переменных окружения
load_dotenv()

app = Flask(__name__)

# Конфигурация Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
PORT = int(os.getenv('PORT', 5000))
BITRIX_WEBHOOK_URL = os.getenv('BITRIX_WEBHOOK_URL')

# Инициализация Twilio клиента
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Хранилище сессий (в продакшене используйте Redis или БД)
sessions = {}

# === Управление сессиями ===
def get_session(phone):
    if phone not in sessions:
        sessions[phone] = {"stage": "menu", "data": {}}
    return sessions[phone]

def clear_session(phone):
    if phone in sessions:
        sessions[phone] = {"stage": "menu", "data": {}}

# === Отправка сообщения в WhatsApp ===
def send_whatsapp_message(phone, message):
    try:
        # Убираем префикс whatsapp: если он есть
        to_number = f"whatsapp:{phone}" if not phone.startswith('whatsapp:') else phone
        
        message = client.messages.create(
            body=message,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number
        )
        print(f"✅ Сообщение отправлено: {message.sid}")
        return True
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")
        return False

# === Отправка в Bitrix24 ===
def send_lead_to_bitrix(name, city, format_type, goal, phone):
    if not BITRIX_WEBHOOK_URL:
        print("⚠️ Bitrix webhook не настроен")
        return False
    
    try:
        goal_names = {
            "1": "Накопления",
            "2": "Инвестиции", 
            "3": "Защита",
            "4": "Кредиты"
        }
        
        data = {
            "fields": {
                "TITLE": f"Лид из WhatsApp: {name}",
                "NAME": name,
                "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
                "COMMENTS": f"Город: {city}\nФормат: {format_type}\nЦель: {goal_names.get(goal, 'Неизвестно')}"
            }
        }
        
        response = requests.post(BITRIX_WEBHOOK_URL, json=data)
        if response.status_code == 200:
            print("✅ Лид отправлен в Bitrix24")
            return True
        else:
            print(f"❌ Ошибка Bitrix24: {response.text}")
            return False
    except Exception as e:
        print(f"❌ Ошибка отправки в Bitrix24: {e}")
        return False

# === Webhook для приема сообщений ===
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        # Получаем данные от Twilio
        from_number = request.values.get('From', '')
        body = request.values.get('Body', '').strip()
        
        print(f"📨 Получено сообщение от {from_number}: {body}")
        
        # Убираем префикс whatsapp: для работы с номером
        phone = from_number.replace('whatsapp:', '')
        session = get_session(phone)
        
        # Обрабатываем сообщение
        handle_message(phone, body.lower(), session)
        
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"error": str(e)}), 500

# === GET endpoint для проверки ===
@app.route("/webhook", methods=["GET"])
def webhook_get():
    return "WhatsApp Bot is running! 🤖", 200

# === Обработка сообщений ===
def handle_message(phone, text, session):
    stage = session["stage"]
    
    # Специальные триггеры
    if "спасибо я обдумаю ваше предложение" in text:
        send_whatsapp_message(phone, "Благодарю вас за доверие! 🙏\n\nПринимайте решение спокойно — мы всегда на связи, когда вы будете готовы. Удачи в планировании будущего! 💼\n\nЕсли передумаете — просто напишите 'меню'.")
        return
    
    if text == "меню" or text == "menu":
        show_menu(phone, session)
        return
    
    # Логика анкеты
    if stage == "await_name":
        session["data"]["name"] = text.title()
        session["stage"] = "await_city"
        send_whatsapp_message(phone, f"Спасибо, {text.title()}! 👋\n\nВ каком городе вы находитесь?")
    
    elif stage == "await_city":
        session["data"]["city"] = text.title()
        session["stage"] = "await_format"
        send_whatsapp_message(phone, "Как вам удобнее пройти консультацию?\n\n1️⃣ Онлайн\n2️⃣ Оффлайн\n\nНапишите цифру 1 или 2")
    
    elif stage == "await_format":
        if text == "1":
            session["data"]["format"] = "Онлайн"
            session["stage"] = "await_goal"
            send_goal_options(phone)
        elif text == "2":
            session["data"]["format"] = "Оффлайн"
            session["stage"] = "await_goal"
            send_goal_options(phone)
        else:
            send_whatsapp_message(phone, "Пожалуйста, выберите 1 (Онлайн) или 2 (Оффлайн)")
    
    elif stage == "await_goal":
        if text in ["1", "2", "3", "4"]:
            session["data"]["goal"] = text
            save_lead(phone, session)
        else:
            send_whatsapp_message(phone, "Пожалуйста, выберите цифру от 1 до 4")
    
    else:
        # Обработка команд в меню
        if text == "1" or "записаться" in text:
            start_consultation(phone, session)
        elif text == "2" or "вопросы" in text or "faq" in text:
            send_faq(phone)
        elif text == "3" or "услуги" in text:
            send_services(phone)
        else:
            show_menu(phone, session)

def send_goal_options(phone):
    message = (
        "Какова ваша основная цель?\n\n"
        "1️⃣ Накопления\n"
        "2️⃣ Инвестиции\n"
        "3️⃣ Защита\n"
        "4️⃣ Кредиты\n\n"
        "Напишите цифру от 1 до 4"
    )
    send_whatsapp_message(phone, message)

# === Главное меню ===
def show_menu(phone, session):
    session["stage"] = "menu"
    message = (
        "Добро пожаловать в DVAG! 👋
│       "Я ваш персональный помощник по финансовому планированию.\n\n"
        "Выберите, что вас интересует.\n\n"
        "1️⃣ Записаться на консультацию\n"
        "2️⃣ Частые вопросы\n"
        "3️⃣ Наши услуги\n\n"
        "Напишите цифру или ключевое слово"
    )
    send_whatsapp_message(phone, message)

# === Начало анкеты ===
def start_consultation(phone, session):
    session["stage"] = "await_name"
    session["data"] = {}
    send_whatsapp_message(phone, "Отлично! Как к вам обращаться?")

# === Частые вопросы ===
def send_faq(phone):
    faq_text = (
        "❓ *Бесплатна ли консультация?*\n"
        "Да, первая консультация — бесплатная и без обязательств.\n\n"
        
        "❓ *Как проходит онлайн-консультация?*\n"
        "Через Zoom, WhatsApp или телефон. Ссылку пришлём после записи.\n\n"
        
        "❓ *Нужны ли документы?*\n"
        "Нет, на первой встрече мы только обсуждаем цели.\n\n"
        
        "❓ *Работаете ли с иностранцами?*\n"
        "Да, мы консультируем всех, кто живёт в Германии.\n\n"
        
        "❓ *DVAG — это банк?*\n"
        "Нет. DVAG — независимый консультант с доступом к 700+ финансовым продуктам.\n\n"
        
        "Чтобы вернуться: напишите 'меню'"
    )
    send_whatsapp_message(phone, faq_text)

# === Услуги ===
def send_services(phone):
    services_text = (
        "💼 *Наши услуги:*\n\n"
        
        "💰 *1. Финансовое планирование*\n"
        "— Бюджет, накопления, цели\n\n"
        
        "📈 *2. Инвестиции и пенсия*\n"
        "— Riester, Rürup, частные пенсионные фонды\n\n"
        
        "🛡️ *3. Защита и страхование*\n"
        "— Жизнь, здоровье, имущество\n\n"
        
        "🏦 *4. Кредиты и рефинансирование*\n"
        "— Подбор ставок, ипотека\n\n"
        
        "Все решения — персональные и прозрачные.\n\n"
        "Напишите 'меню', чтобы вернуться."
    )
    send_whatsapp_message(phone, services_text)

# === Сохранение лида ===
def save_lead(phone, session):
    data = session["data"]
    name = data["name"]
    city = data["city"]
    fmt = data["format"]
    goal = data["goal"]
    
    # Отправка в Bitrix24
    success = send_lead_to_bitrix(name, city, fmt, goal, phone=phone)
    
    # Подтверждение пользователю
    goal_names = {"1": "Накопления", "2": "Инвестиции", "3": "Защита", "4": "Кредиты"}
    summary = (
        f"Спасибо, {name}! ✅\n\n"
        f"Ваши данные переданы:\n"
        f"— Город: {city}\n"
        f"— Формат: {fmt}\n"
        f"— Цель: {goal_names.get(goal, 'Неизвестно')}\n\n"
        "📅 В течение 24 часов с вами свяжется консультант для согласования времени.\n\n"
        "Благодарим за доверие! 💼"
    )
    send_whatsapp_message(phone, summary)
    
    # Сброс сессии
    clear_session(phone)

# === Запуск сервера ===
if __name__ == "__main__":
    print("🤖 Запуск WhatsApp бота...")
    print(f"🌐 Сервер будет доступен на порту {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=True)
