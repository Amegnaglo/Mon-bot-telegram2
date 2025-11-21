import os # Import necessary libraries
import logging # Import logging for debugging and information
import asyncio # Import asyncio for asynchronous operations
import tempfile # Import tempfile for temporary file handling
import shutil # Import shutil for file operations
import json # Import json for handling JSON data
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand # Import necessary Telegram bot components 
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler # Import necessary Telegram bot handlers
import yt_dlp # Import yt-dlp for downloading media


# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("Cant found TELEGRAM_BOT_TOKEN in environment variables.")

# Paths and variables
COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt")
ffmpeg_path_from_env = os.getenv('FFMPEG_PATH')
ffmpeg_path = ffmpeg_path_from_env if ffmpeg_path_from_env else '/usr/bin/ffmpeg'   # Default path for ffmpeg
FFMPEG_IS_AVAILABLE = os.path.exists(ffmpeg_path) and os.access(ffmpeg_path, os.X_OK)   # Check if ffmpeg is available
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@ytdlpdeveloper")    # Channel to which users must be subscribed
TELEGRAM_FILE_SIZE_LIMIT_BYTES = 50 * 1024 * 1024 # 50 MB in bytes
TELEGRAM_FILE_SIZE_LIMIT_TEXT = "50 МБ" # Text representation of the file size limit 
# File to store user language preferences
USER_LANGS_FILE = "user_languages.json" # File to store user language preferences
# Keyboard for language selection # This keyboard will be shown to users when they start the bot or change language 
LANG_KEYBOARD = ReplyKeyboardMarkup( # Keyboard for selecting language
    [
        ["Русский", "English"], # Russian and English
        ["Español", "Azərbaycan dili"], # Spanish and Azerbaijani
        ["Türkçe", "Українська"], # Turkish and Ukrainian
        ["العربية"] # Arabic
    ], 
    resize_keyboard=True, # Resize keyboard buttons
    one_time_keyboard=True # Hide keyboard after selection
)

SEARCH_RESULTS_LIMIT = 10 # Search results limit
user_langs = {} # Dictionary for storing user language preferences

# Dictionaries with localized texts
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


def get_user_lang(user_id):
    """
    Determines the user's language by their ID. If no language is found, Russian is used.
    """
    lang = user_langs.get(user_id)
    if lang in LANGUAGES:
        return lang
    return "en"

def is_soundcloud_url(url):
    """
    Checks if the URL is a SoundCloud link.
    """
    return "soundcloud.com/" in url.lower()

def load_user_langs():
    """
    Loads user language preferences from a file.
    """
    global user_langs
    if os.path.exists(USER_LANGS_FILE):
        with open(USER_LANGS_FILE, 'r', encoding='utf-8') as f:
            try:
                loaded_langs = json.load(f)
                user_langs = {int(k): v for k, v in loaded_langs.items()}
            except json.JSONDecodeError:
                user_langs = {}
    else:
        user_langs = {}

def save_user_langs():
    """
    Saves user language preferences to a file.
    """
    with open(USER_LANGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_langs, f)

async def choose_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sends the user a keyboard to choose a language.
    """
    logger.info(f"User {update.effective_user.id} requested language choice.")
    await update.message.reply_text(
        LANGUAGES["en"]["choose_lang"], # Use Russian text by default for language selection.
        reply_markup=LANG_KEYBOARD
    )

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sets the language for the user and sends a welcome message.
    """
    lang_name = update.message.text
    lang_code = LANG_CODES.get(lang_name)
    user_id = update.effective_user.id
    if lang_code:
        user_langs[user_id] = lang_code
        save_user_langs()
        logger.info(f"User {user_id} set language to {lang_code}.")
        await update.message.reply_text(LANGUAGES[lang_code]["start"])
    else:
        logger.warning(f"User {user_id} sent invalid language: {lang_name}.")
        await update.message.reply_text(
            "Please choose a language from the keyboard."
        )

