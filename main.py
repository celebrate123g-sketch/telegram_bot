import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

TOKEN = " "

bot = Bot(token=TOKEN)
dp = Dispatcher()
sched = AsyncIOScheduler()
reminders = []
jobs = []
user_stats = {}

async def remind_me(chat_id, text):
    await bot.send_message(chat_id, "Напоминание " + text)
    user_stats.setdefault(chat_id, {"created": 0, "completed": 0, "deleted": 0})
    user_stats[chat_id]["completed"] += 1

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    nickname = f"@{user.username}" if user.username else user.first_name

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Поставить напоминание", callback_data="add_reminder")],
        [InlineKeyboardButton(text="Показать все напоминания", callback_data="list_reminders")],
        [InlineKeyboardButton(text="Показать статистику", callback_data="show_stats")],
        [InlineKeyboardButton(text="Удалить все напоминания", callback_data="clear_all")],
        [InlineKeyboardButton(text="Помощь", callback_data="show_help")]
    ])

    await message.reply(f"Привет, {nickname}! Я бот который сможет тебе напомнить сделать что либо через определенное количество минут. Используй /help чтобы узнать все доступные на данный момент команды.",
        reply_markup=keyboard
    )

@dp.callback_query(lambda c: c.data == "add_reminder")
async def add_reminder_callback(callback: CallbackQuery):
    await callback.message.reply("Используй команду:\n/remind <минуты> <текст>")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "list_reminders")
async def list_reminders_callback(callback: CallbackQuery):
    if not reminders:
        await callback.message.reply("У тебя пока нет напоминаний.")
    else:
        text = "Твои напоминания:\n"
        for i, (t, r) in enumerate(reminders, start=1):
            text += f"{i}. Через {t} минут: {r}\n"
        await callback.message.reply(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_stats")
async def show_stats_callback(callback: CallbackQuery):
    user_id = callback.message.chat.id
    stats = user_stats.get(user_id, {"created": 0, "completed": 0, "deleted": 0})
    text = (
        "Статистика:\n"
        f"Создано: {stats['created']}\n"
        f"Выполнено: {stats['completed']}\n"
        f"Удалено: {stats['deleted']}"
    )
    await callback.message.reply(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "clear_all")
async def clear_all_callback(callback: CallbackQuery):
    for job in sched.get_jobs():
        job.remove()
    count = len(reminders)
    reminders.clear()
    user_id = callback.message.chat.id
    user_stats.setdefault(user_id, {"created": 0, "completed": 0, "deleted": 0})
    user_stats[user_id]["deleted"] += count
    await callback.message.reply(f"Удалено {count} напоминаний.")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_help")
async def show_help_callback(callback: CallbackQuery):
    text = (
        "Доступные команды:\n"
        "/remind — создать напоминание\n"
        "/list — список напоминаний\n"
        "/clear — удалить все напоминания\n"
        "/stats — показать статистику\n"
        "/help — справка\n\n"
        "Также можно использовать кнопки меню для удобства."
    )
    await callback.message.reply(text)
    await callback.answer()

async def main():
    sched.start()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
