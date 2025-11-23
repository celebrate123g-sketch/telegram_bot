import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

TOKEN = "8532049702:AAFpukca2vnRYZDNpzOlssqTNge7RsMAR_I"

bot = Bot(token=TOKEN)
dp = Dispatcher()
sched = AsyncIOScheduler()
reminders = []
user_stats = {}
reminder_history = {}
user_temp = {}

async def reminder_trigger(user_id: int, time: datetime):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выполнено", callback_data=f"done|{time}")],
        [InlineKeyboardButton(text="Не выполнено", callback_data=f"missed|{time}")]
    ])

    await bot.send_message(user_id, f"Напоминание на {time.strftime('%d.%m %H:%M')}", reply_markup=kb)

async def schedule_reminder(user_id: int, time: datetime, scheduler):
    job = scheduler.add_job(
        reminder_trigger,
        "date",
        run_date=time,
        args=[user_id, time]
    )

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    nickname = f"@{user.username}" if user.username else user.first_name
    def main_menu():
        kb = InlineKeyboardBuilder()
        kb.button(text="Поставить напоминание", callback_data="menu_add")
        kb.button(text="Список напоминаний", callback_data="menu_list")
        kb.button(text="Статистика", callback_data="menu_stats")
        kb.button(text="История", callback_data="menu_history")
        kb.button(text="Справка", callback_data="menu_help")
        kb.adjust(1)
        return kb.as_markup()
    await message.reply(
        f"Привет, {nickname}! Я бот, который сможет напомнить тебе сделать что-либо. "
        f"Используй /help чтобы узнать все команды.",
        reply_markup=main_menu()
    )

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Поставить напоминание", callback_data="menu_add")
    kb.button(text="Список напоминаний", callback_data="menu_list")
    kb.adjust(1)
    return kb.as_markup()

def add_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Добавить по времени", callback_data="add_time")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    nickname = f"@{user.username}" if user.username else user.first_name
    def main_menu():
        kb = InlineKeyboardBuilder()
        kb.button(text="Поставить напоминание", callback_data="menu_add")
        kb.button(text="Список напоминаний", callback_data="menu_list")
        kb.button(text="Статистика", callback_data="menu_stats")
        kb.button(text="История", callback_data="menu_history")
        kb.button(text="Справка", callback_data="menu_help")
        kb.adjust(1)
        return kb.as_markup()
    await message.reply(
        f"Привет, {nickname}! Я бот, который сможет напомнить тебе сделать что-либо. "
        f"Используй /help чтобы узнать все команды.",
        reply_markup=main_menu()
    )

@dp.callback_query(lambda c: c.data == "menu_add")
async def open_add_menu(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "Меню добавления:",
        reply_markup=add_menu()
    )
    await cb.answer()

@dp.callback_query(lambda c: c.data == "go_back")
async def back_to_main(cb: types.CallbackQuery):
    await cb.message.edit_text(
        "Главное меню:",
        reply_markup=main_menu()
    )
    await cb.answer()

