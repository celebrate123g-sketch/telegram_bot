import asyncio
from datetime import timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

TOKEN = ""

bot = Bot(token=TOKEN)
dp = Dispatcher()
sched = AsyncIOScheduler()

reminders = []
user_stats = {}
reminder_history = {}
user_temp = {}
user_lang = {}
engine = create_engine("sqlite:///reminders.db", echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)
session = SessionLocal()

languages = {
    "ru": {
        "start": "Привет! Выбери раздел:",
        "menu_add": "Поставить напоминание",
        "menu_list": "Список напоминаний",
        "menu_lang": "Язык",
        "lang_set": "Язык установлен: Русский"
    },
    "en": {
        "start": "Hi! Choose a section:",
        "menu_add": "Set reminder",
        "menu_list": "Reminders list",
        "menu_lang": "Language",
        "lang_set": "Language set: English"
    },
    "uz": {
        "start": "Salom! Bo'limni tanlang:",
        "menu_add": "Eslatma qo'shish",
        "menu_list": "Eslatmalar ro'yxati",
        "menu_lang": "Til",
        "lang_set": "Til o'rnatildi: O'zbekcha"
    }
}
CATEGORIES = [
    "Учеба",
    "Спорт",
    "Здоровье",
    "Дом",
    "Работа"
]

class ReminderStat(Base):
    __tablename__ = "reminder_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    text = Column(String)
    time = Column(String)
    type = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    triggered_at = Column(DateTime, nullable=True)

def init_db():
    Base.metadata.create_all(engine)

def t(user_id, key):
    lang = user_lang.get(user_id, "ru")
    return languages.get(lang, languages["ru"]).get(key, key)

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Поставить напоминание", callback_data="menu_add")
    kb.button(text="Список напоминаний", callback_data="menu_list")
    kb.button(text="Статистика", callback_data="menu_stats")
    kb.button(text="История", callback_data="menu_history")
    kb.button(text="Язык", callback_data="menu_lang")
    kb.adjust(1)
    return kb.as_markup()

def add_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="/at HH:MM текст", callback_data="hint_at")
    kb.button(text="/atd HH:MM текст", callback_data="hint_atd")
    kb.button(text="/on YYYY-MM-DD HH:MM текст", callback_data="hint_on")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

def back_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

def lang_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="Русский", callback_data="lang_ru")
    kb.button(text="English", callback_data="lang_en")
    kb.button(text="Uzbek", callback_data="lang_uz")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

async def reminder_trigger(user_id, text, idx):
    await bot.send_message(user_id, f"Напоминание: {text}")
    session = SessionLocal()
    try:
        stat = session.query(ReminderStat).filter_by(
            user_id=user_id,
            text=text
        ).order_by(ReminderStat.id.desc()).first()

        if stat:
            from datetime import datetime
            stat.triggered_at = datetime.utcnow()
            session.commit()

    finally:
        session.close()

class ReminderStat(Base):
    __tablename__ = "reminder_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    text = Column(String)
    time = Column(String)
    type = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    triggered_at = Column(DateTime, nullable=True)

def init_db():
    Base.metadata.create_all(engine)

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    user = message.from_user
    nickname = f"@{user.username}" if user.username else user.first_name
    await message.answer(f"Привет, {nickname}! Я бот-напоминалка.", reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "menu_add")
async def open_add_menu(cb: CallbackQuery):
    await cb.message.edit_text("Создать напоминание (подсказки):", reply_markup=add_menu())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "go_back")
async def back_to_main(cb: CallbackQuery):
    await cb.message.edit_text("Главное меню:", reply_markup=main_menu())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_list")
async def open_list(cb: CallbackQuery):
    user_id = cb.from_user.id
    user_reminders = [(i, r) for i, r in enumerate(reminders) if r["user_id"] == user_id]

    if not user_reminders:
        await cb.message.edit_text("У тебя нет напоминаний.", reply_markup=back_kb())
        return await cb.answer()

    text = ""
    kb = InlineKeyboardBuilder()

    for i, (idx, r) in enumerate(user_reminders, start=1):
        text += f"{i}. {r['time']} — {r['text']}\n"
        kb.button(text=f"Изменить {i}", callback_data=f"edit|{idx}")
        kb.button(text=f"Удалить {i}", callback_data=f"del|{idx}")

    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(2)

    await cb.message.edit_text("Твои напоминания:\n\n" + text, reply_markup=kb.as_markup())
    await cb.answer()


@dp.message(Command("stats"))
async def stats_cmd(message: types.Message):
    session = SessionLocal()
    rows = session.query(ReminderStat).filter_by(user_id=message.from_user.id).all()
    session.close()
    if not rows:
        return await message.reply("У тебя пока нет статистики.")
    text = "Твоя статистика напоминаний:\n\n"
    for r in rows:
        text += f"- {r.text} ({r.type}) — создано: {r.created_at}"
        if r.triggered_at:
            text += f", сработало: {r.triggered_at}"
        text += "\n"
    await message.reply(text)

