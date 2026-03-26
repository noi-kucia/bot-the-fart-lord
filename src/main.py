"""Main file."""

import logging
from os import environ

from dotenv import load_dotenv
from telegram import ForceReply, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

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


def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(environ.get("BOT_TOKEN", None)).build()

    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # on non command i.e message - echo the message on Telegram
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))

    # Run the bot until the user presses Ctrl-C
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
