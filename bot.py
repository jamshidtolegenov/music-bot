import os
import logging
import asyncio
import json
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from io import BytesIO
import tempfile
from flask import Flask, request

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не установлен!")
    print("ℹ️ Установите переменную окружения BOT_TOKEN на Render.com")
    exit(1)

PORT = int(os.environ.get("PORT", 8080))
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ
IS_RENDER = os.environ.get("RENDER", "false").lower() == "true"

# Инициализация Flask приложения для webhook
flask_app = Flask(__name__)

class MusicBot:
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio[filesize<50M]',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            'ignoreerrors': True,
            'noplaylist': True,
            'geo_bypass': True,
            'geo_bypass_country': 'US',
        }

    async def search_and_download(self, query: str) -> dict:
        """Поиск и скачивание песни"""
        temp_path = None
        try:
            # Поиск на YouTube
            search_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'default_search': 'ytsearch1',
            }

            logger.info(f"Поиск: {query}")
            with yt_dlp.YoutubeDL(search_opts) as ydl:
                info = ydl.extract_info(f"ytsearch1:{query}", download=False)
                if not info or 'entries' not in info or not info['entries']:
                    return {'success': False, 'error': 'Песня не найдена'}

                video_info = info['entries'][0]
                video_id = video_info['id']
                video_url = f"https://www.youtube.com/watch?v={video_id}"
                title = video_info.get('title', 'Unknown')
                logger.info(f"Найдено: {title}")

            # Создаем временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                temp_path = tmp_file.name

            # Обновляем опции для скачивания
            download_opts = self.ydl_opts.copy()
            download_opts['outtmpl'] = temp_path.replace('.mp3', '.%(ext)s')
            
            logger.info("Начало скачивания...")
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)

                # Проверяем размер файла
                if os.path.exists(temp_path):
                    file_size = os.path.getsize(temp_path)
                    logger.info(f"Размер файла: {file_size / (1024 * 1024):.2f} МБ")

                    if file_size > MAX_FILE_SIZE:
                        os.unlink(temp_path)
                        return {
                            'success': False,
                            'error': f'Файл слишком большой ({file_size / (1024 * 1024):.1f} МБ). Максимум 50 МБ',
                            'url': video_url
                        }

                    # Читаем файл в память
                    with open(temp_path, 'rb') as f:
                        audio_data = f.read()

                    # Удаляем временный файл
                    os.unlink(temp_path)

                    return {
                        'success': True,
                        'audio_data': audio_data,
                        'title': info.get('title', title),
                        'artist': info.get('artist', info.get('uploader', 'Unknown')),
                        'url': video_url,
                        'file_size': file_size
                    }
                else:
                    # Пробуем найти файл с другим расширением
                    for ext in ['.webm', '.m4a', '.opus']:
                        alt_path = temp_path.replace('.mp3', ext)
                        if os.path.exists(alt_path):
                            file_size = os.path.getsize(alt_path)
                            with open(alt_path, 'rb') as f:
                                audio_data = f.read()
                            os.unlink(alt_path)
                            return {
                                'success': True,
                                'audio_data': audio_data,
                                'title': info.get('title', title),
                                'artist': info.get('artist', info.get('uploader', 'Unknown')),
                                'url': video_url,
                                'file_size': file_size
                            }
                    
                    return {'success': False, 'error': 'Файл не был создан'}

        except Exception as e:
            logger.error(f"Ошибка при скачивании: {e}", exc_info=True)
            # Очистка временных файлов
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            return {'success': False, 'error': f'Ошибка: {str(e)[:100]}'}

# Создаем экземпляр бота
music_bot = MusicBot()

