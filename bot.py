import os
import logging
import asyncio
import tempfile
import shutil
import json
from telegram import (
    Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
)
import yt_dlp

# ==========================
# LOGGING
# ==========================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================
# CONFIG
# ==========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Cant found TELEGRAM_BOT_TOKEN in environment variables.")

COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt")
ffmpeg_path = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg')
FFMPEG_IS_AVAILABLE = os.path.exists(ffmpeg_path) and os.access(ffmpeg_path, os.X_OK)
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@ytdlpdeveloper")
TELEGRAM_FILE_SIZE_LIMIT_BYTES = 500 * 1024 * 1024
TELEGRAM_FILE_SIZE_LIMIT_TEXT = "500 МБ"
USER_LANGS_FILE = "user_languages.json"
SEARCH_RESULTS_LIMIT = 10

# ==========================
# LANGUAGES
# ==========================
LANG_CODES = {"English": "en", "Français": "fr"}
LANG_KEYBOARD = ReplyKeyboardMarkup([["English", "Français"]], resize_keyboard=True, one_time_keyboard=True)

user_langs = {}

LANGUAGES = {
    "en": {
        "start": (
            "Hello! I am a bot for downloading audio and video from YouTube and SoundCloud.\n"
            "Send a link or search for a track using /search.\n"
            f"Subscribe to {REQUIRED_CHANNEL} to use the bot.\n"
            "You can convert video to MP3 by clicking the button under the video."
        ),
        "choose_lang": "Choose language:",
        "not_subscribed": f"Please subscribe to {REQUIRED_CHANNEL} first.",
        "checking": "Checking link...",
        "not_youtube": "This link is not supported.",
        "choose_download_type": "Choose download type:",
        "audio_button_mp3": "🎵 MP3 (Audio)",
        "video_button_mp4": "🎥 MP4 (Video)",
        "downloading_audio": "Downloading audio... Please wait.",
        "downloading_video": "Downloading video... Please wait.",
        "download_progress": "Downloading: {percent} at {speed}, ETA ~{eta}",
        "too_big": f"File too big (> {TELEGRAM_FILE_SIZE_LIMIT_TEXT})",
        "done_audio": "Done! Audio sent.",
        "done_video": "Done! Video sent.",
        "error": "Something went wrong.",
        "cancel_button": "Cancel",
        "cancelling": "Cancelling download...",
        "cancelled": "Download cancelled.",
        "download_in_progress": "Another download is in progress.",
        "already_cancelled_or_done": "Download already cancelled or completed.",
        "url_error_generic": "Failed to process URL. Send a valid YouTube or SoundCloud link.",
        "search_prompt": "Enter track or artist name, then click result to download.",
        "searching": "Searching...",
        "unsupported_url_in_search": "Unsupported link in search.",
        "no_results": "Nothing found.",
        "choose_track": "Select a track:",
        "downloading_selected_track": "Downloading selected track...",
        "copyright_pre": "⚠️ This may be protected by copyright. Personal use only.",
        "copyright_post": "⚠️ Material may be copyrighted. Personal use only.",
        "copyright_command": "⚠️ All downloads may be copyrighted. Contact copyrightytdlpbot@gmail.com to remove."
    },
    "fr": {
        "start": (
            "Bonjour ! Je suis un bot pour télécharger audio et vidéo depuis YouTube et SoundCloud.\n"
            "Envoyez un lien ou recherchez un titre avec /search.\n"
            f"Abonnez-vous à {REQUIRED_CHANNEL} pour utiliser le bot.\n"
            "Vous pouvez convertir la vidéo en MP3 avec le bouton sous la vidéo."
        ),
        "choose_lang": "Choisissez la langue :",
        "not_subscribed": f"Veuillez d'abord vous abonner à {REQUIRED_CHANNEL}.",
        "checking": "Vérification du lien...",
        "not_youtube": "Ce lien n'est pas supporté.",
        "choose_download_type": "Choisissez le type de téléchargement :",
        "audio_button_mp3": "🎵 MP3 (Audio)",
        "video_button_mp4": "🎥 MP4 (Vidéo)",
        "downloading_audio": "Téléchargement audio... Patientez.",
        "downloading_video": "Téléchargement vidéo... Patientez.",
        "download_progress": "Téléchargement : {percent} à {speed}, ETA ~{eta}",
        "too_big": f"Fichier trop volumineux (> {TELEGRAM_FILE_SIZE_LIMIT_TEXT})",
        "done_audio": "Fait ! Audio envoyé.",
        "done_video": "Fait ! Vidéo envoyée.",
        "error": "Une erreur est survenue.",
        "cancel_button": "Annuler",
        "cancelling": "Annulation du téléchargement...",
        "cancelled": "Téléchargement annulé.",
        "download_in_progress": "Un téléchargement est déjà en cours.",
        "already_cancelled_or_done": "Téléchargement déjà annulé ou terminé.",
        "url_error_generic": "Impossible de traiter le lien. Envoyez un lien YouTube ou SoundCloud valide.",
        "search_prompt": "Entrez le titre ou artiste, puis cliquez sur le résultat pour télécharger.",
        "searching": "Recherche...",
        "unsupported_url_in_search": "Lien non supporté dans la recherche.",
        "no_results": "Aucun résultat.",
        "choose_track": "Sélectionnez un titre :",
        "downloading_selected_track": "Téléchargement du titre sélectionné...",
        "copyright_pre": "⚠️ Ce contenu peut être protégé par copyright. Usage personnel uniquement.",
        "copyright_post": "⚠️ Matériel potentiellement protégé par copyright. Usage personnel uniquement.",
        "copyright_command": "⚠️ Tous les téléchargements peuvent être protégés par copyright. Contactez copyrightytdlpbot@gmail.com pour suppression."
    }
}