async def check_subscription(user_id: int, bot) -> bool:
    """
    Checks if the user is subscribed to the required channel.
    """
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id}: {e}")
        return False

def blocking_yt_dlp_download(ydl_opts, url_to_download):
    """
    Performs download using yt-dlp in blocking mode.
    """
    import yt_dlp.utils
    import logging
    yt_dlp_logger = logging.getLogger("yt_dlp")
    yt_dlp_logger.setLevel(logging.WARNING) # Set logging level for yt-dlp
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url_to_download])
        return True
    except yt_dlp.utils.UnsupportedError:
        raise Exception("Unsupported URL: {}".format(url_to_download))
    except Exception as e:
        logger.error(f"yt-dlp download error: {e}")
        raise # Re-raise all other exceptions

async def ask_download_type(update: Update, context: ContextTypes.DEFAULT_TYPE, url: str):
    """
    Sends a copyright warning and asks the user about the download type (MP3 for YouTube/SoundCloud).
    """
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    # Send copyright warning before format selection
    await update.message.reply_text(texts.get("copyright_pre"))
    context.user_data[f'url_for_download_{user_id}'] = url
    if is_soundcloud_url(url):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts["audio_button_sc"], callback_data=f"dltype_audio_sc_{user_id}")]
        ])
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts["audio_button_mp3"], callback_data=f"dltype_audio_mp3_{user_id}")]
        ])
    await update.message.reply_text(texts["choose_download_type"], reply_markup=keyboard)

