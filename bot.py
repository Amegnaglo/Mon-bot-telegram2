import os
import logging
import asyncio
import tempfile
import shutil
import json
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import yt_dlp

# ==========================
# CONFIG
# ==========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Can't find TELEGRAM_BOT_TOKEN in environment variables.")

COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt")
FFMPEG_PATH = os.getenv("FFMPEG_PATH", "/usr/bin/ffmpeg")
FFMPEG_IS_AVAILABLE = os.path.exists(FFMPEG_PATH) and os.access(FFMPEG_PATH, os.X_OK)
TELEGRAM_FILE_SIZE_LIMIT_BYTES = 500 * 1024 * 1024
USER_LANGS_FILE = "user_languages.json"
SEARCH_RESULTS_LIMIT = 6  # nombre de résultats lors d'une recherche

# ==========================
# LOGGING
# ==========================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("telegram_bot")

# ==========================
# LANGUES
# ==========================
LANG_CODES = {"English": "en", "Français": "fr"}
LANG_KEYBOARD = ReplyKeyboardMarkup([["English", "Français"]], resize_keyboard=True, one_time_keyboard=True)

user_langs: dict[int, str] = {}

LANGUAGES = {
    "en": {
        "start": "Hello! Send a link or use /search to find tracks.",
        "choose_lang": "Choose language:",
        "search_prompt": "Enter a track or artist name:",
        "choose_track": "Select a track:",
        "downloading_audio": "Downloading audio...",
        "downloading_video": "Downloading video...",
        "done_audio": "Done! Audio sent.",
        "done_video": "Done! Video sent.",
        "error": "Something went wrong.",
        "too_big": "File too big (> 500MB)",
        "choose_quality": "Choose video quality:",
    },
    "fr": {
        "start": "Bonjour ! Envoyez un lien ou utilisez /search pour rechercher des titres.",
        "choose_lang": "Choisissez la langue :",
        "search_prompt": "Entrez le titre ou artiste :",
        "choose_track": "Sélectionnez un titre :",
        "downloading_audio": "Téléchargement audio...",
        "downloading_video": "Téléchargement vidéo...",
        "done_audio": "Fait ! Audio envoyé.",
        "done_video": "Fait ! Vidéo envoyée.",
        "error": "Une erreur est survenue.",
        "too_big": "Fichier trop volumineux (> 500MB)",
        "choose_quality": "Choisissez la qualité vidéo :",
    }
}

# ==========================
# HELPERS: lang persistence
# ==========================
def load_user_langs() -> None:
    global user_langs
    if os.path.exists(USER_LANGS_FILE):
        try:
            with open(USER_LANGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                user_langs = {int(k): v for k, v in data.items()}
        except Exception:
            user_langs = {}
    else:
        user_langs = {}

def save_user_langs() -> None:
    try:
        with open(USER_LANGS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in user_langs.items()}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Could not save user langs: %s", e)

def get_user_lang(user_id: int) -> str:
    return user_langs.get(user_id, "en")

# ==========================
# UTIL
# ==========================
def is_url(text: str) -> bool:
    t = text.lower().strip()
    return t.startswith("http://") or t.startswith("https://")

def blocking_yt_dlp_download(ydl_opts: dict, url: str) -> None:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

# ==========================
# HANDLERS
# ==========================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    lang = get_user_lang(uid)
    await update.message.reply_text(LANGUAGES[lang]["start"], reply_markup=LANG_KEYBOARD)

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    lang = get_user_lang(uid)
    await update.message.reply_text(LANGUAGES[lang]["choose_lang"], reply_markup=LANG_KEYBOARD)

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    text = update.message.text.strip()
    if text in LANG_CODES:
        code = LANG_CODES[text]
        user_langs[uid] = code
        save_user_langs()
        await update.message.reply_text(LANGUAGES[code]["start"])
    else:
        await update.message.reply_text("Please select a language from the keyboard.")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    lang = get_user_lang(uid)
    await update.message.reply_text(LANGUAGES[lang]["search_prompt"])
    context.user_data[f"awaiting_search_query_{uid}"] = True

async def smart_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()
    uid = update.effective_user.id
    if context.user_data.pop(f"awaiting_search_query_{uid}", False):
        # treat as search query
        await handle_search_query(update, context)
        return

    if is_url(text):
        # store url and ask type
        context.user_data[f"url_for_download_{uid}"] = text
        lang = get_user_lang(uid)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"dl_audio::{uid}")],
            [InlineKeyboardButton("🎥 MP4 (Video)", callback_data=f"dl_video::{uid}")]
        ])
        await update.message.reply_text(LANGUAGES[lang]["choose_track"], reply_markup=keyboard)
    else:
        # fallback: treat as search
        await handle_search_query(update, context)

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from yt_dlp import YoutubeDL
    uid = update.effective_user.id
    lang = get_user_lang(uid)
    query_text = update.message.text.strip()
    ydl_opts = {"quiet": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
    search_query = f"ytsearch{SEARCH_RESULTS_LIMIT}:{query_text}"
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
    except Exception as e:
        logger.exception("Search failed")
        await update.message.reply_text(LANGUAGES[lang]["error"])
        return

    entries = info.get("entries", []) if info else []
    if not entries:
        await update.message.reply_text(LANGUAGES[lang]["error"])
        return

    keyboard = []
    for idx, e in enumerate(entries):
        title = e.get("title") or "Unknown"
        vid = e.get("id")
        # callback format: dl_from_search::<user_id>::<yt_id>
        keyboard.append([InlineKeyboardButton(f"{idx+1}. {title}", callback_data=f"dl_from_search::{uid}::{vid}")])

    await update.message.reply_text(LANGUAGES[lang]["choose_track"], reply_markup=InlineKeyboardMarkup(keyboard))

# Callback when user clicked download type for a direct URL
async def select_download_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("::")
    if len(parts) < 2:
        await query.edit_message_text("Invalid callback.")
        return
    action = parts[0]  # dl_audio or dl_video
    sel_user_id = int(parts[1])
    uid = query.from_user.id

    if uid != sel_user_id:
        await query.edit_message_text("This button is not for you.")
        return

    url = context.user_data.get(f"url_for_download_{uid}")
    if not url:
        await query.edit_message_text("URL not found.")
        return

    if action == "dl_audio":
        # start download_audio
        task = asyncio.create_task(download_audio_for_url(query, context, url))
        context.application.bot_data.setdefault("active_downloads", {})[uid] = task
    elif action == "dl_video":
        # ask quality
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1080p", callback_data=f"dl_video_quality::1080::{uid}")],
            [InlineKeyboardButton("720p", callback_data=f"dl_video_quality::720::{uid}")],
            [InlineKeyboardButton("480p", callback_data=f"dl_video_quality::480::{uid}")],
        ])
        await query.edit_message_text(LANGUAGES[get_user_lang(uid)]["choose_quality"], reply_markup=keyboard)
    else:
        await query.edit_message_text("Unknown action.")

