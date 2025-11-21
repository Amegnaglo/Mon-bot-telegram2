import os
import logging 
import asyncio 
import tempfile 
import shutil 
import json 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters 
import yt_dlp

==========================

CONFIG

==========================

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") if not TOKEN: raise ValueError("Cant found TELEGRAM_BOT_TOKEN in environment variables.")

COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt") ffmpeg_path = os.getenv('FFMPEG_PATH', '/usr/bin/ffmpeg') FFMPEG_IS_AVAILABLE = os.path.exists(ffmpeg_path) and os.access(ffmpeg_path, os.X_OK) TELEGRAM_FILE_SIZE_LIMIT_BYTES = 500 * 1024 * 1024 USER_LANGS_FILE = "user_languages.json" SEARCH_RESULTS_LIMIT = 10

==========================

LOGGING

==========================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') logger = logging.getLogger(name)

==========================

LANGUES

==========================

LANG_CODES = {"English": "en", "Français": "fr"} LANG_KEYBOARD = ReplyKeyboardMarkup([["English", "Français"]], resize_keyboard=True, one_time_keyboard=True)

user_langs = {}

LANGUAGES = { "en": { "start": "Hello! I am a bot for downloading audio and video. Send a link or search using /search.", "choose_lang": "Choose language:", "search_prompt": "Enter a track or artist name:", "choose_track": "Select a track:", "downloading_selected_track": "Downloading selected track...", "downloading_audio": "Downloading audio...", "downloading_video": "Downloading video...", "done_audio": "Done! Audio sent.", "done_video": "Done! Video sent.", "error": "Something went wrong.", "too_big": f"File too big (> 500MB)", "choose_quality": "Choose video quality:", "copyright_command": "⚠️ All downloads may be copyrighted." }, "fr": { "start": "Bonjour ! Je suis un bot pour télécharger audio et vidéo. Envoyez un lien ou utilisez /search.", "choose_lang": "Choisissez la langue :", "search_prompt": "Entrez le titre ou artiste :", "choose_track": "Sélectionnez un titre :", "downloading_selected_track": "Téléchargement du titre sélectionné...", "downloading_audio": "Téléchargement audio...", "downloading_video": "Téléchargement vidéo...", "done_audio": "Fait ! Audio envoyé.", "done_video": "Fait ! Vidéo envoyée.", "error": "Une erreur est survenue.", "too_big": f"Fichier trop volumineux (> 500MB)", "choose_quality": "Choisissez la qualité vidéo :", "copyright_command": "⚠️ Tous les téléchargements peuvent être protégés par copyright." } }

==========================

HELPERS

==========================

def load_user_langs(): global user_langs if os.path.exists(USER_LANGS_FILE): with open(USER_LANGS_FILE, 'r', encoding='utf-8') as f: try: user_langs = {int(k): v for k, v in json.load(f).items()} except json.JSONDecodeError: user_langs = {}

def save_user_langs(): with open(USER_LANGS_FILE, 'w', encoding='utf-8') as f: json.dump(user_langs, f)

def get_user_lang(user_id): return user_langs.get(user_id, "en")

==========================

COMMANDS LANGUE

==========================

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(LANGUAGES[get_user_lang(update.effective_user.id)]["choose_lang"], reply_markup=LANG_KEYBOARD)

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = update.effective_user.id lang_name = update.message.text if lang_name in LANG_CODES: user_langs[user_id] = LANG_CODES[lang_name] save_user_langs() texts = LANGUAGES[LANG_CODES[lang_name]] await update.message.reply_text(texts["start"]) else: await update.message.reply_text("Please choose a language from the keyboard.")

==========================

SMART MESSAGE HANDLER

==========================

def is_url(text): text = text.lower().strip() return text.startswith("http://") or text.startswith("https://")

async def smart_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE): text = update.message.text.strip() user_id = update.effective_user.id

if is_url(text):
    await ask_download_type(update, context, text)
else:
    await handle_search_query(update, context)

==========================

DOWNLOAD TYPE & QUALITY

==========================

async def ask_download_type(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str): user_id = update.effective_user.id lang = get_user_lang(user_id)

context.user_data[f'url_for_download_{user_id}'] = url
keyboard = InlineKeyboardMarkup([
    [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data=f"dl_audio_{user_id}")],
    [InlineKeyboardButton("🎥 MP4 (Video)", callback_data=f"dl_video_{user_id}")]
])
await update.message.reply_text(LANGUAGES[lang]["choose_track"], reply_markup=keyboard)

async def select_download_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() user_id = query.from_user.id

url = context.user_data.pop(f'url_for_download_{user_id}', None)
if not url:
    await query.edit_message_text("URL not found.")
    return

if query.data.startswith("dl_audio"):
    task = asyncio.create_task(download_audio(query, context, url))
elif query.data.startswith("dl_video"):
    # Ask quality
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("1080p", callback_data=f"dl_video_1080_{user_id}")],
        [InlineKeyboardButton("720p", callback_data=f"dl_video_720_{user_id}")],
        [InlineKeyboardButton("480p", callback_data=f"dl_video_480_{user_id}")]
    ])
    await query.edit_message_text(LANGUAGES[get_user_lang(user_id)]["choose_quality"], reply_markup=keyboard)
    return

