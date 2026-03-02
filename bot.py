import os
import json
import asyncio
from datetime import datetime
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
import logging

# ========== НАСТРОЙКИ ==========
TOKEN = "8770855813:AAElfaP9p4pHsJTx6MBg9KPze80tMtoqWJc"
# ================================

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение
app = Flask(__name__)

# Файлы для хранения данных
USERS_FILE = "users.json"

# Создаем Bot отдельно (для вебхука)
bot = Bot(token=TOKEN)

# Создаем Application (НО ЗАПОЛНИМ ПОЗЖЕ)
application = None

# Функции для работы с данными
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 Бот Индекс Подарков работает!\n\n"
        "Команды:\n"
        "/start - приветствие\n"
        "/help - помощь"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Бот в процессе разработки. Скоро будут добавлены новые функции!"
    )

# Flask routes
@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков от Telegram"""
    global application
    
    # Получаем обновление от Telegram
    update_json = request.get_json(force=True)
    update = Update.de_json(update_json, bot)  # Используем отдельный bot
    
    # Создаем новый event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if application:
            loop.run_until_complete(application.process_update(update))
        else:
            logger.error("Application не инициализирован!")
    finally:
        loop.close()
    
    return 'OK', 200

@app.route('/')
def index():
    return 'Бот Индекс Подарков работает!'

@app.route('/health')
def health():
    return {'status': 'ok', 'time': datetime.now().isoformat()}

# Запуск бота
if __name__ == '__main__':
    # Создаем и инициализируем Application
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    # Инициализируем Application
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(application.initialize())
    
    print("=" * 50)
    print("Бот запущен на Render!")
    print("=" * 50)
    
    # Запускаем вебхук
    port = int(os.environ.get('PORT', 10000))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
    )