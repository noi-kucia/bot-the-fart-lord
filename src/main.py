"""Main file."""

import asyncio
import datetime
import logging
import random
from os import environ
from pathlib import Path

import telegram
from dotenv import load_dotenv
from telegram import ForceReply, Update
from telegram.constants import ReactionEmoji
from telegram.ext import Application, CallbackContext, CommandHandler, MessageHandler, filters

load_dotenv(Path(__file__).parent / "env/.env")

# Bot start time to measure uptime
BOT_START_TIME: datetime.datetime = datetime.datetime.now(tz=datetime.UTC)

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s[%(levelname)s]: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def send_debug_notification(message: str) -> None:
    """Send a debug notification to all chats and groups listed in NOTIFICATION_CHAT_IDS environmental var."""
    ids = environ.get("NOTIFICATION_CHAT_IDS", "")

    # Return if no chats were specified
    if not ids:
        logger.warning("No notification chat IDs provided. Skipping debug notification.")
        return

    bot = telegram.Bot(environ.get("BOT_TOKEN", None))

    # Send message to all chats and groups listed in NOTIFICATION_CHAT_IDS environmental var
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


async def help_command(update: Update, _: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text("Help yourself, nigga!")


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
    await update.message.reply_text(response)


async def echo(update: Update, _: CallbackContext) -> None:
    """Echo the user message."""
    await update.message.reply_text(update.message.text)


async def reply_to_fart_voice(update: Update, _: CallbackContext) -> None:
    """Reply to the fart voice message with a random phrase with 20% chance and set a poop reaction."""
    logger.info("Received voice message")

    # Set the poop reaction on the message
    await update.message.set_reaction(ReactionEmoji.PILE_OF_POO)

    # 80% chance to ignore
    if random.random() > 0.2:
        return

    # Reply with a random phrase from the list
    path = Path(__file__).parent.parent / "resources" / "fart_reactions.txt"
    phrase = random.choice(path.read_text().splitlines())
    await update.message.reply_text(phrase, reply_to_message_id=update.message.message_id)


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(environ.get("BOT_TOKEN", None)).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("uptime", uptime_command))

    # Voice message
    application.add_handler(MessageHandler(filters.VOICE, callback=reply_to_fart_voice))

    # Set the start time of the bot
    global BOT_START_TIME
    BOT_START_TIME = datetime.datetime.now(tz=datetime.UTC)

    # Notify when the bot starts
    asyncio.run(send_debug_notification("Bot started at " + BOT_START_TIME.strftime("%Y-%m-%d %H:%M:%S")))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
