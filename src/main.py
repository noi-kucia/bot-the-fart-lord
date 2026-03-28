"""Main file."""

import logging
import random
from os import environ
from pathlib import Path

from dotenv import load_dotenv
from telegram import ForceReply, Update
from telegram.constants import ReactionEmoji
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

load_dotenv("env/.env")

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s[%(levelname)s]: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


# Define a few command handlers. These usually take the two arguments update and
# context.
async def start(update: Update) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    await update.message.reply_html(
        rf"Hi {user.mention_html()}!",
        reply_markup=ForceReply(selective=True),
    )

async def help_command(update: Update) -> None:
    """Send a message when the command /help is issued."""
    await update.message.reply_text("Help!")


async def echo(update: Update) -> None:
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

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Voice message
    application.add_handler(MessageHandler(filters.VOICE, callback=reply_to_fart_voice))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
