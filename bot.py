import os
import logging
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    BusinessConnectionHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

AUTO_REPLY_TEXT = (
    "Это автоответ от создателя профиля. Ваше сообщение получено. "
    "Пожалуйста, не спамьте и не отправляйте одно и то же сообщение несколько раз. "
    "Спасибо за понимание!"
)


# ─── Chat Automation подключение ───────────────────────────────────────────────

async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = update.business_connection
    if conn.is_enabled:
        logger.info(f"Chat Automation подключён: user_id={conn.user.id}")
        await context.bot.send_message(
            chat_id=conn.user_chat_id,
            text=(
                "✅ Chat Automation подключён!\n\n"
                "Теперь я буду автоматически отвечать на сообщения в твоих личных чатах.\n\n"
                "Команды в группах:\n"
                "🔇 /mute — ответь на сообщение → замутить\n"
                "🔊 /unmute — ответь на сообщение → размутить"
            ),
        )
    else:
        logger.info(f"Chat Automation отключён: user_id={conn.user.id}")


# ─── Авто-ответ через Chat Automation ─────────────────────────────────────────

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    if not message:
        return

    # Не отвечаем на свои же сообщения
    if message.from_user and message.from_user.is_bot:
        return

    # Не отвечаем если это сообщение от самого владельца аккаунта
    conn_id = message.business_connection_id
    if not conn_id:
        return

    try:
        await message.reply_text(AUTO_REPLY_TEXT)
    except Exception as e:
        logger.error(f"Ошибка авто-ответа: {e}")


# ─── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я готов к работе.\n\n"
        "📱 Чтобы настроить авто-ответ:\n"
        "Настройки → Chat Automation → вставь мой @username\n\n"
        "После подключения я буду автоматически отвечать на твои личные сообщения.\n\n"
        "📋 Команды для групп:\n"
        "🔇 /mute — ответь на сообщение участника → замутить\n"
        "🔊 /unmute — ответь на сообщение участника → размутить"
    )


# ─── /mute ─────────────────────────────────────────────────────────────────────

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat = update.effective_chat
    caller = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("❌ Эта команда работает только в группах.")
        return

    caller_member = await chat.get_member(caller.id)
    if caller_member.status not in ("administrator", "creator"):
        await message.reply_text("❌ У тебя нет прав администратора.")
        return

    if not message.reply_to_message:
        await message.reply_text("❌ Ответь на сообщение участника которого хочешь замутить, затем /mute")
        return

    target = message.reply_to_message.from_user
    if target.id == caller.id:
        await message.reply_text("❌ Нельзя замутить самого себя.")
        return

    try:
        await chat.restrict_member(
            target.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
        )
        name = f"@{target.username}" if target.username else target.first_name
        await message.reply_text(f"🔇 {name} замучен.")
    except Exception as e:
        await message.reply_text(f"❌ Ошибка: {e}")


# ─── /unmute ───────────────────────────────────────────────────────────────────

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat = update.effective_chat
    caller = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("❌ Эта команда работает только в группах.")
        return

    caller_member = await chat.get_member(caller.id)
    if caller_member.status not in ("administrator", "creator"):
        await message.reply_text("❌ У тебя нет прав администратора.")
        return

    if not message.reply_to_message:
        await message.reply_text("❌ Ответь на сообщение участника которого хочешь размутить, затем /unmute")
        return

    target = message.reply_to_message.from_user

    try:
        await chat.restrict_member(
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        name = f"@{target.username}" if target.username else target.first_name
        await message.reply_text(f"🔊 {name} размучен.")
    except Exception as e:
        await message.reply_text(f"❌ Ошибка: {e}")


# ─── Запуск ────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(BusinessConnectionHandler(on_business_connection))

    # Сообщения через Chat Automation (из личных чатов пользователя)
    app.add_handler(
        MessageHandler(
            filters.UpdateType.BUSINESS_MESSAGE & ~filters.COMMAND,
            handle_business_message,
        )
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))

    logger.info("Бот запущен и ждёт подключения через Chat Automation.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
