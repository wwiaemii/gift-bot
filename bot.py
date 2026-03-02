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

# Создаем Bot отдельно
bot = Bot(token=TOKEN)

# Глобальная переменная для Application
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
    
    # Проверяем, инициализирован ли application
    if application is None:
        logger.error("Application не инициализирован в webhook!")
        return 'Application not initialized', 500
    
    try:
        # Получаем обновление от Telegram
        update_json = request.get_json(force=True)
        update = Update.de_json(update_json, bot)
        
        # Создаем новый event loop для каждого запроса
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Обрабатываем обновление
            loop.run_until_complete(application.process_update(update))
            logger.info(f"Обработан update: {update.update_id}")
        except Exception as e:
            logger.error(f"Ошибка при обработке update: {e}")
            return 'Error processing update', 500
        finally:
            loop.close()
        
        return 'OK', 200
        
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return 'Error', 500

@app.route('/')
def index():
    return 'Бот Индекс Подарков работает!'

@app.route('/health')
def health():
    return {'status': 'ok', 'time': datetime.now().isoformat()}, 200

# Функция для инициализации приложения
def init_application():
    global application
    if application is None:
        logger.info("Инициализация Application...")
        application = Application.builder().token(TOKEN).build()
        
        # Добавляем обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help_command))
        
        # Инициализируем в отдельном цикле событий
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(application.initialize())
            logger.info("Application успешно инициализирован!")
        finally:
            loop.close()
    
    return application

# Запуск бота
if __name__ == '__main__':
    # Инициализируем application ДО запуска Flask
    init_application()
    
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"Запуск веб-сервера на порту {port}")
    
    # Запускаем Flask (НЕ запускаем run_webhook, так как он блокирует Flask)
    app.run(host='0.0.0.0', port=port)