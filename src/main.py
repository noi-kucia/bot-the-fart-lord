"""Main file."""

import asyncio
import contextvars
import datetime
import gettext
import logging
import random
import sqlite3
import subprocess
from functools import wraps
from os import environ
from pathlib import Path
from typing import Literal

import telegram
from dotenv import load_dotenv
from telegram import CallbackQuery, ForceReply, Update
from telegram.constants import ChatType, ReactionEmoji
from telegram.ext import (
    AIORateLimiter,
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

load_dotenv(Path(__file__).parent / "env/.env")

DEBUG = environ.get("DEBUG", "false").lower() == "true"

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s[%(levelname)s]: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Localization
locales_dir = Path(__file__).parent.parent / "locales"


def make_logged_gettext(translator, lang_code):
    """Log missing translations."""

    def wrapped(msg):
        translated = translator(msg)
        if translated == msg and lang_code != "en":  # Message is not translated
            logger.warning("Missing translation: lang=%s msgid=%r", lang_code, msg)
        return translated

    return wrapped


def make_logged_ngettext(translator, lang_code):
    """Log missing plural translations."""

    def wrapped(singular, plural, n):
        translated = translator(singular, plural, n)
        if translated in (singular, plural) and lang_code != "en":  # Message is not translated
            logger.warning("Missing translation: lang=%s msgid=%r msgid_plural=%r", lang_code, singular, plural)
        return translated

    return wrapped


def needs_compile(po, mo):
    """Check if po needs to be (re)compiled."""
    return not mo.exists() or Path(po).stat().st_mtime > Path(mo).stat().st_mtime


def compile_translations():
    """Compile .mo localization files if some are missing or .po file was updated."""
    for po in locales_dir.rglob("*.po"):
        mo = po.with_suffix(".mo")
        locale = po.parent.parent.name
        if needs_compile(po, mo):
            logger.info("Localization: locale %s is obsolete or absent, compiling from %s", locale, po)
            subprocess.run(["msgfmt", str(po), "-o", str(mo)], check=True)


# Extract all supported languages from the locales directory
SUPPORTED_LANGUAGES = [lang.name for lang in locales_dir.glob("*") if lang.is_dir()]

compile_translations()  # Compile translations on startup if needed
languages = {
    lang: gettext.translation("messages", localedir=locales_dir, languages=[lang]) for lang in SUPPORTED_LANGUAGES
}

translation_defaults = {
    "gettext": lambda x: x,
    "ngettext": lambda s, p, n: s if n == 1 else p,
}
translator_var = contextvars.ContextVar(
    "translator",
    default=translation_defaults,
)


def _(msg):
    """Localize a message."""
    return translator_var.get()["gettext"](msg)


def n_(singular, plural, n):
    """
    Localize a message with pluralization.

    Example:
        ```
        n_("{apples_num} apple", "{apples_num}apples", apples_num).format(apples_num=apples_num)
        ```
    """
    return translator_var.get()["ngettext"](singular, plural, n)


def localized(function):
    """
    Set the translator for the current chat based on the language stored in the database.

    Expects a telegram Update instance to be passed as the first argument. It is used to retrieve chat settings.
    Inside the decorated function, you can use _() and n_() functions for translations.
    n_() if you want to use pluralization e.g. formatting a string like "You have %(apples_num)d apples".
    """

    @wraps(function)
    async def inner(update: Update, *args, **kwargs):
        chat_id = update.effective_chat.id
        settings = await get_chat_settings(chat_id)

        lang_code = settings.get("language", None)
        if lang_code is None:
            logger.warning("No language is set for chat %s. Continuing with default (en).", chat_id)
            lang_code = "en"
        translation = languages[lang_code]

        translator = {
            "gettext": make_logged_gettext(translation.gettext, lang_code),
            "ngettext": make_logged_ngettext(translation.ngettext, lang_code),
        }

        token = translator_var.set(translator)
        try:
            return await function(update, *args, **kwargs)
        finally:
            translator_var.reset(token)

    return inner


# Database
conn = sqlite3.connect(Path(__file__).parent.parent / "database.db")
db = conn.cursor()
db.execute(
    """
    CREATE TABLE IF NOT EXISTS farts
    (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id    INTEGER,
        user_id       INTEGER,
        send_datetime TEXT,
        chat_id       INTEGER,
        voice_file_id TEXT
    )
    """
)

db.execute(
    """
    CREATE TABLE IF NOT EXISTS chats
    (
        chat_id          INTEGER PRIMARY KEY,
        chat_type        TEXT,
        setting_timezone TEXT DEFAULT 'UTC',
        setting_language TEXT DEFAULT 'en'
    )
    """
)

# Bot start time to measure uptime
BOT_START_TIME: datetime.datetime = datetime.datetime.now(tz=datetime.UTC)


# ============================= Database functions =============================
#   These are temporal until switching to something more powerful than SQLite
#          which is used to speed development process on early stages
# ================================== Start =====================================


def save_fart(message_id: int, user_id: int, chat_id: int, send_datetime: str, voice_file_id: str) -> None:
    """Save fart to the database."""
    db.execute(
        "INSERT INTO farts VALUES (?, ?, ?, ?, ?, ?)",
        (None, message_id, user_id, send_datetime, chat_id, voice_file_id),
    )
    conn.commit()
    logger.info("fart %s is saved to the database", message_id)


async def save_chat(chat_id: int, chat_type: ChatType | None = None) -> None:
    """
    Save chat to the database.

    Args:
        chat_id (int): ID of the chat to save.
        chat_type: Type of the chat . If not provided, bot will get it from the API.
    """
    # Get chat type if not provided
    if chat_type is None:
        bot = telegram.Bot(environ.get("BOT_TOKEN", None))
        chat_type = (await bot.get_chat(chat_id)).type

    # Save chat to the database
    db.execute("INSERT OR IGNORE INTO chats (chat_id, chat_type) VALUES (?, ?)", (chat_id, chat_type))
    conn.commit()
    logger.info("chat %s is saved to the database", chat_id)


async def get_chat_settings(chat_id: int) -> dict:
    """Get chat settings from the database."""
    chat = db.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()

    # Create with defaults if chat is not in the database
    if chat is None:
        await save_chat(chat_id)
        chat = db.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()

    return {"timezone": chat[2], "language": chat[3]}


async def update_chat_settings(
    chat_id: int, timezone: str | None = None, language: Literal["en", "pl", "ru"] | None = None
) -> dict:
    """
    Update chat settings in the database.

    Values set to None will not be affected.

    Args:
        chat_id: Id of the chat to apply the settings to.
        timezone: Timezone to set from pytz.common_timezones list e.g. 'UTC', 'GMT', 'Europe/Paris'.
        language: Language code to set. Must be one of SUPPORTED_LANGUAGES.

    Returns:
            Updated settings as dict same as get_chat_settings returns.
    """
    # Build a single UPDATE query with only non-None values
    updates = []
    params = []

    if timezone is not None:
        updates.append("setting_timezone = ?")
        params.append(timezone)

    if language is not None:
        updates.append("setting_language = ?")
        params.append(language)

    # Execute single query if there are any updates to apply
    if updates:
        params.append(chat_id)
        query = "UPDATE chats SET " + ", ".join(updates) + " WHERE chat_id = ?"
        db.execute(query, params)
        conn.commit()

    logger.info(
        "chat %s settings are updated to timezone: %s, language: %s",
        chat_id,
        timezone,
        language,
    )

    # Return updated settings
    return await get_chat_settings(chat_id)


# ============================= Database functions =============================
# =================================== END ======================================


async def send_debug_notification(message: str) -> None:
    """Send a debug notification to all chats and groups listed in NOTIFICATION_CHAT_IDS environmental var
    if in production or use logger instead.
    """
    # If not in production, use logger instead
    if DEBUG:
        logger.info(message)
        return

    # Get chat IDs from environmental variable
    ids = environ.get("NOTIFICATION_CHAT_IDS", "")

    # Return if no chats were specified
    if not ids:
        logger.warning("No notification chat IDs provided. Skipping debug notification.")
        return

    # Send message to all chats and groups listed in NOTIFICATION_CHAT_IDS environmental var
    bot = telegram.Bot(environ.get("BOT_TOKEN", None))
    for chat_id_str in ids.split(":"):
        # Validate chat ID and convert to int
        if chat_id_str:
            try:
                chat_id = int(chat_id_str)
                await bot.send_message(chat_id=chat_id, text=message)
            except ValueError:
                logger.warning("Invalid chat ID '%s' in NOTIFICATION_CHAT_IDS. Skipping.", chat_id_str)
                continue
            except Exception as e:
                logger.warning("Failed to send message to chat %s: %s", chat_id, e)
                continue


# Define a few command handlers. These usually take the two arguments update and
# context.
async def start(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        f"yo, {user.mention_html()}!\nShow me your farts if not afraid to shit your pants",
        reply_markup=ForceReply(selective=True),
    )


@localized
async def help_command(update: Update, __: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text(_("Help yourself, nigga!"))


async def uptime_command(update: Update, _: CallbackContext) -> None:
    """Send the current bot uptime."""
    uptime = datetime.datetime.now(tz=datetime.UTC) - BOT_START_TIME
    total_secs = int(uptime.total_seconds())
    days = total_secs // 86400
    hours = (total_secs % 86400) // 3600
    minutes = (total_secs % 3600) // 60
    seconds = total_secs % 60
    response = "Uptime:"
    if days:
        response += f" {days} days" if days > 1 else f" {days} day"
    response += f" {hours} h {minutes} min {seconds} sec"
    await update.message.reply_text(_(response))


async def fart_callback(update: Update, context: CallbackContext) -> None:
    """
    Process a voice message containing fart.

    Bot randomly replies on the message and saves the fart to its database.
    """
    logger.info("Received a fart voice message")

    await reply_to_fart_voice(update, context)  # Reply to fart

    # Save the fart to the database
    kwargs = {
        "message_id": update.message.message_id,
        "user_id": update.message.from_user.id,
        "chat_id": update.message.chat_id,
        "send_datetime": update.message.date.isoformat(),
        "voice_file_id": update.message.voice.file_id,
    }
    save_fart(**kwargs)


async def reply_to_fart_voice(update: Update, _: CallbackContext) -> None:
    """Reply to the fart voice message with a random phrase with 20% chance and set a poop reaction."""
    # Set the poop reaction on the message
    await update.message.set_reaction(ReactionEmoji.PILE_OF_POO)

    # 80% chance to ignore
    if random.random() > 0.2:
        return

    # Reply with a random phrase from the list
    path = Path(__file__).parent.parent / "resources" / "fart_reactions.txt"
    phrase = random.choice(path.read_text().splitlines())
    await update.message.reply_text(phrase, reply_to_message_id=update.message.message_id)


async def stats_command(update: Update, _: CallbackContext) -> None:
    """Send a message with statistics on registered farts in chat."""
    # Fetch chat farts data from the database
    chat_id = update.message.chat_id
    chat_farts = db.execute("SELECT user_id, send_datetime FROM farts WHERE chat_id = ?", (chat_id,)).fetchall()

    # Format and send statistics based on chat type
    match update.message.chat.type:
        case ChatType.PRIVATE:
            await _send_private_stats(update, _, chat_farts)
        case ChatType.GROUP:
            await _send_group_stats(update, _, chat_farts)
        case _:
            logger.debug("Unknown chat type: %s", update.message.chat.type)


@localized
async def _send_private_stats(update: Update, __: CallbackContext, chat_farts: list) -> None:
    """Send message with private farts."""
    user_id = update.message.from_user.id
    all_farts = db.execute("SELECT user_id, send_datetime FROM farts WHERE user_id = ?", (user_id,)).fetchall()
    num_of_chat_farts = len(chat_farts)
    num_of_total_farts = len(all_farts)
    await update.message.reply_text(
        n_(
            "Bro, you farted only {num_of_chat_farts} time here",
            "Bro, you farted {num_of_chat_farts} times just here",
            num_of_chat_farts,
        ).format(num_of_chat_farts=num_of_chat_farts)
        + n_(
            " and only {num_of_total_farts} fart in general!\n",
            " and {num_of_total_farts} farts in general!\n",
            num_of_total_farts,
        ).format(num_of_total_farts=num_of_total_farts)
    )


@localized
async def _send_group_stats(update: Update, __: CallbackContext, farts: list) -> None:
    """Send message with group farts statistics."""
    await update.message.reply_text(_(f"Nigga, I found at least {len(farts)} farts in this chat, it's getting hot!"))


@localized
async def settings_command(update: Update, __: CallbackContext) -> None:
    """Send current chat settings with inline keyboard to change them."""
    chat_id = update.message.chat_id

    # Get chat settings
    settings = await get_chat_settings(chat_id)

    # Create inline keyboard with options
    keyboard = [
        [
            telegram.InlineKeyboardButton(_("Timezone"), callback_data="setting_timezone_change"),
            telegram.InlineKeyboardButton(_("Language"), callback_data="setting_language_change"),
        ]
    ]

    await update.message.reply_text(
        _(f"your settings: {settings}"), reply_markup=telegram.InlineKeyboardMarkup(keyboard)
    )


@localized
async def setting_change_callback(update: Update, __: CallbackContext) -> None:
    """
    Handle callback query for changing chat settings.

    Each callback data must start with "setting_<settingName>_change" to be handled by this function.
    """
    query: CallbackQuery = update.callback_query
    setting_name = query.data.split("_")[1]

    if setting_name == "timezone":
        await query.edit_message_text(_("Timezone change is not implemented yet."))
    elif setting_name == "language":
        keyboard = [
            [telegram.InlineKeyboardButton(lang, callback_data=f"setting_language_set_{lang}")]
            for lang in SUPPORTED_LANGUAGES
        ]
        await query.edit_message_text(_("Select language:"), reply_markup=telegram.InlineKeyboardMarkup(keyboard))
    else:
        logger.warning("Unknown setting name in callback query: %s", setting_name)


@localized
async def setting_language_set_callback(update: Update, __: CallbackContext) -> None:
    """Handle callback query for setting language."""
    query: CallbackQuery = update.callback_query
    language = query.data.split("_")[-1]

    # Change language in the database
    chat_id = update.effective_chat.id
    await update_chat_settings(chat_id, language=language)
    await query.edit_message_text(_(f"Language changed to {language}."))


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = (
        Application.builder()
        .token(environ.get("BOT_TOKEN", None))
        .read_timeout(30)
        .write_timeout(30)
        .rate_limiter(AIORateLimiter(group_time_period=25, group_max_rate=15, max_retries=2))
        .build()
    )

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("uptime", uptime_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("settings", settings_command))

    # Button handlers
    application.add_handler(CallbackQueryHandler(setting_change_callback, pattern=r"setting_.*_change"))
    application.add_handler(CallbackQueryHandler(setting_language_set_callback, pattern=r"setting_language_set_.*"))

    # Voice message
    # NOTE: Currently assuming that all voice messages are farts
    application.add_handler(MessageHandler(filters.VOICE, callback=fart_callback))

    # Set the start time of the bot
    global BOT_START_TIME
    BOT_START_TIME = datetime.datetime.now(tz=datetime.UTC)

    # Notify when the bot starts
    asyncio.run(send_debug_notification("Bot started at " + BOT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
