import os
import json
import asyncio
import aiohttp
from datetime import datetime
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
import logging
from bs4 import BeautifulSoup
import re
from telethon import TelegramClient
from telethon.tl.functions.users import GetFullUserRequest

# ========== НАСТРОЙКИ ==========
TOKEN = "8770855813:AAElfaP9p4pHsJTx6MBg9KPze80tMtoqWJc"
# ================================

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Создаем Flask приложение для вебхуков
app = Flask(__name__)

# Файлы для хранения данных
USERS_FILE = "users.json"
HISTORY_FILE = "history.json"
GIFTS_CACHE = "gifts_cache.json"

# ========== НОВЫЙ КЛАСС С TELETHON ==========
class TelegramGiftChecker:
    def __init__(self):
        # ВАЖНО: Вставьте сюда свои данные из my.telegram.org
        self.api_id = 35965626  # ЗАМЕНИТЕ НА СВОЙ API ID
        self.api_hash = "a7a604be2517c623176e2d66917b5039"  # ЗАМЕНИТЕ НА СВОЙ API HASH
        self.client = None
        self.session_file = "gift_checker_session"
        
    async def start_client(self):
        """Запускает клиент Telethon"""
        if not self.client:
            self.client = TelegramClient(self.session_file, self.api_id, self.api_hash)
            await self.client.start()
            print("✅ Клиент Telegram запущен")
    
    async def check_user_gifts(self, username):
        """
        Проверяет наличие подарков у пользователя через MTProto API
        """
        try:
            await self.start_client()
            
            # Получаем информацию о пользователе
            if username.startswith('@'):
                username = username[1:]
            
            # Получаем полную информацию о пользователе
            user = await self.client.get_entity(username)
            full_user = await self.client(GetFullUserRequest(user.id))
            
            # Ищем информацию о подарках
            gifts_info = {
                'username': f"@{username}",
                'has_gifts': False,
                'gifts_count': 0,
                'gifts_visible': False,
                'profile_photo': None,
                'last_active': None
            }
            
            # Анализируем атрибуты пользователя
            if hasattr(full_user, 'gifts'):
                gifts_info['has_gifts'] = len(full_user.gifts) > 0
                gifts_info['gifts_count'] = len(full_user.gifts)
                gifts_info['gifts_visible'] = True
            
            # Проверяем наличие подарков через другие поля
            if hasattr(full_user, 'profile_photo'):
                gifts_info['profile_photo'] = full_user.profile_photo
            
            # Информация о последней активности
            if hasattr(user, 'status'):
                gifts_info['last_active'] = str(user.status)
            
            return gifts_info
            
        except Exception as e:
            print(f"Ошибка при проверке {username}: {e}")
            return None
    
    async def compare_gifts(self, username1, username2):
        """
        Сравнивает подарки двух пользователей
        """
        user1_data = await self.check_user_gifts(username1)
        user2_data = await self.check_user_gifts(username2)
        
        if not user1_data or not user2_data:
            return None
        
        # Логика определения статуса на основе реальных подарков
        result = {
            'user1': user1_data,
            'user2': user2_data,
            'status': 'unknown',
            'confidence': 0,
            'details': []
        }
        
        # Если у обоих есть подарки - скорее всего вместе
        if user1_data['has_gifts'] and user2_data['has_gifts']:
            result['status'] = 'together'
            result['confidence'] = 0.9
            result['details'].append(f"У обоих есть подарки ({user1_data['gifts_count']} и {user2_data['gifts_count']})")
        
        # Если подарки только у одного - возможно, подарил кто-то другой
        elif user1_data['has_gifts'] or user2_data['has_gifts']:
            result['status'] = 'maybe_together'
            result['confidence'] = 0.4
            result['details'].append("Подарки есть только у одного")
        
        # Если нет подарков ни у кого
        else:
            result['status'] = 'apart'
            result['confidence'] = 0.6
            result['details'].append("У обоих нет подарков")
        
        return result
    
    async def close(self):
        """Закрывает клиент"""
        if self.client:
            await self.client.disconnect()
# ========== КОНЕЦ НОВОГО КЛАССА ==========

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
        'check_count': 0,
        'history': []
    }
    
    data[user_id].append(tracking)
    save_data(USERS_FILE, data)
    return tracking

