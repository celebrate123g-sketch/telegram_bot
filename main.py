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

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    if user.username:
        nickname = f"@{user.username}"
    else:
        nickname = user.first_name
    await message.reply(f"Привет, {nickname}! Я бот который сможет тебе напомнить сделать что либо через определенное количество минут. Используй /help чтобы узнать все доступные на данный момент команды.")

@dp.message(Command("remind"))
async def remember(message: types.Message):
    txt = message.text.split(" ")
    if len(txt) < 3:
        await message.reply("Используй формат: /remember (минуты, через сколько нужно сделать напоминание) (текст)")
        return
    try:
        t = int(txt[1])
    except ValueError:
        await message.reply("Минуты должны быть числом!")
        return
    reminder_text = " ".join(txt[2:])
    when = datetime.now() + timedelta(minutes=t)
    job = sched.add_job(remind_me, "date", run_date=when, args=[message.chat.id, reminder_text])
    jobs.append(job)
    reminders.append((t, reminder_text))
    await message.reply(f"Хорошо. Я напомню через {t} минут: {reminder_text}")
    user_id = message.chat.id
    if user_id not in user_stats:
        user_stats[user_id] = {"created": 0, "completed": 0, "deleted": 0}
    user_stats[user_id]["created"] += 1

@dp.message(Command("list"))
async def list_cmd(message: types.Message):
    if not reminders:
        await message.reply("У тебя пока нет напоминаний.")
        return
    text = "Твои напоминания:\n"
    for i, (t, r) in enumerate(reminders, start=1):
        text += f"{i}. Через {t} минут: {r}\n"
    await message.reply(text)

@dp.message(Command("clear"))
async def clear_cmd(message: types.Message):
    user_id = message.chat.id
    count = len(reminders)
    for job in sched.get_jobs():
        job.remove()
    reminders.clear()
    if user_id not in user_stats:
        user_stats[user_id] = {"created": 0, "completed": 0, "deleted": 0}
    user_stats[user_id]["deleted"] += count
    await message.reply(f"Удалено {count} напоминаний.")

@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    text = (
        "Полный список доступных команд:\n"
        "/remind (минуты, через сколько нужно сделать напоминание) (текст) - создать напоминание\n"
        "/list - показать все напоминания\n"
        "/clear - удалить все напоминания\n"
        "/help - показать это сообщение\n"
        "/stats - что бы показать статистику (Создано напоминаний, выполнено, удалено)"
    )
    await message.reply(text)

@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    user_id = message.chat.id
    stats = user_stats.get(user_id, {"created": 0, "completed": 0, "deleted": 0})
    text = (
        "Статистика твоих напоминаний:\n"
        f"Создано: {stats['created']}\n"
        f"Выполнено: {stats['completed']}\n"
        f"Удалено: {stats['deleted']}"
    )
    await message.reply(text)


async def main():
    sched.start()
    print("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