@dp.callback_query(lambda c: c.data == "menu_history")
async def open_history(cb: CallbackQuery):
    user_id = cb.from_user.id
    items = reminder_history.get(user_id, [])

    if not items:
        await cb.message.edit_text("История пуста", reply_markup=back_kb())
        return await cb.answer()

    text = "\n".join(f"{it['time'].strftime('%d.%m %H:%M')} — {it['status']}" for it in items)
    await cb.message.edit_text("История:\n" + text, reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_lang")
async def open_lang(cb: CallbackQuery):
    await cb.message.edit_text("Выберите язык:", reply_markup=lang_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def set_lang(cb: CallbackQuery):
    code = cb.data.split("_",1)[1]
    user_lang[cb.from_user.id] = code
    await cb.message.edit_text(languages.get(code, languages["ru"])["lang_set"], reply_markup=main_menu())
    await cb.answer()

@dp.message(Command("at"))
async def cmd_at(message: types.Message):
    parts = message.text.split(" ",2)
    if len(parts) < 3:
        return await message.reply("Используй формат: /at HH:MM текст")

    time_str, text = parts[1], parts[2]

    try:
        tm = datetime.strptime(time_str, "%H:%M").time()
    except:
        return await message.reply("Неверный формат времени")

    now = datetime.now()
    dt = datetime.combine(now.date(), tm)
    if dt <= now:
        dt += timedelta(days=1)

    idx = len(reminders)
    reminders.append({"user_id": message.chat.id, "type":"once", "time": time_str, "text": text, "job": None})

    job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[message.chat.id, text, idx])
    reminders[idx]["job"] = job

    user_stats.setdefault(message.chat.id, {"created":0,"completed":0,"deleted":0})
    user_stats[message.chat.id]["created"] += 1

    await message.reply(f"Напоминание установлено на {time_str}: {text}")

@dp.message(Command("atd"))
async def cmd_atd(message: types.Message):
    parts = message.text.split(" ",2)
    if len(parts) < 3:
        return await message.reply("Используй формат: /atd HH:MM текст")
    time_str, text = parts[1], parts[2]
    try:
        tm = datetime.strptime(time_str, "%H:%M").time()
    except:
        return await message.reply("Неверный формат времени")
    idx = len(reminders)
    job = sched.add_job(reminder_trigger, "cron", hour=tm.hour, minute=tm.minute, args=[message.chat.id, text, idx])
    reminders.append({"user_id": message.chat.id, "type":"daily", "time": time_str, "text": text, "job": job})
    user_stats.setdefault(message.chat.id, {"created":0,"completed":0,"deleted":0})
    user_stats[message.chat.id]["created"] += 1
    await message.reply(f"Ежедневное напоминание установлено на {time_str}: {text}")

@dp.message(Command("on"))
async def cmd_on(message: types.Message):
    parts = message.text.split(" ",3)
    if len(parts) < 4:
        return await message.reply("Используй формат: /on YYYY-MM-DD HH:MM текст")

    date_str, time_str, text = parts[1], parts[2], parts[3]

    try:
        dt = datetime.strptime(date_str + " " + time_str, "%Y-%m-%d %H:%M")
    except:
        return await message.reply("Неверный формат даты/времени")

    if dt <= datetime.now():
        return await message.reply("Дата уже прошла")

    idx = len(reminders)
    reminders.append({"user_id": message.chat.id, "type":"once", "time": f"{date_str} {time_str}", "text": text, "job": None})

    job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[message.chat.id, text, idx])
    reminders[idx]["job"] = job

    user_stats.setdefault(message.chat.id, {"created":0,"completed":0,"deleted":0})
    user_stats[message.chat.id]["created"] += 1

    await message.reply(f"Напоминание создано на {date_str} {time_str}")

@dp.callback_query(lambda c: c.data.startswith("done|"))
async def done_cb(callback: CallbackQuery):
    idx = int(callback.data.split("|",1)[1])
    user_id = callback.from_user.id

    user_stats.setdefault(user_id, {"created":0,"completed":0,"deleted":0})
    user_stats[user_id]["completed"] += 1

    reminder_history.setdefault(user_id, [])
    reminder_history[user_id].append({"time": datetime.now(), "status":"Выполнено"})

    await callback.message.edit_text("Отмечено как выполненное")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("missed|"))
