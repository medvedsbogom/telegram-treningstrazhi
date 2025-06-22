import logging
import json
import os
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, __version__ as telegram_version
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
from telegram.error import TelegramError
from flask import Flask

# Настройка Flask для health-check
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running", 200

# Проверяем версию библиотеки
print(f"Using python-telegram-bot version: {telegram_version}")

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Токен бота из .env
from dotenv import load_dotenv
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("Токен бота не установлен! Проверь .env.")
    exit(1)

# Путь к файлам данных (относительный)
DATA_FILE = "bot_data.json"
LOG_FILE = "action_log.json"

# Состояние для ConversationHandler
SET_TITLE = 0

# Загрузка данных из файла
def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                logger.warning(f"Файл {DATA_FILE} пустой, возвращаем значения по умолчанию")
                return [], [], set(), "", None
            data = json.loads(content)
            return (
                data.get("participants", []),
                data.get("queue", []),
                set(data.get("payments", [])),
                data.get("custom_title", ""),
                data.get("message_id", None)
            )
    except FileNotFoundError:
        logger.warning(f"Файл {DATA_FILE} не найден, создаём новый")
        save_data([], [], set(), "", None)
        return [], [], set(), "", None
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка при разборе {DATA_FILE}: {e}, возвращаем значения по умолчанию")
        return [], [], set(), "", None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при загрузке {DATA_FILE}: {e}")
        return [], [], set(), "", None