# Callback after user chooses quality for a direct URL
async def select_video_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("::")
    if len(parts) != 3:
        await query.edit_message_text("Invalid selection.")
        return
    _, quality, sel_user_id_str = parts
    sel_user_id = int(sel_user_id_str)
    uid = query.from_user.id
    if uid != sel_user_id:
        await query.edit_message_text("This button is not for you.")
        return

    url = context.user_data.get(f"url_for_download_{uid}")
    if not url:
        await query.edit_message_text("URL not found.")
        return

    task = asyncio.create_task(download_video_for_url(query, context, url, quality))
    context.application.bot_data.setdefault("active_downloads", {})[uid] = task

# Callback when user selects an item from search results
async def select_search_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("::")
    # expected: dl_from_search::<requester_uid>::<yt_id>
    if len(parts) != 3:
        await query.edit_message_text("Invalid selection.")
        return
    _, requester_uid_str, yt_id = parts
    requester_uid = int(requester_uid_str)
    uid = query.from_user.id
    if uid != requester_uid:
        await query.edit_message_text("This button is not for you.")
        return

    # now ask audio or video for that yt_id
    context.user_data[f"yt_id_for_{uid}"] = yt_id
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"dl_search_audio::{uid}::{yt_id}")],
        [InlineKeyboardButton("🎥 MP4 (Video)", callback_data=f"dl_search_video::{uid}::{yt_id}")]
    ])
    await query.edit_message_text("Choose format:", reply_markup=keyboard)

# Callback when user chooses format for a search result
async def select_search_format_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("::")
    if len(parts) < 3:
        await query.edit_message_text("Invalid selection.")
        return
    action = parts[0]  # dl_search_audio or dl_search_video
    requester_uid = int(parts[1])
    yt_id = parts[2]
    uid = query.from_user.id
    if uid != requester_uid:
        await query.edit_message_text("This button is not for you.")
        return

    url = f"https://www.youtube.com/watch?v={yt_id}"
    if action == "dl_search_audio":
        task = asyncio.create_task(download_audio_for_url(query, context, url))
        context.application.bot_data.setdefault("active_downloads", {})[uid] = task
    else:
        # ask quality
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("1080p", callback_data=f"dl_video_quality::{1080}::{uid}::{yt_id}")],
            [InlineKeyboardButton("720p", callback_data=f"dl_video_quality::{720}::{uid}::{yt_id}")],
            [InlineKeyboardButton("480p", callback_data=f"dl_video_quality::{480}::{uid}::{yt_id}")],
        ])
        await query.edit_message_text(LANGUAGES[get_user_lang(uid)]["choose_quality"], reply_markup=keyboard)