async def handle_download(update_or_query, context: ContextTypes.DEFAULT_TYPE, url: str, texts: dict, user_id: int, download_type: str):
    """
    Handles the download of an audio file from YouTube or SoundCloud.
    """
    if not update_or_query.message:
        try:
            # Send error message if chat_id is not found.
            await context.bot.send_message(chat_id=user_id, text=texts["error"] + " (internal error: chat not found)")
        except Exception:
            pass # Ignore error if message cannot be sent.
        return

    chat_id = update_or_query.message.chat_id
    temp_dir = None
    status_message = None
    active_downloads = context.bot_data.setdefault('active_downloads', {})
    loop = asyncio.get_running_loop()
    cancel_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(texts["cancel_button"], callback_data=f"cancel_{user_id}")]])

    async def update_status_message_async(text_to_update, show_cancel_button=True):
        """
        Updates the status message in the chat.
        """
        nonlocal status_message
        if status_message:
            try:
                current_keyboard = cancel_keyboard if show_cancel_button else None
                await status_message.edit_text(text_to_update, reply_markup=current_keyboard)
            except Exception as e:
                logger.debug(f"Could not edit status message: {e}") # Debug message
                pass # Ignore errors when editing the message.

    def progress_hook(d):
        """
        Progress hook for yt-dlp.
        """
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', 'N/A').strip()
            speed_str = d.get('_speed_str', 'N/A').strip()
            eta_str = d.get('_eta_str', 'N/A').strip()
            progress_text = texts["download_progress"].format(percent=percent_str, speed=speed_str, eta=eta_str)
            asyncio.run_coroutine_threadsafe(update_status_message_async(progress_text), loop)

    try:
        status_message = await context.bot.send_message(chat_id=chat_id, text=texts["downloading_audio"], reply_markup=cancel_keyboard)
        temp_dir = tempfile.mkdtemp()
        ydl_opts = {
            'outtmpl': os.path.join(temp_dir, '%(title).140B - Made by @ytdlpload_bot Developed by BitSamurai [%(id)s].%(ext)s'),
            'format': 'bestaudio/best',
            'cookiefile': COOKIE_FILE if os.path.exists(COOKIE_FILE) else None,
            'progress_hooks': [progress_hook],
            'nocheckcertificate': True,
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_path if FFMPEG_IS_AVAILABLE else None,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192K',
            }],
            'postprocessor_args': {
                'FFmpegExtractAudio': ['-metadata', 'comment=Made by @ytdlpload_bot']
            },
            'verbose': True # Enable verbose output to see what errors occur.
        }
        # Remove None values from ydl_opts to avoid errors.
        ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

        logger.info(f"Starting download for {url} by user {user_id}")
        try:
            await asyncio.to_thread(blocking_yt_dlp_download, ydl_opts, url)
        except Exception as e:
            if 'Unsupported URL' in str(e) or 'unsupported url' in str(e).lower():
                await update_status_message_async("The link is not supported. Please check the link or try another query.", show_cancel_button=False)
                return
            logger.error(f"Error during yt-dlp download for {url}: {e}")
            raise # Re-raise exception after logging.

        downloaded_files_info = []
        all_temp_files = os.listdir(temp_dir)
        for file_name in all_temp_files:
            file_path = os.path.join(temp_dir, file_name)
            file_ext_lower = os.path.splitext(file_name)[1].lower()
            base_title = os.path.splitext(file_name.split(" [")[0])[0] # Extract title from file name.
            if file_ext_lower in [".mp3", ".m4a", ".webm", ".ogg", ".opus", ".aac"]:
                downloaded_files_info.append((file_path, base_title))

        if not downloaded_files_info:
            await update_status_message_async(texts["error"] + " (file not found)", show_cancel_button=False)
            return

        total_files = len(downloaded_files_info)
        for i, (file_to_send, title_str) in enumerate(downloaded_files_info):
            await update_status_message_async(texts["sending_file"].format(index=i+1, total=total_files))
            file_size = os.path.getsize(file_to_send)

            if file_size > TELEGRAM_FILE_SIZE_LIMIT_BYTES:
                await context.bot.send_message(chat_id=chat_id, text=f"{texts['too_big']} ({os.path.basename(file_to_send)})")
                continue

            try:
                with open(file_to_send, 'rb') as f_send:
                    await context.bot.send_audio(
                        chat_id=chat_id, audio=f_send, title=title_str,
                        filename=os.path.basename(file_to_send)
                    )
                # Send copyright message after sending each file
                await context.bot.send_message(chat_id=chat_id, text=texts.get("copyright_post"))
                logger.info(f"Successfully sent audio for {url} to user {user_id}")
            except Exception as e:
                logger.error(f"Error sending audio file {os.path.basename(file_to_send)} to user {user_id}: {e}")
                await context.bot.send_message(chat_id=chat_id, text=f"{texts['error']} (Error sending file {os.path.basename(file_to_send)})")

        await update_status_message_async(texts["done_audio"], show_cancel_button=False)

    except asyncio.CancelledError:
        # Handle download cancellation.
        logger.info(f"Download cancelled for user {user_id}.")
        if status_message:
            await update_status_message_async(texts["cancelled"], show_cancel_button=False)
        else:
            await context.bot.send_message(chat_id=chat_id, text=texts["cancelled"])
    except Exception as e:
        # General error handling for download.
        if 'Unsupported URL' in str(e) or 'unsupported url' in str(e).lower():
            if status_message:
                await update_status_message_async("The link is not supported. Please check the link or try another query.", show_cancel_button=False)
            else:
                await context.bot.send_message(chat_id=chat_id, text="The link is not supported. Please check the link or try another query.")
            return
        logger.critical(f"Unhandled error in handle_download for user {user_id}: {e}", exc_info=True) # Use critical for unhandled errors
        if status_message:
            await update_status_message_async(texts["error"] + str(e), show_cancel_button=False)
        else:
            await context.bot.send_message(chat_id=chat_id, text=texts["error"] + str(e))
    finally:
        # Clean up temporary files and remove active download status.
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"Cleaned up temporary directory {temp_dir} for user {user_id}.")
        if user_id in active_downloads:
            del active_downloads[user_id]
            logger.info(f"Removed active download for user {user_id}.")