# Сохранение данных в файл
def save_data(participants, queue, payments, custom_title, message_id):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump({
                "participants": participants,
                "queue": queue,
                "payments": list(payments),
                "custom_title": custom_title,
                "message_id": message_id
            }, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении данных в {DATA_FILE}: {e}")

# Загрузка лога действий
def load_action_log():
    try:
        with open(LOG_FILE, "r") as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except FileNotFoundError:
        logger.warning(f"Файл {LOG_FILE} не найден, создаём новый")
        save_action_log([])
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка при разборе {LOG_FILE}: {e}")
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при загрузке {LOG_FILE}: {e}")
        return []

# Сохранение лога действий
def save_action_log(log):
    try:
        with open(LOG_FILE, "w") as f:
            json.dump(log, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка при сохранении лога в {LOG_FILE}: {e}")

# Логирование действия
def log_action(user_id, user_name, action):
    action_log = load_action_log()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    action_log.append({
        "timestamp": timestamp,
        "user_id": user_id,
        "user_name": user_name,
        "action": action
    })
    save_action_log(action_log)

# Глобальные переменные
participants, queue, payments, custom_title, message_id = load_data()

# Функция для создания инлайн-клавиатуры
def create_keyboard(is_admin=False):
    keyboard = [
        [InlineKeyboardButton("Записаться", callback_data="signup")],
        [InlineKeyboardButton("Под вопросом", callback_data="maybe")],
        [InlineKeyboardButton("Форс-мажор", callback_data="force_majeure")],
        [InlineKeyboardButton("Оплатил", callback_data="paid")]
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("📊 Статистика", callback_data="stats")])
    return InlineKeyboardMarkup(keyboard)

# Функция для создания диалогового меню
def create_menu_keyboard(is_admin=False):
    keyboard = [
        ["/start", "/menu"],
        ["/settitle", "/cleartitle", "/clearall"]
    ]
    if is_admin:
        keyboard.append(["/stats"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# Функция для форматирования списка участников и очереди
def format_list():
    title = custom_title if custom_title else "Список участников и очередь"
    message = f"📋 <b>{title}</b>\n\n"
    message += "👥 Записавшиеся:\n"
    if participants:
        for i, user in enumerate(participants, 1):
            status = "✅" if user["id"] in payments else ""
            message += f"{i}. {user['name']} {status}\n"
    else:
        message += "Пока никто не записался.\n"

    message += "\n🕒 Очередь:\n"
    if queue:
        for i, user in enumerate(queue, 1):
            status = "✅" if user["id"] in payments else ""
            message += f"{i}. {user['name']} {status}\n"
    else:
        message += "Очередь пуста.\n"

    return message

# Функция для форматирования статистики
def format_stats():
    action_log = load_action_log()
    if not action_log:
        return "📊 <b>Статистика действий</b>\n\nНет записанных действий."

    message = "📊 <b>Статистика действий</b>\n\n"
    for entry in action_log:
        message += f"[{entry['timestamp']}] {entry['user_name']} ({entry['user_id']}): {entry['action']}\n"
    return message

# Проверка, является ли пользователь администратором
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception as e:
        logger.error(f"Ошибка при проверке статуса администратора: {e}")
        return False

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_id
    is_admin_user = await is_admin(update, context)
    await update.message.reply_text(
        "Добро пожаловать! Используйте кнопки для взаимодействия или /menu для просмотра всех команд.",
        reply_markup=create_menu_keyboard(is_admin_user)
    )
    sent_message = await update.message.reply_text(
        format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
    )
    message_id = sent_message.message_id
    save_data(participants, queue, payments, custom_title, message_id)

# Обработчик команды /menu
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    is_admin_user = await is_admin(update, context)
    await update.message.reply_text(
        "Выберите команду из меню ниже:",
        reply_markup=create_menu_keyboard(is_admin_user)
    )

# Обработчик команды /stats
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_admin(update, context):
        await update.message.reply_text("Эта команда доступна только администраторам группы!")
        return
    await update.message.reply_text(format_stats(), parse_mode="HTML")

# Обработчик команды /settitle (начало)
async def set_title_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not await is_admin(update, context):
        await update.message.reply_text("Эта команда доступна только администраторам группы!")
        return ConversationHandler.END

    await update.message.reply_text(
        "Пожалуйста, введите новый заголовок:",
        reply_markup=ReplyKeyboardRemove()
    )
    return SET_TITLE

# Обработчик ввода заголовка
async def set_title_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global custom_title, message_id
    is_admin_user = await is_admin(update, context)
    custom_title = update.message.text.strip()
    save_data(participants, queue, payments, custom_title, message_id)
    log_action(update.effective_user.id, update.effective_user.full_name or "Без имени", f"Установил заголовок: {custom_title}")
    await update.message.reply_text(
        f"Заголовок установлен: {custom_title}",
        reply_markup=create_menu_keyboard(is_admin_user)
    )
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=message_id,
                text=format_list(),
                parse_mode="HTML",
                reply_markup=create_keyboard(is_admin_user)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await update.message.reply_text(
                format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
            )
            message_id = sent_message.message_id
            save_data(participants, queue, payments, custom_title, message_id)
    else:
        sent_message = await update.message.reply_text(
            format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
        )
        message_id = sent_message.message_id
        save_data(participants, queue, payments, custom_title, message_id)
    return ConversationHandler.END

# Обработчик отмены ввода заголовка
async def set_title_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    is_admin_user = await is_admin(update, context)
    await update.message.reply_text(
        "Установка заголовка отменена.",
        reply_markup=create_menu_keyboard(is_admin_user)
    )
    return ConversationHandler.END

# Обработчик команды /cleartitle
async def clear_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global custom_title, message_id
    is_admin_user = await is_admin(update, context)
    if not is_admin_user:
        await update.message.reply_text("Эта команда доступна только администраторам группы!")
        return

    custom_title = ""
    save_data(participants, queue, payments, custom_title, message_id)
    log_action(update.effective_user.id, update.effective_user.full_name or "Без имени", "Сбросил заголовок")
    await update.message.reply_text(
        "Заголовок сброшен.",
        reply_markup=create_menu_keyboard(is_admin_user)
    )
    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=message_id,
                text=format_list(),
                parse_mode="HTML",
                reply_markup=create_keyboard(is_admin_user)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await update.message.reply_text(
                format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
            )
            message_id = sent_message.message_id
            save_data(participants, queue, payments, custom_title, message_id)
    else:
        sent_message = await update.message.reply_text(
            format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
        )
        message_id = sent_message.message_id
        save_data(participants, queue, payments, custom_title, message_id)

# Обработчик команды /clearall
async def clear_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global participants, queue, payments, custom_title, message_id
    is_admin_user = await is_admin(update, context)
    if not is_admin_user:
        await update.message.reply_text("Эта команда доступна только администраторам группы!")
        return

    participants = []
    queue = []
    payments = set()
    custom_title = ""
    save_data(participants, queue, payments, custom_title, message_id)
    log_action(update.effective_user.id, update.effective_user.full_name or "Без имени", "Очистил все данные")
    await update.message.reply_text(
        "Список, очередь и все данные успешно очищены.",
        reply_markup=create_menu_keyboard(is_admin_user)
    )

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=message_id,
                text=format_list(),
                parse_mode="HTML",
                reply_markup=create_keyboard(is_admin_user)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await update.message.reply_text(
                format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
            )
            message_id = sent_message.message_id
            save_data(participants, queue, payments, custom_title, message_id)
    else:
        sent_message = await update.message.reply_text(
            format_list(), parse_mode="HTML", reply_markup=create_keyboard(is_admin_user)
        )
        message_id = sent_message.message_id
        save_data(participants, queue, payments, custom_title, message_id)

# Обработчик нажатий на кнопки
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global message_id
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user_name = query.from_user.full_name or query.from_user.username or "Без имени"
    user_data = {"id": user_id, "name": user_name}
    is_admin_user = await is_admin(update, context)
    notification = ""

    if query.data == "stats":
        if not is_admin_user:
            await query.message.reply_text("Эта функция доступна только администраторам!")
            return
        await query.message.reply_text(format_stats(), parse_mode="HTML")
        return

    if query.data == "signup":
        if any(user["id"] == user_id for user in queue):
            queue[:] = [user for user in queue if user["id"] != user_id]
            if len(participants) < 12:
                participants.append(user_data)
                notification = f"{user_name}, вы перемещены из очереди в список участников! Позиция: {len(participants)}"
                log_action(user_id, user_name, "Перемещен из очереди в участники")
            else:
                queue.append(user_data)
                notification = f"{user_name}, вы уже в очереди!"
                log_action(user_id, user_name, "Попытка повторной записи в очередь")
        elif any(user["id"] == user_id for user in participants):
            notification = "Вы уже записаны в список участников!"
            log_action(user_id, user_name, "Попытка повторной записи в участники")
        else:
            if len(participants) < 12:
                participants.append(user_data)
                notification = f"{user_name}, вы записаны в список! Позиция: {len(participants)}"
                log_action(user_id, user_name, "Записался в участники")
            else:
                queue.append(user_data)
                notification = f"{user_name}, вы добавлены в очередь! Позиция: {len(queue)}"
                log_action(user_id, user_name, "Добавлен в очередь")

    elif query.data == "maybe":
        if any(user["id"] == user_id for user in participants):
            participants[:] = [user for user in participants if user["id"] != user_id]
            queue.append(user_data)
            notification = f"{user_name}, вы перемещены из списка участников в очередь! Позиция: {len(queue)}"
            log_action(user_id, user_name, "Перемещен из участников в очередь (под вопросом)")
        elif any(user["id"] == user_id for user in queue):
            notification = "Вы уже в очереди под вопросом!"
            log_action(user_id, user_name, "Попытка повторной записи в очередь (под вопросом)")
        else:
            queue.append(user_data)
            notification = f"{user_name}, вы добавлены в очередь под вопросом! Позиция: {len(queue)}"
            log_action(user_id, user_name, "Добавлен в очередь (под вопросом)")

    elif query.data == "force_majeure":
        original_participants_len = len(participants)
        participants[:] = [user for user in participants if user["id"] != user_id]
        queue[:] = [user for user in queue if user["id"] != user_id]
        payments.discard(user_id)
        if original_participants_len > len(participants) or queue:
            notification = f"{user_name}, вы удалены из списка/очереди."
            log_action(user_id, user_name, "Удален из списка/очереди (форс-мажор)")
        else:
            notification = "Вы не были записаны."
            log_action(user_id, user_name, "Попытка удаления (форс-мажор, не был записан)")

    elif query.data == "paid":
        if any(user["id"] == user_id for user in participants + queue):
            payments.add(user_id)
            notification = f"{user_name}, отмечено как оплачено! ✅"
            log_action(user_id, user_name, "Отметил оплату")
        else:
            notification = "Вы не записаны, сначала запишитесь!"
            log_action(user_id, user_name, "Попытка отметить оплату (не записан)")

    save_data(participants, queue, payments, custom_title, message_id)

    message_text = f"{notification}\n\n{format_list()}"

    if message_id:
        try:
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=message_id,
                text=message_text,
                parse_mode="HTML",
                reply_markup=create_keyboard(is_admin_user)
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            sent_message = await query.message.reply_text(
                text=message_text,
                parse_mode="HTML",
                reply_markup=create_keyboard(is_admin_user)
            )
            message_id = sent_message.message_id
            save_data(participants, queue, payments, custom_title, message_id)
    else:
        sent_message = await query.message.reply_text(
            text=message_text,
            parse_mode="HTML",
            reply_markup=create_keyboard(is_admin_user)
        )
        message_id = sent_message.message_id
        save_data(participants, queue, payments, custom_title, message_id)

# Основная функция с обработкой перезапусков
def run_bot():
    try:
        logger.info("Запуск бота...")
        application = Application.builder().token(TOKEN).build()

        conv_handler = ConversationHandler(
            entry_points=[CommandHandler('settitle', set_title_start)],
            states={
                SET_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_title_save)],
            },
            fallbacks=[CommandHandler('cancel', set_title_cancel)]
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", menu))
        application.add_handler(CommandHandler("stats", stats))
        application.add_handler(CommandHandler("cleartitle", clear_title))
        application.add_handler(CommandHandler("clearall", clear_all))
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(button))

        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except TelegramError as te:
        logger.error(f"Ошибка Telegram: {te}")
    except Exception as e:
        logger.error(f"Неизвестная ошибка: {e}")

if __name__ == "__main__":
    import threading
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=8080)