# ==========================
# HELPERS
# ==========================
def get_user_lang(user_id):
    return user_langs.get(user_id, "en")

def is_soundcloud_url(url):
    return "soundcloud.com/" in url.lower()

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

def is_url(text):
    text = text.lower().strip()
    return (
        text.startswith("http://") or text.startswith("https://")
    ) and (
        "youtube.com/" in text or "youtu.be/" in text or "soundcloud.com/" in text
    )

# ==========================
# DOWNLOAD HANDLER
# ==========================
def blocking_yt_dlp_download(ydl_opts, url):
    import yt_dlp.utils
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

# ==========================
# BOT COMMANDS
# ==========================
async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(LANGUAGES["en"]["choose_lang"], reply_markup=LANG_KEYBOARD)

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang_name = update.message.text
    lang_code = LANG_CODES.get(lang_name)
    user_id = update.effective_user.id
    if lang_code:
        user_langs[user_id] = lang_code
        save_user_langs()
        texts = LANGUAGES[lang_code]
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
# SMART MESSAGE HANDLER (Audio + Video + Search)
# ==========================
async def smart_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    text = update.message.text.strip()

    if is_url(text):
        await ask_download_type(update, context, text)
    else:
        await handle_search_query(update, context)

# ==========================
# DOWNLOAD TYPE SELECTION (Audio / Video)
# ==========================
async def ask_download_type(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    context.user_data[f'url_for_download_{user_id}'] = url

    if is_soundcloud_url(url):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts["audio_button_mp3"], callback_data=f"dltype_audio_sc_{user_id}")]
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts["audio_button_mp3"], callback_data=f"dltype_audio_mp3_{user_id}")],
            [InlineKeyboardButton(texts["video_button_mp4"], callback_data=f"dltype_video_mp4_{user_id}")]
        ])
    await update.message.reply_text(texts["choose_download_type"], reply_markup=keyboard)

# ==========================
# CALLBACK HANDLER FOR DOWNLOAD TYPE
# ==========================
async def select_download_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        parts = query.data.split("_")
        dtype = parts[1]
        ftype = parts[2]
        uid_cb = int(parts[3])
        if user_id != uid_cb:
            await query.edit_message_text("This button is not for you.")
            return
    except Exception:
        await query.edit_message_text("Invalid selection. Try again.")
        return

    url = context.user_data.pop(f'url_for_download_{user_id}', None)
    if not url:
        await query.edit_message_text("URL not found. Try again.")
        return

    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    if dtype == "audio":
        task = asyncio.create_task(download_audio(query, context, url, texts, user_id))
    elif dtype == "video":
        task = asyncio.create_task(download_video(query, context, url, texts, user_id))
    else:
        await query.edit_message_text("Unknown type.")
        return

    context.bot_data.setdefault('active_downloads', {})[user_id] = {'task': task}

# ==========================
# AUDIO DOWNLOAD
# ==========================
async def download_audio(query, context, url, texts, user_id):
    chat_id = query.message.chat_id
    temp_dir = tempfile.mkdtemp()
    await query.edit_message_text(texts["downloading_audio"])
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192'
        }],
        'quiet': True,
        'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        files = os.listdir(temp_dir)
        for file in files:
            path = os.path.join(temp_dir, file)
            size = os.path.getsize(path)
            if size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text=texts["too_big"])
                continue
            with open(path, 'rb') as f:
                await context.bot.send_audio(chat_id=chat_id, audio=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text=texts["done_audio"])
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"{texts['error']}: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================
# VIDEO DOWNLOAD
# ==========================
async def download_video(query, context, url, texts, user_id):
    chat_id = query.message.chat_id
    temp_dir = tempfile.mkdtemp()
    await query.edit_message_text(texts["downloading_video"])
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'),
        'quiet': True,
        'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        files = os.listdir(temp_dir)
        for file in files:
            path = os.path.join(temp_dir, file)
            size = os.path.getsize(path)
            if size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text=texts["too_big"])
                continue
            with open(path, 'rb') as f:
                await context.bot.send_video(chat_id=chat_id, video=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text=texts["done_video"])
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"{texts['error']}: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================
# SEARCH HANDLER
# ==========================
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    await update.message.reply_text(texts["search_prompt"])
    context.user_data[f'awaiting_search_query_{user_id}'] = True

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from yt_dlp import YoutubeDL
    query_text = update.message.text.strip()
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'noplaylist': True}
    search_query = f"ytsearch{SEARCH_RESULTS_LIMIT}:{query_text}"
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query, download=False)
    entries = info.get('entries', [])
    if not entries:
        await update.message.reply_text(texts["no_results"])
        return
    keyboard = [
        [InlineKeyboardButton(f"{idx+1}. {e.get('title')}", callback_data=f"dltype_audio_mp3_{user_id}")]
        for idx, e in enumerate(entries)
    ]
    await update.message.reply_text(texts["choose_track"], reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================
# MAIN
# ==========================
def main():
    load_user_langs()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("languages", choose_language))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("copyright", copyright_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_message_handler))
    app.add_handler(MessageHandler(filters.Regex(f"^({'|'.join(LANG_CODES.keys())})$"), set_language))
    app.add_handler(CallbackQueryHandler(select_download_type_callback, pattern="^dltype_"))
    
    async def set_commands(_):
        await app.bot.set_my_commands([
            BotCommand("start", "Start and choose language"),
            BotCommand("languages", "Change language"),
            BotCommand("search", "Search music/video (YouTube/SoundCloud)"),
            BotCommand("copyright", "Copyright info")
        ])
    app.post_init = set_commands
    app.run_polling()

if __name__ == '__main__':
    main()