async def missed_cb(callback: CallbackQuery):
    idx = int(callback.data.split("|",1)[1])
    user_id = callback.from_user.id

    reminder_history.setdefault(user_id, [])
    reminder_history[user_id].append({"time": datetime.now(), "status":"Не выполнено"})

    await callback.message.edit_text("Отмечено как не выполненное")
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("edit|"))
async def edit_choice(cb: CallbackQuery):
    idx = int(cb.data.split("|",1)[1])
    user_temp[cb.from_user.id] = {"mode": None, "index": idx}

    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить время", callback_data=f"edit_time|{idx}")
    kb.button(text="Изменить текст", callback_data=f"edit_text|{idx}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)

    await cb.message.edit_text("Что изменить?", reply_markup=kb.as_markup())
    await cb.answer()

@dp.message_handler(lambda m: m.from_user.id in user_temp and user_temp[m.from_user.id]["step"] == "category")
async def get_category(msg: types.Message):
    user_id = msg.from_user.id
    cat = msg.text

    if cat not in CATEGORIES:
        return await msg.reply("Выберите категорию из списка")

    user_temp[user_id]["category"] = cat
    user_temp[user_id]["step"] = "text"

    await msg.reply("Введите текст напоминания", reply_markup=types.ReplyKeyboardRemove())

@dp.message_handler(lambda m: m.from_user.id in user_temp and user_temp[m.from_user.id]["step"] == "text")
async def get_text(msg: types.Message):
    user_id = msg.from_user.id
    text = msg.text

    user_temp[user_id]["text"] = text
    user_temp[user_id]["step"] = "time"

    await msg.reply("Введите время (формат ЧЧ:ММ)")

@dp.callback_query(lambda c: c.data.startswith("edit_time|"))
async def ask_new_time(cb: CallbackQuery):
    idx = int(cb.data.split("|",1)[1])
    user_temp[cb.from_user.id] = {"mode":"time", "index": idx}
    await cb.message.edit_text("Введи новое время (HH:MM):", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_text|"))
async def ask_new_text(cb: CallbackQuery):
    idx = int(cb.data.split("|",1)[1])
    user_temp[cb.from_user.id] = {"mode":"text", "index": idx}
    await cb.message.edit_text("Введи новый текст:", reply_markup=back_kb())
    await cb.answer()

@dp.message()
async def catch_edit(msg: types.Message):
    user_id = msg.from_user.id
    if user_id not in user_temp:
        return

    temp = user_temp[user_id]
    idx = temp["index"]

    if temp["mode"] == "time":
        try:
            datetime.strptime(msg.text, "%H:%M")
        except ValueError:
            await msg.reply("Неверный формат времени")
            return
        job = reminders[idx].get("job")
        if job:
            try:
                job.remove()
            except (AttributeError, RuntimeError):
                pass
        reminders[idx]["time"] = msg.text
        tm = datetime.strptime(msg.text, "%H:%M").time()
        if reminders[idx]["type"] == "once":
            now = datetime.now()
            dt = datetime.combine(now.date(), tm)
            if dt <= now:
                dt += timedelta(days=1)
            job = sched.add_job(
                reminder_trigger,
                "date",
                run_date=dt,
                args=[reminders[idx]["user_id"], reminders[idx]["text"], idx]
            )
            reminders[idx]["job"] = job
        elif reminders[idx]["type"] == "daily":
            job = sched.add_job(
                reminder_trigger,
                "cron",
                hour=tm.hour,
                minute=tm.minute,
                args=[reminders[idx]["user_id"], reminders[idx]["text"], idx]
            )
            reminders[idx]["job"] = job
        await msg.reply("Время изменено")
        user_temp.pop(user_id, None)
    elif temp["mode"] == "text":
        reminders[idx]["text"] = msg.text
        await msg.reply("Текст напоминания обновлён")
        user_temp.pop(user_id, None)

@dp.callback_query(lambda c: c.data.startswith("del|"))
async def delete_cb(cb: CallbackQuery):
    idx = int(cb.data.split("|",1)[1])

    if idx < 0 or idx >= len(reminders):
        await cb.message.edit_text("Ошибка: не найдено", reply_markup=back_kb())
        return await cb.answer()

    job = reminders[idx].get("job")
    if job:
        try:
            job.remove()
        except:
            pass

    reminders[idx] = None

    user_stats.setdefault(cb.from_user.id, {"created":0,"completed":0,"deleted":0})
    user_stats[cb.from_user.id]["deleted"] += 1

    await cb.message.edit_text("Напоминание удалено", reply_markup=back_kb())
    await cb.answer()

@dp.message_handler(commands=["add"])
async def add_cmd(msg: types.Message):
    user_id = msg.from_user.id
    user_temp[user_id] = {"step": "category"}

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for c in CATEGORIES:
        kb.add(c)

    await msg.reply("Выберите категорию", reply_markup=kb)


@dp.message(Command("history"))
async def history_cmd(message: types.Message):
    user_id = message.from_user.id
    items = reminder_history.get(user_id, [])

    if not items:
        return await message.reply("История пуста")

    text = "\n".join(f"{it['time'].strftime('%d.%m %H:%M')} — {it['status']}" for it in items)
    await message.reply(text)

async def main():
    sched.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
