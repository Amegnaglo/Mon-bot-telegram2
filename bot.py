import os
import logging
import asyncio
import tempfile
import shutil
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import yt_dlp

# ==========================
# CONFIG
# ==========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Cant found TELEGRAM_BOT_TOKEN in environment variables.")

COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt")  # si besoin pour YouTube
ffmpeg_path = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg')
FFMPEG_IS_AVAILABLE = os.path.exists(ffmpeg_path) and os.access(ffmpeg_path, os.X_OK)
TELEGRAM_FILE_SIZE_LIMIT_BYTES = 500 * 1024 * 1024
TELEGRAM_FILE_SIZE_LIMIT_TEXT = "500 MB"
USER_LANGS_FILE = "user_languages.json"
SEARCH_RESULTS_LIMIT = 10

# ==========================
# LOGGING
# ==========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================
# LANGUES
# ==========================
LANG_CODES = {"English": "en", "Français": "fr"}
LANG_KEYBOARD = ReplyKeyboardMarkup([["English", "Français"]], resize_keyboard=True, one_time_keyboard=True)
user_langs = {}

LANGUAGES = {
    "en": {
        "start": "Hello! I am a bot for downloading audio and video.\nSend a link or search using /search.",
        "choose_lang": "Choose language:",
        "search_prompt": "Enter a track or artist name:",
        "choose_track": "Select a track:",
        "downloading_selected_track": "Downloading selected track...",
        "downloading_audio": "Downloading audio...",
        "downloading_video": "Downloading video...",
        "done_audio": "Done! Audio sent.",
        "done_video": "Done! Video sent.",
        "error": "Something went wrong.",
        "too_big": f"File too big (> {TELEGRAM_FILE_SIZE_LIMIT_TEXT})",
        "copyright_command": "⚠️ All downloads may be copyrighted.",
        "choose_video_quality": "Choose video quality:"
    },
    "fr": {
        "start": "Bonjour ! Je suis un bot pour télécharger audio et vidéo.\nEnvoyez un lien ou utilisez /search.",
        "choose_lang": "Choisissez la langue :",
        "search_prompt": "Entrez le titre ou artiste :",
        "choose_track": "Sélectionnez un titre :",
        "downloading_selected_track": "Téléchargement du titre sélectionné...",
        "downloading_audio": "Téléchargement audio...",
        "downloading_video": "Téléchargement vidéo...",
        "done_audio": "Fait ! Audio envoyé.",
        "done_video": "Fait ! Vidéo envoyée.",
        "error": "Une erreur est survenue.",
        "too_big": f"Fichier trop volumineux (> {TELEGRAM_FILE_SIZE_LIMIT_TEXT})",
        "copyright_command": "⚠️ Tous les téléchargements peuvent être protégés par copyright.",
        "choose_video_quality": "Choisissez la qualité vidéo :"
    }
}

# ==========================
# UTILITAIRES
# ==========================
def load_user_langs():
    global user_langs
    if os.path.exists(USER_LANGS_FILE):
        with open(USER_LANGS_FILE, 'r', encoding='utf-8') as f:
            try:
                user_langs = {int(k): v for k, v in json.load(f).items()}
            except json.JSONDecodeError:
                user_langs = {}
    else:
        user_langs = {}

def save_user_langs():
    with open(USER_LANGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_langs, f)

def get_user_lang(user_id):
    return user_langs.get(user_id, "en")

def is_url(text):
    text = text.lower().strip()
    return text.startswith("http://") or text.startswith("https://")

def blocking_yt_dlp_download(ydl_opts, url):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

def get_video_formats(url):
    ydl_opts = {'quiet': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = [
                f for f in info.get('formats', [])
                if f.get('vcodec') != 'none' and f.get('acodec') != 'none'
            ]
            return [{'format_id': f['format_id'], 'height': f.get('height', 0), 'url': f['url']} for f in formats]
    except:
        return []

# ==========================
# COMMANDES
# ==========================
async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Choose language / Choisissez la langue :", reply_markup=LANG_KEYBOARD)

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang_name = update.message.text
    if lang_name in LANG_CODES:
        user_langs[user_id] = LANG_CODES[lang_name]
        save_user_langs()
        texts = LANGUAGES[LANG_CODES[lang_name]]
        await update.message.reply_text(texts["start"])
    else:
        await update.message.reply_text("Please choose a language from the keyboard.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await choose_language(update, context)

async def copyright_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    await update.message.reply_text(texts["copyright_command"])

# ==========================
# SMART MESSAGE HANDLER
# ==========================
async def smart_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    if is_url(text):
        await ask_download_type(update, context, text)
    else:
        await handle_search_query(update, context)

# ==========================
# CHOIX AUDIO / VIDEO
# ==========================
async def ask_download_type(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    context.user_data[f'url_for_download_{user_id}'] = url
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"dl_audio_{user_id}")],
        [InlineKeyboardButton("🎥 MP4 (Video)", callback_data=f"dl_video_{user_id}")]
    ])
    await update.message.reply_text(texts["choose_track"], reply_markup=keyboard)

