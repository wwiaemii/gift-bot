import os
import json
import asyncio
import logging
from datetime import datetime
from flask import Flask, request
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest

# ========== НАСТРОЙКИ ==========
TOKEN = "8770855813:AAElfaP9p4pHsJTx6MBg9KPze80tMtoqWJc"
API_ID = 35965626
API_HASH = "a7a604be2517c623176e2d66917b5039"
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

# Создаем Bot для Telegram
bot = Bot(token=TOKEN)

# Создаем Application
application = Application.builder().token(TOKEN).build()

# Класс для проверки подарков через Telethon
class GiftChecker:
    def __init__(self, api_id, api_hash):
        self.api_id = api_id
        self.api_hash = api_hash
        self.client = None
        self.initialized = False
    
    async def initialize(self):
        if not self.initialized:
            self.client = TelegramClient('gift_session', self.api_id, self.api_hash)
            await self.client.start()
            self.initialized = True
            logger.info("Telethon клиент инициализирован")
    
    async def check_user_gifts(self, username):
        try:
            await self.initialize()
            
            if username.startswith('@'):
                username = username[1:]
            
            user = await self.client.get_entity(username)
            full_user = await self.client(GetFullUserRequest(user.id))
            
            gifts_info = {
                'username': f"@{username}",
                'has_gifts': False,
                'gifts_count': 0,
                'gifts_visible': False,
                'last_active': str(user.status) if hasattr(user, 'status') else None
            }
            
            # Проверяем наличие подарков
            if hasattr(full_user, 'gifts'):
                gifts_info['has_gifts'] = len(full_user.gifts) > 0
                gifts_info['gifts_count'] = len(full_user.gifts)
                gifts_info['gifts_visible'] = True
            
            return gifts_info
            
        except Exception as e:
            logger.error(f"Ошибка при проверке {username}: {e}")
            return None
    
    async def compare_gifts(self, username1, username2):
        user1 = await self.check_user_gifts(username1)
        user2 = await self.check_user_gifts(username2)
        
        if not user1 or not user2:
            return None
        
        result = {
            'user1': user1,
            'user2': user2,
            'status': 'unknown',
            'confidence': 0,
            'details': []
        }
        
        if user1['has_gifts'] and user2['has_gifts']:
            result['status'] = 'together'
            result['confidence'] = 0.9
            result['details'].append(f"У обоих есть подарки")
        elif user1['has_gifts'] or user2['has_gifts']:
            result['status'] = 'maybe_together'
            result['confidence'] = 0.4
            result['details'].append("Подарки есть только у одного")
        else:
            result['status'] = 'apart'
            result['confidence'] = 0.6
            result['details'].append("У обоих нет подарков")
        
        return result

# Создаем экземпляр GiftChecker
gift_checker = GiftChecker(API_ID, API_HASH)

# Функции для работы с данными
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_trackings(user_id):
    data = load_data(USERS_FILE)
    return data.get(str(user_id), [])

def save_tracking(user_id, username1, username2):
    data = load_data(USERS_FILE)
    user_id = str(user_id)
    
    if user_id not in data:
        data[user_id] = []
    
    tracking = {
        'id': len(data[user_id]) + 1,
        'username1': username1,
        'username2': username2,
        'status': 'unknown',
        'last_check': datetime.now().isoformat(),
        'created_at': datetime.now().isoformat(),
        'history': []
    }
    
    data[user_id].append(tracking)
    save_data(USERS_FILE, data)
    return tracking

# Команды бота
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 Бот Индекс Подарков\n\n"
        "Команды:\n"
        "/track @user1 @user2 - отслеживать пару\n"
        "/mytracks - мои пары\n"
        "/help - помощь"
    )

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Используйте: /track @user1 @user2")
            return
        
        username1 = args[0]
        username2 = args[1]
        
        if not username1.startswith('@'):
            username1 = '@' + username1
        if not username2.startswith('@'):
            username2 = '@' + username2
        
        msg = await update.message.reply_text(f"🔍 Проверяю {username1} и {username2}...")
        
        result = await gift_checker.compare_gifts(username1, username2)
        
        if result:
            user_id = update.effective_user.id
            tracking = save_tracking(user_id, username1, username2)
            
            status_emoji = '🎉' if result['status'] == 'together' else '💔' if result['status'] == 'apart' else '❓'
            
            response = f"{status_emoji} Результат:\n\n"
            response += f"👤 {username1}: {'🎁' if result['user1']['has_gifts'] else '❌'}\n"
            response += f"👤 {username2}: {'🎁' if result['user2']['has_gifts'] else '❌'}\n\n"
            response += f"Статус: {result['status']}\n"
            response += f"ID: {tracking['id']}"
            
            await msg.edit_text(response)
        else:
            await msg.edit_text("❌ Не удалось проверить профили")
            
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await update.message.reply_text("❌ Ошибка")

async def my_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    tracks = get_user_trackings(user_id)
    
    if not tracks:
        await update.message.reply_text("У вас нет отслеживаемых пар")
        return
    
    response = "📋 Ваши пары:\n\n"
    for track in tracks:
        emoji = '🎉' if track['status'] == 'together' else '💔' if track['status'] == 'apart' else '❓'
        response += f"{emoji} [{track['id']}] {track['username1']} и {track['username2']}\n"
    
    await update.message.reply_text(response)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Помощь:\n\n"
        "/track @user1 @user2 - добавить пару\n"
        "/mytracks - список пар\n"
        "/start - приветствие"
    )

# Добавляем обработчики
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("track", track_command))
application.add_handler(CommandHandler("mytracks", my_tracks))
application.add_handler(CommandHandler("help", help_command))

# Инициализируем Application
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
loop.run_until_complete(application.initialize())
loop.run_until_complete(gift_checker.initialize())
loop.close()

logger.info("✅ Бот инициализирован!")

# Flask routes
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update_json = request.get_json(force=True)
        update = Update.de_json(update_json, bot)
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
        loop.close()
        
        return 'OK', 200
    except Exception as e:
        logger.error(f"Ошибка в webhook: {e}")
        return 'Error', 500

@app.route('/')
def index():
    return 'Gift Index Bot is running!'

@app.route('/health')
def health():
    return {'status': 'ok'}, 200

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)