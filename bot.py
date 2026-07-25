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

AUTO_REPLY_TEXT = (
    "Это автоответ от создателя профиля. Ваше сообщение получено. "
    "Пожалуйста, не спамьте и не отправляйте одно и то же сообщение несколько раз. "
    "Спасибо за понимание!"
)


# ─── Chat Automation подключение / отключение ─────────────────────────────────

async def on_business_connection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = update.business_connection
    if conn.is_enabled:
        context.bot_data[f"bc_owner_{conn.id}"] = conn.user.id
        context.bot_data[f"bc_chat_{conn.id}"] = conn.user_chat_id
        logger.info(f"Chat Automation подключён: user_id={conn.user.id}")
        try:
            await context.bot.send_message(
                chat_id=conn.user_chat_id,
                text=(
                    "✅ Chat Automation подключён!\n\n"
                    "Теперь я буду автоматически отвечать на сообщения в твоих личных чатах.\n"
                    "Все входящие сообщения будут пересылаться тебе сюда.\n\n"
                    "Команды в группах:\n"
                    "🔇 /mute — ответь на сообщение → замутить\n"
                    "🔊 /unmute — ответь на сообщение → размутить"
                ),
            )
        except TelegramError as e:
            logger.error(f"Не удалось отправить приветствие: {e}")
    else:
        context.bot_data.pop(f"bc_owner_{conn.id}", None)
        context.bot_data.pop(f"bc_chat_{conn.id}", None)
        logger.info(f"Chat Automation отключён: user_id={conn.user.id}")


# ─── Получение данных о подключении (с защитой от перезапуска бота) ───────────

async def _get_bc_data(context: ContextTypes.DEFAULT_TYPE, conn_id: str):
    """Возвращает (owner_id, owner_chat_id), получая их из кэша или API."""
    owner_id = context.bot_data.get(f"bc_owner_{conn_id}")
    owner_chat_id = context.bot_data.get(f"bc_chat_{conn_id}")
    
    if owner_id and owner_chat_id:
        return owner_id, owner_chat_id
    
    try:
        conn = await context.bot.get_business_connection(conn_id)
        owner_id = conn.user.id
        owner_chat_id = conn.user_chat_id
        context.bot_data[f"bc_owner_{conn_id}"] = owner_id
        context.bot_data[f"bc_chat_{conn_id}"] = owner_chat_id
        return owner_id, owner_chat_id
    except TelegramError as e:
        logger.error(f"Не удалось получить business connection {conn_id}: {e}")
        return None, None


# ─── Авто-ответ и пересылка владельцу ─────────────────────────────────────────

async def handle_business_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message or update.edited_message
    if not message or not message.from_user:
        return

    if message.from_user.is_bot:
        return

    conn_id = message.business_connection_id
    if not conn_id:
        return

    owner_id, owner_chat_id = await _get_bc_data(context, conn_id)
    if not owner_id or not owner_chat_id:
        return

    sender = message.from_user
    if sender.id == owner_id:
        return

    # ─── Автоответ (не шлём повторно на отредактированные сообщения) ───
    if not update.edited_message:
        try:
            await message.reply_text(AUTO_REPLY_TEXT)
        except TelegramError as e:
            logger.error(f"Ошибка авто-ответа: {e}")

    # ─── Пересылка владельцу в ЛС ───
    try:
        sender_name = sender.full_name or sender.first_name or "Неизвестно"
        username = f"@{sender.username}" if sender.username else "нет юзернейма"
        edited_mark = " ✏️ <b>[ОТРЕДАКТИРОВАНО]</b>" if update.edited_message else ""
        
        info = (
            f"📨 <b>Новое сообщение{edited_mark}</b>\n"
            f"👤 <b>От:</b> {sender_name}\n"
            f"🔗 <b>Юзернейм:</b> {username}\n"
            f"🆔 <b>ID:</b> <code>{sender.id}</code>"
        )

        if message.text:
            text_content = message.text_html or message.text or ""
            await context.bot.send_message(
                chat_id=owner_chat_id,
                text=f"{info}\n\n💬 <b>Текст:</b>\n{text_content}",
                parse_mode="HTML"
            )
        else:
            # Медиа, голосовые, стикеры и т.д. — пересылаем через forward
            await context.bot.send_message(
                chat_id=owner_chat_id,
                text=info,
                parse_mode="HTML"
            )
            await message.forward(chat_id=owner_chat_id)
            
    except TelegramError as e:
        logger.error(f"Ошибка пересылки владельцу: {e}")


# ─── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я готов к работе.\n\n"
        "📱 Чтобы настроить авто-ответ:\n"
        "Настройки → Chat Automation → вставь мой @username\n\n"
        "После подключения я буду:\n"
        "• Автоматически отвечать на личные сообщения\n"
        "• Пересылать тебе все входящие сообщения сюда\n\n"
        "📋 Команды для групп:\n"
        "🔇 /mute — ответь на сообщение → замутить\n"
        "🔊 /unmute — ответь на сообщение → размутить"
    )


# ─── Вспомогательная проверка прав ────────────────────────────────────────────

async def _check_admin_rights(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.message
    chat = update.effective_chat
    caller = update.effective_user

    if not message or not chat or not caller:
        return False

    if chat.type not in ("group", "supergroup"):
        await message.reply_text("❌ Эта команда работает только в группах.")
        return False

    # Права бота
    try:
        bot_member = await chat.get_member(context.bot.id)
    except TelegramError:
        await message.reply_text("❌ Не удалось проверить мои права.")
        return False

    bot_can_restrict = False
    if bot_member.status == "creator":
        bot_can_restrict = True
    elif bot_member.status == "administrator":
        bot_can_restrict = bot_member.can_restrict_members

    if not bot_can_restrict:
        await message.reply_text("❌ У меня нет прав для ограничения участников.")
        return False

    # Права вызывающего
    try:
        caller_member = await chat.get_member(caller.id)
    except TelegramError:
        await message.reply_text("❌ Не удалось проверить твои права.")
        return False

    caller_can_restrict = False
    if caller_member.status == "creator":
        caller_can_restrict = True
    elif caller_member.status == "administrator":
        caller_can_restrict = caller_member.can_restrict_members

    if not caller_can_restrict:
        await message.reply_text("❌ У тебя нет прав администратора.")
        return False

    # Проверка reply
    if not message.reply_to_message:
        await message.reply_text("❌ Ответь на сообщение участника, затем введи команду.")
        return False

    target = message.reply_to_message.from_user
    if not target:
        await message.reply_text("❌ Не удалось определить пользователя.")
        return False

    if target.id == caller.id:
        await message.reply_text("❌ Нельзя применить к самому себе.")
        return False

    try:
        target_member = await chat.get_member(target.id)
    except TelegramError:
        await message.reply_text("❌ Не удалось получить информацию об участнике.")
        return False

    if target_member.status in ("creator", "administrator"):
        await message.reply_text("❌ Нельзя ограничить этого участника.")
        return False

    return True


# ─── /mute ─────────────────────────────────────────────────────────────────────

async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_admin_rights(update, context):
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
        logger.error(f"Ошибка при мьюте: {e}")
        await update.message.reply_text("❌ Не удалось ограничить участника.")


# ─── /unmute ───────────────────────────────────────────────────────────────────

async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _check_admin_rights(update, context):
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
        logger.error(f"Ошибка при анмьюте: {e}")
        await update.message.reply_text("❌ Не удалось снять ограничения.")


# ─── Запуск ────────────────────────────────────────────────────────────────────

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

    logger.info("Бот запущен и ждёт подключения через Chat Automation.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