def update_tracking_status(user_id, tracking_id, new_status, details=None):
    data = load_data(USERS_FILE)
    user_id = str(user_id)
    
    if user_id in data:
        for tracking in data[user_id]:
            if tracking['id'] == tracking_id:
                old_status = tracking['status']
                tracking['status'] = new_status
                tracking['last_check'] = datetime.now().isoformat()
                tracking['check_count'] = tracking.get('check_count', 0) + 1
                
                # Сохраняем в историю
                if 'history' not in tracking:
                    tracking['history'] = []
                
                tracking['history'].append({
                    'timestamp': datetime.now().isoformat(),
                    'old_status': old_status,
                    'new_status': new_status,
                    'details': details
                })
                
                # Ограничиваем историю
                if len(tracking['history']) > 20:
                    tracking['history'] = tracking['history'][-20:]
                
                save_data(USERS_FILE, data)
                return True
    return False

# Создаем экземпляр проверяльщика
gift_checker = TelegramGiftChecker()

# ========== ВСЕ КОМАНДЫ БОТА ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = """
🎁 Добро пожаловать в бот ИНДЕКС ПОДАРКОВ!

Я отслеживаю подарки в Telegram профилях и анализирую отношения.

📋 Доступные команды:

/track @username1 @username2 - начать отслеживание пары
Пример: /track @anna @sergey

/mytracks - мои отслеживаемые пары
/check [ID] - проверить конкретную пару
/history [ID] - история изменений
/analyze @username - анализ профиля
/stop [ID] - остановить отслеживание
/help - подробная помощь

🔍 Как это работает:
Бот анализирует видимость подарков в профилях и делает вывод о статусе отношений.
    """
    await update.message.reply_text(welcome)

async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления пары на отслеживание"""
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ Используйте формат: /track @username1 @username2\n"
                "Например: /track @anna @sergey"
            )
            return
        
        username1 = args[0]
        username2 = args[1]
        
        if not username1.startswith('@'):
            username1 = '@' + username1
        if not username2.startswith('@'):
            username2 = '@' + username2
        
        msg = await update.message.reply_text(
            f"🔍 Проверяю профили {username1} и {username2}...\n"
            f"Это может занять несколько секунд."
        )
        
        result = await gift_checker.compare_gifts(username1, username2)
        
        if result:
            user_id = update.effective_user.id
            tracking = save_tracking(user_id, username1, username2)
            
            status_emoji = {
                'together': '🎉',
                'maybe_together': '🤔',
                'apart': '💔',
                'uncertain': '❓',
                'unknown': '❓'
            }.get(result['status'], '❓')
            
            status_text = {
                'together': 'ВМЕСТЕ!',
                'maybe_together': 'Возможно вместе',
                'apart': 'Расстались',
                'uncertain': 'Неопределенно',
                'unknown': 'Неизвестно'
            }.get(result['status'], 'Неизвестно')
            
            response = f"{status_emoji} РЕЗУЛЬТАТ АНАЛИЗА\n\n"
            response += f"👤 {username1}\n"
            response += f"   Подарки: {'🎁 есть' if result['user1']['has_gifts'] else '❌ нет'}\n"
            response += f"   Видимость: {'✅ открыты' if result['user1']['gifts_visible'] else '🔒 скрыты'}\n\n"
            
            response += f"👤 {username2}\n"
            response += f"   Подарки: {'🎁 есть' if result['user2']['has_gifts'] else '❌ нет'}\n"
            response += f"   Видимость: {'✅ открыты' if result['user2']['gifts_visible'] else '🔒 скрыты'}\n\n"
            
            response += f"📊 ВЕРДИКТ: {status_text}\n"
            response += f"📈 Уверенность: {int(result['confidence']*100)}%\n\n"
            
            response += f"🆔 ID отслеживания: {tracking['id']}\n"
            response += "Теперь я буду следить за изменениями!"
            
            await msg.edit_text(response)
            update_tracking_status(user_id, tracking['id'], result['status'], result['details'])
            
        else:
            await msg.edit_text(
                "❌ Не удалось проверить профили.\n"
                "Возможные причины:\n"
                "- Профили не существуют\n"
                "- Профили закрыты\n"
                "- Слишком много запросов"
            )
            
    except Exception as e:
        logger.error(f"Ошибка в track_command: {e}")
        await update.message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