# Создаем приложение Telegram
app = Application.builder().token(BOT_TOKEN).build()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    welcome_text = (
        "🎵 <b>Добро пожаловать в Music Bot!</b>\n\n"
        "Просто отправьте мне название песни, и я найду её для вас.\n\n"
        "<b>Примеры:</b>\n"
        "• Imagine Dragons - Believer\n"
        "• Shape of You\n"
        "• Coldplay Paradise\n\n"
        "<b>Команды:</b>\n"
        "/start - Показать это сообщение\n"
        "/help - Помощь\n\n"
        "⚠️ Максимальный размер файла: 50 МБ\n"
        "⏳ Обработка занимает 10-30 секунд"
    )
    await update.message.reply_text(welcome_text, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    help_text = (
        "📖 <b>Как пользоваться ботом:</b>\n\n"
        "1️⃣ Отправьте название песни или исполнителя\n"
        "2️⃣ Дождитесь поиска и скачивания (10-30 сек)\n"
        "3️⃣ Получите MP3 файл\n\n"
        "<b>Советы:</b>\n"
        "• Указывайте исполнителя для лучших результатов\n"
        "• Если файл слишком большой, получите ссылку на YouTube\n"
        "• Бот работает с YouTube\n\n"
        "❓ Проблемы? Попробуйте переформулировать запрос."
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    query = update.message.text.strip()

    if not query:
        await update.message.reply_text("❌ Пожалуйста, отправьте название песни.")
        return

    status_msg = await update.message.reply_text(
        f"🔍 Ищу: <b>{query}</b>\n⏳ Пожалуйста, подождите...",
        parse_mode='HTML'
    )

    try:
        logger.info(f"Обработка запроса: {query}")
        result = await music_bot.search_and_download(query)

        if result['success']:
            await status_msg.edit_text(
                f"✅ Найдено: <b>{result['title']}</b>\n📤 Отправляю файл...",
                parse_mode='HTML'
            )

            # Отправляем аудио из памяти
            await update.message.reply_audio(
                audio=BytesIO(result['audio_data']),
                title=result['title'][:64],  # Ограничение Telegram
                performer=result['artist'][:64],
                caption=f"🎵 {result['title']}\n👤 {result['artist']}\n📦 {result['file_size'] / (1024*1024):.1f} МБ",
                filename=f"{result['title'][:50]}.mp3"
            )

            logger.info(f"Файл успешно отправлен: {result['title']}")
            await status_msg.delete()

        else:
            error_text = f"❌ {result['error']}"
            if 'url' in result:
                error_text += f"\n\n🔗 Вы можете послушать здесь:\n{result['url']}"
            await status_msg.edit_text(error_text, disable_web_page_preview=True)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        await status_msg.edit_text("❌ Произошла ошибка. Попробуйте позже.")

# Регистрация обработчиков
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Flask роуты
@flask_app.route("/")
def home():
    return "🤖 Music Bot is running! Send /start to @your_bot_username"

@flask_app.route("/health")
def health():
    return "OK", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    """Обработчик webhook от Telegram"""
    if request.method == "POST":
        try:
            # Получаем обновление
            data = request.get_json()
            update = Update.de_json(data, app.bot)
            
            # Обрабатываем обновление асинхронно
            async def process_update():
                await app.initialize()
                await app.process_update(update)
            
            # Запускаем в event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(process_update())
            
            return "OK", 200
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return "Error", 500
    return "Method not allowed", 405

async def setup_webhook():
    """Установка webhook"""
    try:
        webhook_url = f"https://{os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')}/webhook"
        if webhook_url.startswith("https:///"):
            logger.warning("RENDER_EXTERNAL_HOSTNAME не установлен, webhook не настроен")
            return
        
        await app.bot.set_webhook(
            url=webhook_url,
            max_connections=10,
            allowed_updates=Update.ALL_TYPES
        )
        logger.info(f"✅ Webhook установлен: {webhook_url}")
    except Exception as e:
        logger.error(f"❌ Ошибка установки webhook: {e}")

def run_flask():
    """Запуск Flask сервера"""
    flask_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )

async def main():
    """Основная функция запуска"""
    print("=" * 50)
    print("🤖 Telegram Music Bot")
    print(f"📍 Режим: {'Render (Webhook)' if IS_RENDER else 'Local (Polling)'}")
    print(f"🔧 Версия yt-dlp: {yt_dlp.version.__version__}")
    print("=" * 50)

    if IS_RENDER:
        # Запускаем Flask в отдельном потоке
        flask_thread = threading.Thread(target=run_flask)
        flask_thread.daemon = True
        flask_thread.start()
        
        # Ждем запуска Flask
        await asyncio.sleep(2)
        
        # Устанавливаем webhook
        await setup_webhook()
        
        # Инициализируем приложение
        await app.initialize()
        
        # Держим приложение запущенным
        print("✅ Бот запущен и ожидает сообщений через webhook...")
        try:
            while True:
                await asyncio.sleep(3600)
        except KeyboardInterrupt:
            print("Бот остановлен")
    else:
        # Локальный запуск с polling
        print("📍 Запуск в режиме polling...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
        print("✅ Бот запущен и ожидает сообщений...")
        try:
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            print("Остановка бота...")
            await app.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка запуска: {e}")
        print(f"❌ Ошибка: {e}")