async def select_download_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    url = context.user_data.pop(f'url_for_download_{user_id}', None)
    if not url:
        await query.edit_message_text("URL not found.")
        return

    if query.data.startswith("dl_audio"):
        task = asyncio.create_task(download_audio(query, context, url))
        context.bot_data.setdefault('active_downloads', {})[user_id] = {'task': task}

    elif query.data.startswith("dl_video"):
        await query.edit_message_text("Fetching available video formats...")
        formats = await asyncio.to_thread(get_video_formats, url)
        if not formats:
            await query.edit_message_text("No video formats found.")
            return
        keyboard = [
            [InlineKeyboardButton(f"{f['height']}p", callback_data=f"dl_video_quality_{user_id}_{f['format_id']}")]
            for f in formats
        ]
        context.user_data[f'video_formats_{user_id}'] = {f['format_id']: f for f in formats}
        texts = LANGUAGES[get_user_lang(user_id)]
        await query.edit_message_text(texts["choose_video_quality"], reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================
# CHOIX QUALITE VIDEO
# ==========================
async def select_video_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        _, uid, format_id = query.data.split("_", 2)
        uid = int(uid)
    except:
        await query.edit_message_text("Invalid selection.")
        return
    if uid != query.from_user.id:
        await query.edit_message_text("This button is not for you.")
        return
    formats = context.user_data.get(f'video_formats_{uid}', {})
    chosen_format = formats.get(format_id)
    if not chosen_format:
        await query.edit_message_text("Format not found.")
        return
    url = query.message.text  # On récupère l’URL originale
    await query.edit_message_text(f"Downloading video in {chosen_format['height']}p...")
    task = asyncio.create_task(download_video_with_format(query, context, url, chosen_format['format_id']))
    context.bot_data.setdefault('active_downloads', {})[uid] = {'task': task}

# ==========================
# TELECHARGEMENT
# ==========================
async def download_audio(query, context, url):
    chat_id = query.message.chat_id
    temp_dir = tempfile.mkdtemp()
    await query.edit_message_text("Downloading audio...")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}],
        'quiet': True,
        'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        for file in os.listdir(temp_dir):
            path = os.path.join(temp_dir, file)
            if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text="File too big")
                continue
            with open(path, 'rb') as f:
                await context.bot.send_audio(chat_id=chat_id, audio=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text="Audio sent!")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

async def download_video_with_format(query, context, url, format_id):
    chat_id = query.message.chat_id
    temp_dir = tempfile.mkdtemp()
    ydl_opts = {
        'format': format_id,
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None,
        'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        for file in os.listdir(temp_dir):
            path = os.path.join(temp_dir, file)
            if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text="File too big")
                continue
            with open(path, 'rb') as f:
                await context.bot.send_video(chat_id=chat_id, video=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text="Video sent!")
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================
# SEARCH
# ==========================
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    await update.message.reply_text(texts["search_prompt"])
    context.user_data[f'awaiting_search_query_{user_id}'] = True

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from yt_dlp import YoutubeDL
    user_id = update.effective_user.id
    query_text = update.message.text.strip()
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'noplaylist': True}
    search_query = f"ytsearch{SEARCH_RESULTS_LIMIT}:{query_text}"
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query, download=False)
    entries = info.get('entries', [])
    if not entries:
        await update.message.reply_text("No results found.")
        return
    keyboard = [[InlineKeyboardButton(f"{idx+1}. {e.get('title')}", callback_data=f"dl_audio_{user_id}_{e.get('id')}")] for idx, e in enumerate(entries)]
    await update.message.reply_text(texts["choose_track"], reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data[f'search_results_{user_id}'] = {e.get('id'): e for e in entries}

# ==========================
# MAIN
# ==========================
def main():
    load_user_langs()
    app = Application.builder().token(TOKEN).build()
    # Commandes
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("languages", choose_language))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("copyright", copyright_command))
    # Message handler
    app.add_handler(MessageHandler(filters.Regex(f"^({'|'.join(LANG_CODES.keys())})$"), set_language))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_message_handler))
    # Callbacks
    app.add_handler(CallbackQueryHandler(select_download_type_callback, pattern="^dl_"))
    app.add_handler(CallbackQueryHandler(select_video_quality_callback, pattern="^dl_video_quality_"))
    # Menu officiel
    async def set_commands(_):
        await app.bot.set_my_commands([
            BotCommand("start", "Start / Choose language"),
            BotCommand("languages", "Change language"),
            BotCommand("search", "Search music/video"),
            BotCommand("copyright", "Copyright info")
        ])
    app.post_init = set_commands
    app.run_polling()

if __name__ == "__main__":
    main()