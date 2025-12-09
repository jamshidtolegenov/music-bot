# bot.py
import os
import logging
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
from io import BytesIO
import tempfile

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8156755767:AAG_4Rrn0IPjh2qJoYr59-qEhO0A0jAAj_Y")
PORT = int(os.environ.get("PORT", 8080))
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 МБ

# Проверяем, запущен ли на Render
IS_RENDER = os.environ.get("RENDER", False)

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
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'ignoreerrors': True,
            'noplaylist': True,
        }

    async def search_and_download(self, query: str) -> dict:
        """Поиск и скачивание песни"""
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

            # Скачивание во временный файл
            logger.info("Начало скачивания...")
            
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp_file:
                temp_path = tmp_file.name
            
            # Обновляем опции для скачивания
            download_opts = self.ydl_opts.copy()
            download_opts['outtmpl'] = temp_path.replace('.mp3', '.%(ext)s')
            
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
                        'title': info.get('title', 'Unknown'),
                        'artist': info.get('artist', info.get('uploader', 'Unknown')),
                        'url': video_url
                    }
                else:
                    return {'success': False, 'error': 'Файл не был создан'}

        except Exception as e:
            logger.error(f"Ошибка при скачивании: {e}", exc_info=True)
            return {'success': False, 'error': f'Ошибка: {str(e)}'}

music_bot = MusicBot()

# ... (остальные функции start, help_command, handle_message остаются почти без изменений)
# НО обновите handle_message:

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
                title=result['title'],
                performer=result['artist'],
                caption=f"🎵 {result['title']}\n👤 {result['artist']}",
                filename=f"{result['title']}.mp3"
            )
            
            logger.info(f"Файл успешно отправлен: {result['title']}")
            await status_msg.delete()

        else:
            error_text = f"❌ {result['error']}"
            if 'url' in result:
                error_text += f"\n\n🔗 Вы можете послушать здесь:\n{result['url']}"
            await status_msg.edit_text(error_text)

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        await status_msg.edit_text("❌ Произошла ошибка. Попробуйте позже.")

def main():
    """Запуск бота"""
    # Создание приложения
    app = Application.builder().token(BOT_TOKEN).build()

    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запуск бота
    print("🤖 Бот запущен на Render!")
    
    if IS_RENDER:
        # На Render используем webhook
        from telegram.ext import Updater
        import threading
        from flask import Flask, request
        
        flask_app = Flask(__name__)
        
        @flask_app.route("/")
        def home():
            return "🤖 Music Bot is running!"
        
        @flask_app.route("/health")
        def health():
            return "OK", 200
        
        @flask_app.route(f"/{BOT_TOKEN}", methods=["POST"])
        def webhook():
            json_str = request.get_data().decode('UTF-8')
            update = Update.de_json(json_str, app.bot)
            app.process_update(update)
            return "OK"
        
        # Устанавливаем webhook
        webhook_url = f"https://your-app-name.onrender.com/{BOT_TOKEN}"
        app.bot.set_webhook(webhook_url)
        print(f"Webhook установлен: {webhook_url}")
        
        # Запускаем Flask сервер
        threading.Thread(target=lambda: flask_app.run(
            host="0.0.0.0",
            port=PORT,
            debug=False
        )).start()
        
        # Запускаем polling для обработки
        app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    else:
        # Локально используем polling
        print("📍 Режим: Polling (локальный запуск)")
        app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