async def my_tracks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все отслеживаемые пары"""
    user_id = update.effective_user.id
    tracks = get_user_trackings(user_id)
    
    if not tracks:
        await update.message.reply_text(
            "У вас пока нет отслеживаемых пар.\n"
            "Используйте /track @username1 @username2 чтобы добавить"
        )
        return
    
    response = "📋 ВАШИ ОТСЛЕЖИВАЕМЫЕ ПАРЫ:\n\n"
    
    for track in tracks:
        status_emoji = {
            'together': '🎉',
            'maybe_together': '🤔',
            'apart': '💔',
            'uncertain': '❓',
            'unknown': '❓'
        }.get(track['status'], '❓')
        
        response += f"{status_emoji} [{track['id']}] {track['username1']} и {track['username2']}\n"
        response += f"   Статус: {track['status']}\n"
        response += f"   Проверок: {track.get('check_count', 0)}\n"
        response += f"   Последняя: {track['last_check'][:16]}\n\n"
    
    await update.message.reply_text(response)

async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет конкретную пару"""
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Используйте: /check [ID пары]")
            return
        
        tracking_id = int(args[0])
        user_id = update.effective_user.id
        tracks = get_user_trackings(user_id)
        
        track = next((t for t in tracks if t['id'] == tracking_id), None)
        
        if not track:
            await update.message.reply_text("Пара с таким ID не найдена")
            return
        
        msg = await update.message.reply_text(
            f"🔍 Проверяю {track['username1']} и {track['username2']}..."
        )
        
        result = await gift_checker.compare_gifts(
            track['username1'], 
            track['username2']
        )
        
        if result:
            update_tracking_status(user_id, tracking_id, result['status'], result['details'])
            
            if result['status'] != track['status']:
                emoji = "🎉" if result['status'] == 'together' else "💔"
                response = f"{emoji} СТАТУС ИЗМЕНИЛСЯ!\n\n"
            else:
                response = "✅ СТАТУС НЕ ИЗМЕНИЛСЯ\n\n"
            
            response += f"👤 {track['username1']}: {'🎁' if result['user1']['has_gifts'] else '❌'}\n"
            response += f"👤 {track['username2']}: {'🎁' if result['user2']['has_gifts'] else '❌'}\n"
            response += f"📊 Текущий статус: {result['status']}\n"
            
            await msg.edit_text(response)
        else:
            await msg.edit_text("❌ Не удалось проверить профили")
            
    except Exception as e:
        logger.error(f"Ошибка в check_command: {e}")
        await update.message.reply_text("❌ Ошибка при проверке")

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю изменений пары"""
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Используйте: /history [ID пары]")
            return
        
        tracking_id = int(args[0])
        user_id = update.effective_user.id
        tracks = get_user_trackings(user_id)
        
        track = next((t for t in tracks if t['id'] == tracking_id), None)
        
        if not track:
            await update.message.reply_text("Пара с таким ID не найдена")
            return
        
        if not track.get('history'):
            await update.message.reply_text("История изменений пока пуста")
            return
        
        response = f"📜 ИСТОРИЯ: {track['username1']} и {track['username2']}\n\n"
        
        for event in track['history'][-10:]:
            emoji = "🎉" if event['new_status'] == 'together' else "💔"
            response += f"{emoji} {event['timestamp'][:16]}\n"
            response += f"   {event['old_status']} → {event['new_status']}\n"
            if event.get('details'):
                response += f"   {', '.join(event['details'])}\n"
            response += "\n"
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Ошибка в history_command: {e}")
        await update.message.reply_text("❌ Ошибка при получении истории")

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализирует отдельный профиль"""
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Используйте: /analyze @username")
            return
        
        username = args[0]
        if not username.startswith('@'):
            username = '@' + username
        
        msg = await update.message.reply_text(f"🔍 Анализирую профиль {username}...")
        
        result = await gift_checker.check_user_gifts(username)
        
        if result:
            response = f"📊 АНАЛИЗ ПРОФИЛЯ {username}\n\n"
            response += f"🎁 Наличие подарков: {'✅ есть' if result['has_gifts'] else '❌ нет'}\n"
            response += f"👁 Видимость: {'✅ открыты' if result['gifts_visible'] else '🔒 скрыты'}\n"
            if result['gifts_count'] > 0:
                response += f"📦 Количество: {result['gifts_count']}\n"
            if result['last_active']:
                response += f"⏰ Активность: {result['last_active']}\n"
            
            await msg.edit_text(response)
        else:
            await msg.edit_text("❌ Не удалось проанализировать профиль")
            
    except Exception as e:
        logger.error(f"Ошибка в analyze_command: {e}")
        await update.message.reply_text("❌ Ошибка при анализе")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Останавливает отслеживание пары"""
    try:
        args = context.args
        if not args:
            await update.message.reply_text("Используйте: /stop [ID пары]")
            return
        
        tracking_id = int(args[0])
        user_id = update.effective_user.id
        data = load_data(USERS_FILE)
        user_id_str = str(user_id)
        
        if user_id_str in data:
            data[user_id_str] = [t for t in data[user_id_str] if t['id'] != tracking_id]
            save_data(USERS_FILE, data)
            await update.message.reply_text(f"✅ Отслеживание пары {tracking_id} остановлено")
        else:
            await update.message.reply_text("Пара не найдена")
            
    except Exception as e:
        logger.error(f"Ошибка в stop_command: {e}")
        await update.message.reply_text("❌ Ошибка при остановке")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🔍 ПОДРОБНАЯ ИНСТРУКЦИЯ:

1️⃣ ДОБАВЛЕНИЕ ПАРЫ:
/track @username1 @username2
Пример: /track @anna @sergey

2️⃣ ПРОСМОТР ВСЕХ ПАР:
/mytracks - список всех отслеживаемых

3️⃣ ПРОВЕРКА СТАТУСА:
/check [ID] - проверить конкретную пару

4️⃣ ИСТОРИЯ:
/history [ID] - история изменений

5️⃣ АНАЛИЗ ПРОФИЛЯ:
/analyze @username - инфо о пользователе

6️⃣ УПРАВЛЕНИЕ:
/stop [ID] - удалить пару из отслеживания

🎯 КАК ЭТО РАБОТАЕТ:
Бот анализирует веб-версию Telegram и ищет:
- Наличие подарков в профиле
- Видимость подарков
- Изменения в статусе

⚠️ ВАЖНО:
- Бот видит только публичную информацию
- Если профиль скрыт - анализ может быть неточным
- Для точности проверяйте несколько раз в день
    """
    await update.message.reply_text(help_text)