async def select_download_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the selection of download type from the Inline keyboard.
    """
    query = update.callback_query
    await query.answer() # Answer CallbackQuery to remove the 'clock' from the button.
    user_id = query.from_user.id
    logger.info(f"User {user_id} selected download type: {query.data}")
    try:
        parts = query.data.split("_")
        if len(parts) != 4 or parts[0] != "dltype" or (parts[1] != "audio"):
            raise ValueError("Incorrect callback_data format for audio")
        specific_format = parts[2]
        user_id_from_callback = int(parts[3])

        if specific_format == "mp3":
            download_type_for_handler = "audio_mp3"
        elif specific_format == "sc":
            download_type_for_handler = "audio_sc"
        else:
            raise ValueError("Unknown download type")

    except (IndexError, ValueError) as e:
        logger.error(f"Error parsing callback_data for user {user_id}: {e} - Data: {query.data}")
        await query.edit_message_text("Selection error. Please try sending the link again.")
        return

    requesting_user_id = query.from_user.id
    if user_id_from_callback != requesting_user_id:
        logger.warning(f"User {requesting_user_id} tried to use another user's callback: {user_id_from_callback}")
        await query.edit_message_text("This button is not for you.")
        return

    lang = get_user_lang(requesting_user_id)
    texts = LANGUAGES[lang]

    # Extract URL for download from user_data.
    url_to_download = context.user_data.pop(f'url_for_download_{requesting_user_id}', None)
    if not url_to_download:
        logger.error(f"URL not found in user_data for user {requesting_user_id}")
        await query.edit_message_text(texts["error"] + " (URL not found, try again)")
        return

    try:
        await query.edit_message_reply_markup(reply_markup=None) # Remove keyboard after selection.
    except Exception as e:
        logger.debug(f"Could not remove reply markup: {e}")
        pass # Ignore errors if keyboard is already removed.

    # Start download in background.
    task = asyncio.create_task(handle_download(query, context, url_to_download, texts, requesting_user_id, download_type_for_handler))
    active_downloads = context.bot_data.setdefault('active_downloads', {})
    active_downloads[requesting_user_id] = {'task': task}

async def search_youtube(query: str):
    """
    Performs a search for videos on YouTube.
    """
    if is_url(query):
        return 'unsupported_url'

    ydl_opts = {
        'quiet': True, # Disable output messages.
        'skip_download': True, # Skip download.
        'extract_flat': True, # Extract only flat info list.
        'nocheckcertificate': True, # Do not check SSL certificates.
        'default_search': None, # Disable default search to control it.
        'noplaylist': True # Do not extract playlists.
    }
    try:
        # Search for top 10 results.
        search_query = f"ytsearch{SEARCH_RESULTS_LIMIT}:{query}"
        logger.info(f"Searching YouTube for query: {query}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            entries = info.get('entries', [])
            if entries is None:
                logger.info(f"No entries found for YouTube search: {query}")
                return [] # Return empty list if entries is None.
            return entries[:SEARCH_RESULTS_LIMIT]
    except yt_dlp.utils.DownloadError as e:
        if 'Unsupported URL' in str(e) or 'unsupported url' in str(e).lower():
            logger.warning(f"Unsupported URL in search query: {query}")
            return 'unsupported_url'
        logger.error(f"DownloadError during YouTube search for {query}: {e}")
        return []
    except Exception as e:
        logger.critical(f"Unhandled error during YouTube search for {query}: {e}", exc_info=True)
        return []

def is_url(text):
    """
    Checks if a string is a YouTube or SoundCloud URL.
    """
    text = text.lower().strip()
    return (
        text.startswith("http://") or text.startswith("https://")
    ) and (
        "youtube.com/" in text or "youtu.be/" in text or "soundcloud.com/" in text
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Starts the music search process.
    """
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    logger.info(f"User {user_id} issued /search command.")
    await update.message.reply_text(texts["search_prompt"])
    context.user_data[f'awaiting_search_query_{user_id}'] = True