# NOTE: the dl_video_quality callback above for search results includes yt_id; handle both forms
async def universal_video_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split("::")
    # two possible forms:
    # 1) dl_video_quality::480::<uid>
    # 2) dl_video_quality::480::<uid>::<yt_id>
    if len(parts) not in (3, 4):
        await query.edit_message_text("Invalid selection.")
        return
    _, quality, sel_user_id = parts[0], parts[1], parts[2]
    uid = query.from_user.id
    sel_user_id = int(sel_user_id)
    if uid != sel_user_id:
        await query.edit_message_text("This button is not for you.")
        return

    yt_id = parts[3] if len(parts) == 4 else None
    if yt_id:
        url = f"https://www.youtube.com/watch?v={yt_id}"
    else:
        url = context.user_data.get(f"url_for_download_{uid}")
    if not url:
        await query.edit_message_text("URL not found.")
        return

    task = asyncio.create_task(download_video_for_url(query, context, url, quality))
    context.application.bot_data.setdefault("active_downloads", {})[uid] = task

# ==========================
# DOWNLOAD IMPLEMENTATIONS
# ==========================
async def download_audio_for_url(query, context, url: str) -> None:
    chat_id = query.message.chat_id
    uid = query.from_user.id
    temp_dir = tempfile.mkdtemp()
    await query.edit_message_text("Downloading audio...")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": os.path.join(temp_dir, "%(title)s.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "quiet": True,
        "ffmpeg_location": FFMPEG_PATH if FFMPEG_IS_AVAILABLE else None,
        "cookiefile": COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        for file in os.listdir(temp_dir):
            path = os.path.join(temp_dir, file)
            if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text=LANGUAGES[get_user_lang(uid)]["too_big"])
                continue
            with open(path, "rb") as f:
                await context.bot.send_audio(chat_id=chat_id, audio=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text=LANGUAGES[get_user_lang(uid)]["done_audio"])
    except Exception as e:
        logger.exception("Audio download failed")
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

async def download_video_for_url(query, context, url: str, quality: str) -> None:
    chat_id = query.message.chat_id
    uid = query.from_user.id
    temp_dir = tempfile.mkdtemp()
    await query.edit_message_text(f"Downloading video ({quality})...")
    # ensure quality numeric
    try:
        q_int = int(str(quality))
    except Exception:
        q_int = 720
    ydl_opts = {
        "format": f"bestvideo[height<={q_int}]+bestaudio/best",
        "outtmpl": os.path.join(temp_dir, "%(title)s.%(ext)s"),
        "quiet": True,
        "ffmpeg_location": FFMPEG_PATH if FFMPEG_IS_AVAILABLE else None,
        "merge_output_format": "mp4",
    }
    try:
        await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        for file in os.listdir(temp_dir):
            path = os.path.join(temp_dir, file)
            if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text=LANGUAGES[get_user_lang(uid)]["too_big"])
                continue
            with open(path, "rb") as f:
                await context.bot.send_video(chat_id=chat_id, video=f, filename=file)
        await context.bot.send_message(chat_id=chat_id, text=LANGUAGES[get_user_lang(uid)]["done_video"])
    except Exception as e:
        logger.exception("Video download failed")
        await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================
# MAIN
# ==========================
def main() -> None:
    load_user_langs()
    app = Application.builder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("languages", choose_language))
    app.add_handler(CommandHandler("search", search_command))

    # Language selection from keyboard (matches exact language names)
    app.add_handler(MessageHandler(filters.Regex(f\"^({'|'.join(map(lambda s: s.replace(')','\\)').replace('(','\\('), LANG_CODES.keys()))})$\"), set_language))

    # Smart text handler (search or URL)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_message_handler))

    # Callbacks:
    app.add_handler(CallbackQueryHandler(select_download_type_callback, pattern=r"^dl_(audio|video)::"))
    app.add_handler(CallbackQueryHandler(select_video_quality_callback, pattern=r"^dl_video_quality::"))
    # search selection -> shows format choices
    app.add_handler(CallbackQueryHandler(select_search_result_callback, pattern=r"^dl_from_search::"))
    # format choosen after search
    app.add_handler(CallbackQueryHandler(select_search_format_callback, pattern=r"^dl_search_(audio|video)::"))
    # universal quality handler (handles both direct URL and search result qualities)
    app.add_handler(CallbackQueryHandler(universal_video_quality_callback, pattern=r"^dl_video_quality::"))

    # set bot commands
    async def set_commands(app_: Application) -> None:
        await app_.bot.set_my_commands([
            BotCommand("start", "Start and choose language"),
            BotCommand("languages", "Change language"),
            BotCommand("search", "Search music/video (YouTube)"),
        ])
    app.post_init = set_commands

    logger.info("Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()