@dp.callback_query(lambda c: c.data == "list_reminders")
async def list_reminders_callback(callback: CallbackQuery):
    user_id = callback.message.chat.id
    user_reminders = [r for r in reminders if r[0] == user_id]
    if not user_reminders:
        await callback.edit_texty("У тебя пока нет напоминаний.")
    else:
        text = "Твои напоминания:\n"
        for i, (_, r_type, time_str, r_text) in enumerate(user_reminders, start=1):
            text += f"{i}. [{r_type}] {time_str}: {r_text}\n"
        await callback.message.reply(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_stats")
async def show_stats_callback(callback: CallbackQuery):
    user_id = callback.message.chat.id
    stats = user_stats.get(user_id, {"created": 0, "completed": 0, "deleted": 0})
    text = (
        f"Статистика:\n"
        f"Создано: {stats['created']}\n"
        f"Выполнено: {stats['completed']}\n"
        f"Удалено: {stats['deleted']}"
    )
    await callback.message.reply(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "clear_all")
async def clear_all_callback(callback: CallbackQuery):
    user_id = callback.message.chat.id
    jobs_to_remove = [job for job in sched.get_jobs() if job.args[0] == user_id]
    for job in jobs_to_remove:
        job.remove()
    count = sum(1 for r in reminders if r[0] == user_id)
    reminders[:] = [r for r in reminders if r[0] != user_id]
    user_stats.setdefault(user_id, {"created": 0, "completed": 0, "deleted": 0})
    user_stats[user_id]["deleted"] += count
    await callback.message.reply(f"Удалено {count} напоминаний.")
    await callback.answer()

@dp.callback_query(lambda c: c.data == "show_help")
async def show_help_callback(callback: CallbackQuery):
    text = (
        "Доступные команды:\n"
        "/remind - создать напоминание\n"
        "/list - список напоминаний\n"
        "/clear - удалить все напоминания\n"
        "/stats - показать статистику\n"
        "/help - справка\n"
        "/at - установить напоминание на определённое время (HH:MM)\n"
        "/atd - ежедневное напоминание в формате HH:MM"
    )
    await callback.message.reply(text)
    await callback.answer()

@dp.message(Command("at"))
async def time_cmd(message: types.Message):
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.reply("Используй формат: /at HH:MM текст напоминания")
        return
    time_str, reminder_text = parts[1], parts[2]
    try:
        target_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await message.reply("Неверный формат времени! Используй HH:MM")
        return
    now = datetime.now()
    target_datetime = datetime.combine(now.date(), target_time)
    if target_datetime <= now:
        target_datetime += timedelta(days=1)
    sched.add_job(reminder_trigger, "date", run_date=target_datetime, args=[message.chat.id, reminder_text])
    reminders.append((message.chat.id, "по времени", target_datetime.strftime("%H:%M"), reminder_text))
    user_stats.setdefault(message.chat.id, {"created":0, "completed":0, "deleted":0})
    user_stats[message.chat.id]["created"] += 1
    await message.reply(f"Напоминание установлено на {target_datetime.strftime('%H:%M')} — {reminder_text}")

@dp.message(Command("atd"))
async def atd_cmd(message: types.Message):
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.reply("Используй формат: /atd HH:MM текст напоминания")
        return
    time_str, reminder_text = parts[1], parts[2]
    try:
        target_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        await message.reply("Неверный формат времени! Используй HH:MM")
        return
    sched.add_job(
        reminder_trigger,
        "cron",
        hour=target_time.hour,
        minute=target_time.minute,
        args=[message.chat.id, reminder_text],
    )
    reminders.append((message.chat.id, "ежедневно", time_str, reminder_text))
    user_stats.setdefault(message.chat.id, {"created":0, "completed":0, "deleted":0})
    user_stats[message.chat.id]["created"] += 1
    await message.reply(f"Ежедневное напоминание установлено на {time_str} — {reminder_text}")

@dp.message(Command("on"))
async def on_date_cmd(message: types.Message):
    data = message.text.split(" ", 3)
    if len(data) < 4:
        await message.reply("Формат: /on YYYY-MM-DD HH:MM текст")
        return
    date_str = data[1]
    time_str = data[2]
    text = data[3]
    try:
        dt = datetime.strptime(date_str + " " + time_str, "%Y-%m-%d %H:%M")
    except:
        await message.reply("Ошибка! Используй формат даты и времени правильно!")
        return
    if dt <= datetime.now():
        await message.reply("Эта дата уже прошла.")
        return
    sched.add_job(reminder_trigger, "date", run_date=dt, args=[message.chat.id, text])
    reminders.append((message.chat.id, date_str + " " + time_str, text))
    await message.reply("Напоминание создано на " + date_str + " " + time_str)

@dp.callback_query(lambda c: c.data.startswith("done|"))
async def done_callback(callback: CallbackQuery):
    text = callback.data.split("|", 1)[1]
    user_id = callback.from_user.id

    user_stats.setdefault(user_id, {"created": 0, "completed": 0, "deleted": 0})
    user_stats[user_id]["completed"] += 1

    await callback.message.edit_text(f"Отлично! Ты выполнил: {text}")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("notdone|"))