async def handle_search_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Processes the user's search query and displays the results.
    """
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    query_text = update.message.text.strip()
    logger.info(f"User {user_id} sent search query: '{query_text}'")

    await update.message.reply_text(texts["searching"])
    results = await search_youtube(query_text)

    if results == 'unsupported_url':
        await update.message.reply_text(texts["unsupported_url_in_search"])
        context.user_data.pop(f'awaiting_search_query_{user_id}', None) # Reset awaiting query flag.
        return

    if not isinstance(results, list): # Check that results is a list.
        results = []

    if not results:
        await update.message.reply_text(texts["no_results"])
        context.user_data.pop(f'awaiting_search_query_{user_id}', None)
        return

    keyboard = []
    for idx, entry in enumerate(results):
        title = entry.get('title', texts["no_results"])
        video_id = entry.get('id')
        keyboard.append([InlineKeyboardButton(f"{idx+1}. {title}", callback_data=f"searchsel_{user_id}_{video_id}")])

    await update.message.reply_text(
        texts["choose_track"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    # Save search results for later selection.
    context.user_data[f'search_results_{user_id}'] = {entry.get('id'): entry for entry in results}
    context.user_data.pop(f'awaiting_search_query_{user_id}', None) # Reset awaiting query flag.
    logger.info(f"User {user_id} received {len(results)} search results.")

async def search_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the selection of a track from search results.
    """
    query = update.callback_query
    await query.answer() # Answer CallbackQuery to remove the 'clock' from the button.
    user_id = query.from_user.id
    logger.info(f"User {user_id} selected track from search: {query.data}")

    try:
        _, sel_user_id, video_id = query.data.split("_", 2)
        sel_user_id = int(sel_user_id)
    except Exception as e:
        logger.error(f"Error parsing search select callback data for user {user_id}: {e} - Data: {query.data}")
        await query.edit_message_text("Track selection error.")
        return

    if user_id != sel_user_id:
        logger.warning(f"User {user_id} tried to use another user's search select callback: {sel_user_id}")
        await query.edit_message_text("This button is not for you.")
        return

    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]

    url = f"https://youtu.be/{video_id}" # Form URL from video ID.
    await query.edit_message_text(texts["downloading_selected_track"], reply_markup=None) # Remove keyboard.

    # Start download of selected track.
    task = asyncio.create_task(
        handle_download(query, context, url, texts, user_id, "audio_mp3")
    )
    active_downloads = context.bot_data.setdefault('active_downloads', {})
    active_downloads[user_id] = {'task': task}

async def smart_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Smart message handler: determines if the message is a URL or a search query.
    """
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    text = update.message.text.strip()
    logger.info(f"User {user_id} sent message: '{text}'")

    active_downloads = context.bot_data.setdefault('active_downloads', {})
    if user_id in active_downloads and active_downloads[user_id].get('task') and not active_downloads[user_id]['task'].done():
        await update.message.reply_text(texts["download_in_progress"])
        return

    # Check subscription before any message processing.
    is_subscribed = await check_subscription(user_id, context.bot)
    if not is_subscribed:
        await update.message.reply_text(texts["not_subscribed"])
        return

    if is_url(text):
        await ask_download_type(update, context, text)
    else:
        # If not a URL and the bot is awaiting a search query (e.g., after /search).
        # Check if the bot is awaiting a search query from this user.
        if context.user_data.get(f'awaiting_search_query_{user_id}'):
            await handle_search_query(update, context)
        else:
            # If the user just wrote a word (e.g., Timeless), automatically perform a music search.
            if len(text.split()) <= 5 and text.isascii():
                # Auto-search for short texts (up to 5 words, ASCII)
                logger.info(f"User {user_id} auto-search for: '{text}'")
                await update.message.reply_text(texts["searching"])
                results = await search_youtube(text)
                if not results or results == 'unsupported_url':
                    await update.message.reply_text(texts["no_results"])
                    return
                keyboard = []
                for idx, entry in enumerate(results):
                    title = entry.get('title', texts["no_results"])
                    video_id = entry.get('id')
                    keyboard.append([InlineKeyboardButton(f"{idx+1}. {title}", callback_data=f"searchsel_{user_id}_{video_id}")])
                await update.message.reply_text(
                    texts["choose_track"],
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                context.user_data[f'search_results_{user_id}'] = {entry.get('id'): entry for entry in results}
            else:
                await update.message.reply_text(texts["url_error_generic"])

async def cancel_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the request to cancel a download.
    """
    query = update.callback_query
    await query.answer() # Answer CallbackQuery to remove the 'clock' from the button.
    user_id = query.from_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    logger.info(f"User {user_id} requested download cancellation.")

    active_downloads = context.bot_data.setdefault('active_downloads', {})
    download = active_downloads.get(user_id)

    if not download or not download.get('task') or download['task'].done():
        try:
            await query.edit_message_text(texts["already_cancelled_or_done"])
        except Exception as e:
            logger.debug(f"Could not edit message for already cancelled/done download: {e}")
            pass # Ignore error if message cannot be edited (e.g., already changed).
        return

    download['task'].cancel() # Cancel active download task.
    try:
        await query.edit_message_text(texts["cancelling"])
    except Exception as e:
        logger.debug(f"Could not edit message to 'cancelling': {e}")
        pass # Ignore error if message cannot be edited.
    logger.info(f"Download task cancelled for user {user_id}.")