context.bot_data.setdefault('active_downloads', {})[user_id] = {'task': task}

async def select_video_quality_callback(update: Update, context: ContextTypes.DEFAULT_TYPE): query = update.callback_query await query.answer() user_id = query.from_user.id

url = context.user_data.get(f'url_for_download_{user_id}')
if not url:
    await query.edit_message_text("URL not found.")
    return

try:
    _, _, quality, sel_user_id = query.data.split("_")
    sel_user_id = int(sel_user_id)
except Exception:
    await query.edit_message_text("Invalid selection.")
    return

if user_id != sel_user_id:
    await query.edit_message_text("This button is not for you.")
    return

task = asyncio.create_task(download_video(query, context, url, quality))
context.bot_data.setdefault('active_downloads', {})[user_id] = {'task': task}

==========================

DOWNLOAD HANDLERS

==========================

def blocking_yt_dlp_download(ydl_opts, url): with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])

async def download_audio(query, context, url): chat_id = query.message.chat_id temp_dir = tempfile.mkdtemp() await query.edit_message_text("Downloading audio...") ydl_opts = { 'format': 'bestaudio/best', 'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'), 'postprocessors': [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}], 'quiet': True, 'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None, 'cookiefile': COOKIE_FILE } try: await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url) files = os.listdir(temp_dir) for file in files: path = os.path.join(temp_dir, file) if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES: await context.bot.send_message(chat_id=chat_id, text="File too big") continue with open(path, 'rb') as f: await context.bot.send_audio(chat_id=chat_id, audio=f, filename=file) await context.bot.send_message(chat_id=chat_id, text="Audio sent!") except Exception as e: await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}") finally: shutil.rmtree(temp_dir, ignore_errors=True)

async def download_video(query, context, url, quality): chat_id = query.message.chat_id temp_dir = tempfile.mkdtemp() await query.edit_message_text(f"Downloading video ({quality})...") ydl_opts = { 'format': f'bestvideo[height<={quality}]+bestaudio/best', 'outtmpl': os.path.join(temp_dir, '%(title)s.%(ext)s'), 'quiet': True, 'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None } try: await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url) files = os.listdir(temp_dir) for file in files: path = os.path.join(temp_dir, file) if os.path.getsize(path) > TELEGRAM_FILE_SIZE_LIMIT_BYTES: await context.bot.send_message(chat_id=chat_id, text="File too big") continue with open(path, 'rb') as f: await context.bot.send_video(chat_id=chat_id, video=f, filename=file) await context.bot.send_message(chat_id=chat_id, text="Video sent!") except Exception as e: await context.bot.send_message(chat_id=chat_id, text=f"Error: {e}") finally: shutil.rmtree(temp_dir, ignore_errors=True)

==========================

SEARCH

==========================

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE): user_id = update.effective_user.id lang = get_user_lang(user_id) texts = LANGUAGES[lang] await update.message.reply_text(texts["search_prompt"]) context.user_data[f'awaiting_search_query_{user_id}'] = True

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE): from yt_dlp import YoutubeDL user_id = update.effective_user.id query_text = update.message.text.strip() lang = get_user_lang(user_id)

ydl_opts = {'quiet': True, 'skip_download': True, 'extract_flat': True, 'noplaylist': True}
search_query = f"ytsearch{SEARCH_RESULTS_LIMIT}:{query_text}"
with YoutubeDL(ydl_opts) as ydl:
    info = ydl.extract_info(search_query, download=False)
entries = info.get('entries', [])
if not entries:
    await update.message.reply_text(LANGUAGES[lang]["error"])
    return

keyboard = [[InlineKeyboardButton(f"{idx+1}. {e.get('title')}", callback_data=f"dl_audio_{user_id}_{e.get('id')}")] for idx, e in enumerate(entries)]
await update.message.reply_text(LANGUAGES[lang]["choose_track"], reply_markup=InlineKeyboardMarkup(keyboard))

==========================

MAIN

==========================

def main(): load_user_langs() app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", choose_language))
app.add_handler(CommandHandler("languages", choose_language))
app.add_handler(CommandHandler("search", search_command))
app.add_handler(MessageHandler(filters.Regex(f"^({'|'.join(LANG_CODES.keys())})$"), set_language))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, smart_message_handler))

app.add_handler(CallbackQueryHandler(select_download_type_callback, pattern="^dl_") )
app.add_handler(CallbackQueryHandler(select_video_quality_callback, pattern="^dl_video_"))

async def set_commands(_):
    await app.bot.set_my_commands([
        BotCommand("start", "Start and choose language"),
        BotCommand("languages", "Change language"),
        BotCommand("search", "Search music/video (YouTube/SoundCloud)"),
        BotCommand("copyright", "Copyright info")
    ])
app.post_init = set_commands

app.run_polling()

if name == "main": main()