async def not_done_callback(callback: CallbackQuery):
    text = callback.data.split("|", 1)[1]
    await callback.message.edit_text(f"Ты не выполнил: {text}")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith(("done", "missed")))
async def confirm_reminder(callback: types.CallbackQuery):
    action, t = callback.data.split("|")
    t = datetime.fromisoformat(t)
    status = "Выполнено" if action == "done" else "Не выполнено"
    user_id = callback.from_user.id
    if user_id not in reminder_history:
        reminder_history[user_id] = []
    reminder_history[user_id].append({
        "time": t,
        "status": status
    })
    await callback.message.edit_text(
        f"Напоминание на {t.strftime('%d.%m %H:%M')} — {status}"
    )

@dp.message(Command("history"))
async def history_cmd(message: types.Message):
    user_id = message.from_user.id
    if user_id not in reminder_history or len(reminder_history[user_id]) == 0:
        return await message.answer("История пуста")
    items = sorted(reminder_history[user_id], key=lambda x: x["time"])
    text = "\n".join(
        f"{item['time'].strftime('%d.%m %H:%M')} — {item['status']}"
        for item in items
    )
    await message.answer(text)

@dp.callback_query(lambda c: c.data == "list_reminders")
async def list_reminders_callback(callback: CallbackQuery):
    if not reminders:
        await callback.message.reply("У тебя нет напоминаний.")
        return

    text = "Твои напоминания:\n\n"
    kb = InlineKeyboardBuilder()

    for i, rem in enumerate(reminders):
        rem_time = rem.get("time")
        rem_text = rem.get("text")
        text += f"{i+1}. {rem_time} — {rem_text}\n"

        kb.button(text=f"Изменить {i+1}", callback_data=f"edit|{i}")
        kb.button(text=f"Удалить {i+1}", callback_data=f"del|{i}")

    kb.adjust(2)
    await callback.message.reply(text, reply_markup=kb.as_markup())


@dp.callback_query(lambda c: c.data.startswith("edit"))
async def edit_reminder_callback(cb: CallbackQuery):
    edit_index = int(cb.data.split("|")[1])
    index = int(cb.data.split("|")[1])
    user_temp[cb.message.chat.id] = index

    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить время", callback_data="edit_time")
    kb.button(text="Изменить текст", callback_data="edit_text")
    kb.adjust(1)

    await cb.message.reply("Что изменить?", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "edit_time")
async def ask_new_time(cb: CallbackQuery):
    await cb.message.reply("Введи новое время в формате HH:MM:")
    user_temp[cb.message.chat.id] = {"mode": "time", "index": user_temp[cb.message.chat.id]}
    await cb.answer()

@dp.message()
async def catch_edit_message(msg: types.Message):
    user_id = msg.chat.id
    if user_id not in user_temp:
        return
    temp = user_temp[user_id]
    if isinstance(temp, dict) and temp.get("mode") == "time":
        index = temp["index"]
        try:
            new_time = datetime.strptime(msg.text, "%H:%M").strftime("%H:%M")
        except:
            await msg.reply("Неверный формат! Пример: 19:30")
            return
        reminders[index]["time"] = new_time
        await msg.reply(f"Время изменено на {new_time}")
        del user_temp[user_id]

@dp.callback_query(lambda c: c.data == "edit_text")
async def ask_new_text(cb: CallbackQuery):
    user_temp[cb.message.chat.id] = {
        "mode": "text",
        "index": user_temp[cb.message.chat.id]
    }
    await cb.message.reply("Введи новый текст:")
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("del"))
async def delete_reminder(cb: CallbackQuery):
    index = int(cb.data.split("|")[1])

    try:
        reminders.pop(index)
        await cb.message.reply("Напоминание удалено.")
    except:
        await cb.message.reply("Ошибка удаления.")
    await cb.answer()

async def main():
    sched.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
