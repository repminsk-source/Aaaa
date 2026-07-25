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
from telegram.error import TelegramError

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
PORT = int(os.environ.get("PORT", "10000"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

AUTO_REPLY_TEXT = (
    "Это автоответ от создателя профиля. Ваше сообщение получено. "
    "Пожалуйста, не спамьте и не отправляйте одно и то же сообщение несколько раз. "
    "Спасибо за понимание!"
)


async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = update.business_connection
    if conn.is_enabled:
        context.bot_data[f"owner_{conn.id}"] = conn.user.id
        context.bot_data[f"chat_{conn.id}"] = conn.user_chat_id
        logger.info(f"Chat Automation подключён: user_id={conn.user.id}")
        try:
            await context.bot.send_message(
                chat_id=conn.user_chat_id,
                text=(
                    "✅ Chat Automation активен!\n\n"
                    "• Автоответ на личные сообщения\n"
                    "• Пересылка входящих сюда\n\n"
                    "Команды в группах:\n"
                    "🔇 /mute — замутить (ответь на сообщение)\n"
                    "🔊 /unmute — размутить (ответь на сообщение)"
                ),
            )
        except TelegramError as e:
            logger.error(f"Ошибка приветствия: {e}")
    else:
        context.bot_data.pop(f"owner_{conn.id}", None)
        context.bot_data.pop(f"chat_{conn.id}", None)
        logger.info(f"Chat Automation отключён: user_id={conn.user.id}")


async def _get_owner_data(context: ContextTypes.DEFAULT_TYPE, conn_id: str):
    owner_id = context.bot_data.get(f"owner_{conn_id}")
    owner_chat = context.bot_data.get(f"chat_{conn_id}")
    if owner_id and owner_chat:
        return owner_id, owner_chat
    try:
        conn = await context.bot.get_business_connection(conn_id)
        owner_id = conn.user.id
        owner_chat = conn.user_chat_id
        context.bot_data[f"owner_{conn_id}"] = owner_id
        context.bot_data[f"chat_{conn_id}"] = owner_chat
        return owner_id, owner_chat
    except TelegramError as e:
        logger.error(f"Не удалось получить BC {conn_id}: {e}")
        return None, None


async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    if not message or not message.from_user:
        return
    if message.from_user.is_bot:
        return

    conn_id = message.business_connection_id
    if not conn_id:
        return

    owner_id, owner_chat = await _get_owner_data(context, conn_id)
    if not owner_id or not owner_chat:
        return

    sender = message.from_user
    if sender.id == owner_id:
        return

    if update.message:
        try:
            await message.reply_text(AUTO_REPLY_TEXT)
        except TelegramError as e:
            logger.error(f"Ошибка автоответа: {e}")

    try:
        name = sender.full_name or sender.first_name or "Неизвестно"
        username = f"@{sender.username}" if sender.username else "нет юзернейма"
        edited = " ✏️ <b>[ИЗМЕНЕНО]</b>" if update.edited_message else ""
        header = (
            f"📨 <b>Новое сообщение{edited}</b>\n"
            f"👤 <b>От:</b> {name}\n"
            f"🔗 <b>Юзернейм:</b> {username}\n"
            f"🆔 <b>ID:</b> <code>{sender.id}</code>"
        )

        if message.text:
            text = message.text_html or message.text or ""
            await context.bot.send_message(
                chat_id=owner_chat,
                text=f"{header}\n\n💬 {text}",
                parse_mode="HTML"
            )
        else:
            await context.bot.send_message(
                chat_id=owner_chat,
                text=header,
                parse_mode="HTML"
            )
            await message.forward(chat_id=owner_chat)
    except TelegramError as e:
        logger.error(f"Ошибка пересылки: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет!\n\n"
        "📱 Настройка автоответа:\n"
        "Настройки → Chat Automation → введи мой @username\n\n"
        "После этого я буду отвечать на все личные сообщения и пересылать их тебе сюда.\n\n"
        "📋 Команды для групп:\n"
        "🔇 /mute — замутить участника (ответь на его сообщение)\n"
        "🔊 /unmute — размутить участника (ответь на его сообщение)"
    )


async def _check_rights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    msg = update.message
    chat = update.effective_chat
    caller = update.effective_user
    if not msg or not chat or not caller:
        return False

    if chat.type not in ("group", "supergroup"):
        await msg.reply_text("❌ Только для групп.")
        return False

    try:
        bot_member = await chat.get_member(context.bot.id)
    except TelegramError:
        await msg.reply_text("❌ Ошибка проверки прав бота.")
        return False

    bot_ok = bot_member.status == "creator" or (
        bot_member.status == "administrator" and bot_member.can_restrict_members
    )
    if not bot_ok:
        await msg.reply_text("❌ У меня нет прав ограничивать участников.")
        return False

    try:
        caller_member = await chat.get_member(caller.id)
    except TelegramError:
        await msg.reply_text("❌ Ошибка проверки твоих прав.")
        return False

    caller_ok = caller_member.status == "creator" or (
        caller_member.status == "administrator" and caller_member.can_restrict_members
    )
    if not caller_ok:
        await msg.reply_text("❌ Нужны права администратора.")
        return False

    if not msg.reply_to_message:
        await msg.reply_text("❌ Ответь на сообщение участника, затем введи команду.")
        return False

    target = msg.reply_to_message.from_user
    if not target:
        await msg.reply_text("❌ Не удалось определить пользователя.")
        return False

    if target.id == caller.id:
        await msg.reply_text("❌ Нельзя применить к себе.")
        return False

    try:
        target_member = await chat.get_member(target.id)
    except TelegramError:
        await msg.reply_text("❌ Ошибка получения данных участника.")
        return False

    if target_member.status in ("creator", "administrator"):
        await msg.reply_text("❌ Нельзя ограничить администратора.")
        return False

    return True


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_rights(update, context):
        return
    target = update.message.reply_to_message.from_user
    chat = update.effective_chat
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
        await update.message.reply_text(f"🔇 {name} замучен.")
    except TelegramError as e:
        logger.error(f"Ошибка мьюта: {e}")
        await update.message.reply_text("❌ Не удалось замутить.")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_rights(update, context):
        return
    target = update.message.reply_to_message.from_user
    chat = update.effective_chat
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
        await update.message.reply_text(f"🔊 {name} размучен.")
    except TelegramError as e:
        logger.error(f"Ошибка анмьюта: {e}")
        await update.message.reply_text("❌ Не удалось размутить.")


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(BusinessConnectionHandler(on_business_connection))
    app.add_handler(
        MessageHandler(
            (
                filters.UpdateType.BUSINESS_MESSAGE
                | filters.UpdateType.EDITED_BUSINESS_MESSAGE
            )
            & ~filters.COMMAND,
            handle_business_message,
        )
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mute", mute_user))
    app.add_handler(CommandHandler("unmute", unmute_user))

    if WEBHOOK_URL:
        logger.info(f"Запуск webhook на {WEBHOOK_URL}:{PORT}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            allowed_updates=Update.ALL_TYPES,
        )
    else:
        logger.info("WEBHOOK_URL не задан, запуск polling")
        app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
