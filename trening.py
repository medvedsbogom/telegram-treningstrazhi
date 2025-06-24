import logging
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Настройка логирования (только в stdout для Docker)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Токен бота (вставлен напрямую для простоты)
TOKEN = "8048456136:AAHnpah8JeI2Zkio4UZaCLShc0NBQoSMbg8"

# Функция команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info(f"Получена команда /start от {update.effective_user.username or 'неизвестный пользователь'}")
    keyboard = [
        [InlineKeyboardButton("Сосал?", callback_data="sosal")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Нажми кнопку:", reply_markup=reply_markup)

# Функция обработки кнопки
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    logger.info(f"Получен callback: {query.data} от {query.from_user.username or 'неизвестный пользователь'}")
    if query.data == "sosal":
        await query.edit_message_text("Воняет попа")

def main() -> None:
    logger.info("Запуск бота...")
    application = Application.builder().token(TOKEN).build()
    logger.info("Приложение инициализировано")
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button))
    logger.info("Обработчики добавлены, запуск polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