async def copyright_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /copyright command and sends the copyright message.
    """
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    logger.info(f"User {user_id} issued /copyright command.")
    await update.message.reply_text(texts["copyright_command"])

def main():
    """
    Main function to run the bot.
    """
    load_user_langs() # Load user languages at startup.
    
    try:
        app = Application.builder().token(TOKEN).build()
        logger.info("Bot application built successfully.")
    except Exception as e:
        logger.critical(f"Failed to build bot application: {e}", exc_info=True)
        # If an error occurs here, it is critical and execution should stop.
        raise

    # Add command handlers.
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("language", choose_language))
    app.add_handler(CommandHandler("languages", choose_language))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("copyright", copyright_command)) # New /copyright command.

    # Message handler for language selection (by button text).
    app.add_handler(MessageHandler(filters.Regex(f"^({'|'.join(LANG_CODES.keys())})$"), set_language))

    # CallbackQuery handlers for download type selection and search selection.
    app.add_handler(CallbackQueryHandler(select_download_type_callback, pattern="^dltype_"))
    app.add_handler(CallbackQueryHandler(search_select_callback, pattern="^searchsel_"))
    app.add_handler(CallbackQueryHandler(cancel_download_callback, pattern="^cancel_"))

    # Main text message handler (if not a command and not language selection).
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.Regex(f"^({'|'.join(LANG_CODES.keys())})$"),
        smart_message_handler
    ))

    async def set_commands(_):
        """
        Sets the bot commands in Telegram. These commands are displayed in the Telegram menu.
        """
        logger.info("Setting bot commands.")
        await app.bot.set_my_commands([
            BotCommand("start", "Start and choose language"),
            BotCommand("languages", "Change language"),
            BotCommand("search", "Search music/video (YouTube/SoundCloud)"),
            BotCommand("copyright", "use this bot as your own risk") # More clear description
        ])
    app.post_init = set_commands # Run set_commands after application initialization.
    
    logger.info("Starting bot polling.")
    try:
        app.run_polling() # Start the bot.
    except Exception as e:
        logger.critical(f"Bot polling failed: {e}", exc_info=True)
        

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the /start command: prompts to choose a language and sends copyright warning.
    """
    logger.info(f"User {update.effective_user.id} issued /start command.")
    await choose_language(update, context)
    user_id = update.effective_user.id
    lang = get_user_lang(user_id)
    texts = LANGUAGES[lang]
    await update.message.reply_text(texts["copyright_post"])

if __name__ == '__main__':
    main()