# Периодическая проверка всех пар
async def check_all_tracks(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет все отслеживаемые пары (запускается каждый час)"""
    logger.info("Запуск периодической проверки всех пар")
    
    data = load_data(USERS_FILE)
    
    for user_id_str, tracks in data.items():
        for track in tracks:
            try:
                logger.info(f"Проверка пары {track['username1']} и {track['username2']}")
                
                result = await gift_checker.compare_gifts(
                    track['username1'],
                    track['username2']
                )
                
                if result and result['status'] != track['status']:
                    update_tracking_status(
                        int(user_id_str),
                        track['id'],
                        result['status'],
                        result['details']
                    )
                    
                    try:
                        status_emoji = "🎉" if result['status'] == 'together' else "💔"
                        await context.bot.send_message(
                            chat_id=int(user_id_str),
                            text=f"{status_emoji} ИЗМЕНЕНИЕ СТАТУСА!\n\n"
                                 f"Пара: {track['username1']} и {track['username2']}\n"
                                 f"Новый статус: {result['status']}"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления: {e}")
                
                await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Ошибка при проверке пары {track.get('id')}: {e}")
                continue
    
    logger.info("Периодическая проверка завершена")

# Flask routes для вебхуков
@app.route('/webhook', methods=['POST'])
def webhook():
    """Обработка вебхуков от Telegram"""
    update = Update.de_json(request.get_json(force=True), application.bot)
    asyncio.run(application.process_update(update))
    return 'OK', 200

@app.route('/')
def index():
    return 'Бот Индекс Подарков работает!'

@app.route('/health')
def health():
    return {'status': 'ok', 'time': datetime.now().isoformat()}

# Запуск бота
if __name__ == '__main__':
    # Создаем приложение бота
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("mytracks", my_tracks))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("history", history_command))
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # Определяем режим запуска
    if os.environ.get('RENDER'):
        # На Render.com используем вебхук
        port = int(os.environ.get('PORT', 10000))
        application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=TOKEN,
            webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME')}/webhook"
        )
    else:
        # Локально используем поллинг
        print("=" * 50)
        print("БОТ ЗАПУЩЕН В РЕЖИМЕ ПОЛЛИНГА")
        print("=" * 50)
        print("Для остановки нажмите Ctrl+C")
        print("=" * 50)
        application.run_polling()