import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

TOKEN = ""

bot = Bot(token=TOKEN)
dp = Dispatcher()
sched = AsyncIOScheduler()

engine = create_engine("sqlite:///reminders.db", echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

reminders = []
user_temp = {}
user_lang = {}
user_stats = {}
reminder_history = {}

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

CATEGORIES = ["Учеба", "Спорт", "Здоровье", "Дом", "Работа"]

class ReminderStat(Base):
    __tablename__ = "reminder_stats"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    text = Column(String)
    time = Column(String)
    type = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    triggered_at = Column(DateTime, nullable=True)

Base.metadata.create_all(engine)

def t(user_id, key):
    lang = user_lang.get(user_id, "ru")
    return languages.get(lang, languages["ru"]).get(key, key)

def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Поставить напоминание", callback_data="menu_add")
    kb.button(text="Список", callback_data="menu_list")
    kb.button(text="Статистика", callback_data="menu_stats")
    kb.button(text="История", callback_data="menu_history")
    kb.button(text="Язык", callback_data="menu_lang")
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
    await bot.send_message(user_id, "Напоминание: " + text)
    s = SessionLocal()
    row = s.query(ReminderStat).filter_by(user_id=user_id, text=text).order_by(ReminderStat.id.desc()).first()
    if row:
        row.triggered_at = datetime.utcnow()
        s.commit()
    s.close()

@dp.message(Command("start"))
async def start_cmd(message: types.Message):
    await message.answer(t(message.from_user.id, "start"), reply_markup=main_menu())

@dp.callback_query(lambda c: c.data == "go_back")
async def go_back(cb: CallbackQuery):
    await cb.message.edit_text("Главное меню:", reply_markup=main_menu())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_add")
async def menu_add(cb: CallbackQuery):
    await cb.message.edit_text("Создание напоминания:\nКоманды:\n/at HH:MM текст\n/atd HH:MM текст\n/on YYYY-MM-DD HH:MM текст", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_lang")
async def menu_lang(cb: CallbackQuery):
    await cb.message.edit_text("Выберите язык:", reply_markup=lang_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("lang_"))
async def set_lang(cb: CallbackQuery):
    code = cb.data.split("_")[1]
    user_lang[cb.from_user.id] = code
    await cb.message.edit_text(languages[code]["lang_set"], reply_markup=main_menu())
    await cb.answer()

@dp.message(Command("at"))
async def cmd_at(message: types.Message):
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.reply("Формат: /at HH:MM текст")
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
    job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[message.from_user.id, text, idx])
    reminders.append({"user_id": message.from_user.id, "type": "once", "time": time_str, "text": text, "job": job})
    s = SessionLocal()
    s.add(ReminderStat(user_id=message.from_user.id, text=text, time=time_str, type="once"))
    s.commit()
    s.close()
    await message.reply("Напоминание создано")

@dp.message(Command("atd"))
async def cmd_atd(message: types.Message):
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        return await message.reply("Формат: /atd HH:MM текст")
    time_str, text = parts[1], parts[2]
    try:
        tm = datetime.strptime(time_str, "%H:%M").time()
    except:
        return await message.reply("Ошибка времени")
    idx = len(reminders)
    job = sched.add_job(reminder_trigger, "cron", hour=tm.hour, minute=tm.minute, args=[message.from_user.id, text, idx])
    reminders.append({"user_id": message.from_user.id, "type": "daily", "time": time_str, "text": text, "job": job})
    s = SessionLocal()
    s.add(ReminderStat(user_id=message.from_user.id, text=text, time=time_str, type="daily"))
    s.commit()
    s.close()
    await message.reply("Ежедневное напоминание создано")

@dp.message(Command("on"))
async def cmd_on(message: types.Message):
    parts = message.text.split(" ", 3)
    if len(parts) < 4:
        return await message.reply("Формат: /on YYYY-MM-DD HH:MM текст")
    date_str, time_str, text = parts[1], parts[2], parts[3]
    try:
        dt = datetime.strptime(date_str + " " + time_str, "%Y-%m-%d %H:%M")
    except:
        return await message.reply("Ошибка даты")
    if dt <= datetime.now():
        return await message.reply("Дата уже прошла")
    idx = len(reminders)
    job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[message.from_user.id, text, idx])
    reminders.append({"user_id": message.from_user.id, "type": "once", "time": date_str + " " + time_str, "text": text, "job": job})
    s = SessionLocal()
    s.add(ReminderStat(user_id=message.from_user.id, text=text, time=date_str + " " + time_str, type="once"))
    s.commit()
    s.close()
    await message.reply("Напоминание создано")

@dp.callback_query(lambda c: c.data == "menu_list")
async def menu_list(cb: CallbackQuery):
    items = [(i, r) for i, r in enumerate(reminders) if r and r["user_id"] == cb.from_user.id]
    if not items:
        await cb.message.edit_text("У тебя нет напоминаний", reply_markup=back_kb())
        return await cb.answer()
    text = ""
    kb = InlineKeyboardBuilder()
    for i, (idx, r) in enumerate(items, start=1):
        text += f"{i}. {r['time']} — {r['text']}\n"
        kb.button(text=f"Изменить {i}", callback_data=f"edit|{idx}")
        kb.button(text=f"Удалить {i}", callback_data=f"del|{idx}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(2)
    await cb.message.edit_text("Твои напоминания:\n\n" + text, reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit|"))
async def edit_menu(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    user_temp[cb.from_user.id] = {"index": idx, "mode": None}
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить время", callback_data=f"edit_time|{idx}")
    kb.button(text="Изменить текст", callback_data=f"edit_text|{idx}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Что изменить?", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_time|"))
async def edit_time(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    user_temp[cb.from_user.id] = {"index": idx, "mode": "time"}
    await cb.message.edit_text("Введите новое время (HH:MM)", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_text|"))
async def edit_text(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    user_temp[cb.from_user.id] = {"index": idx, "mode": "text"}
    await cb.message.edit_text("Введите новый текст", reply_markup=back_kb())
    await cb.answer()

@dp.message()
async def edit_handler(msg: types.Message):
    uid = msg.from_user.id
    if uid not in user_temp:
        return
    data = user_temp[uid]
    idx = data["index"]
    if data["mode"] == "time":
        try:
            tm = datetime.strptime(msg.text, "%H:%M").time()
        except:
            return await msg.reply("Неверный формат времени")
        job = reminders[idx]["job"]
        if job:
            job.remove()
        if reminders[idx]["type"] == "daily":
            job = sched.add_job(reminder_trigger, "cron", hour=tm.hour, minute=tm.minute, args=[uid, reminders[idx]["text"], idx])
        else:
            now = datetime.now()
            dt = datetime.combine(now.date(), tm)
            if dt <= now:
                dt += timedelta(days=1)
            job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[uid, reminders[idx]["text"], idx])
        reminders[idx]["time"] = msg.text
        reminders[idx]["job"] = job
        user_temp.pop(uid)
        await msg.reply("Время обновлено")
    elif data["mode"] == "text":
        reminders[idx]["text"] = msg.text
        user_temp.pop(uid)
        await msg.reply("Текст обновлён")

@dp.callback_query(lambda c: c.data.startswith("del|"))
async def delete_rem(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    if reminders[idx] and reminders[idx]["job"]:
        try:
            reminders[idx]["job"].remove()
        except:
            pass
    reminders[idx] = None
    await cb.message.edit_text("Удалено", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_stats")
async def menu_stats(cb: CallbackQuery):
    s = SessionLocal()
    rows = s.query(ReminderStat).filter_by(user_id=cb.from_user.id).all()
    s.close()
    if not rows:
        await cb.message.edit_text("Статистика пуста", reply_markup=back_kb())
        return await cb.answer()
    text = ""
    for r in rows:
        text += f"{r.text} — создано {r.created_at}"
        if r.triggered_at:
            text += f", выполнено {r.triggered_at}"
        text += "\n"
    await cb.message.edit_text(text, reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_history")
async def menu_hist(cb: CallbackQuery):
    uid = cb.from_user.id
    items = reminder_history.get(uid, [])
    if not items:
        await cb.message.edit_text("История пустая", reply_markup=back_kb())
        return await cb.answer()
    text = "\n".join(f"{it['time'].strftime('%d.%m %H:%M')} — {it['status']}" for it in items)
    await cb.message.edit_text(text, reply_markup=back_kb())
    await cb.answer()

async def main():
    sched.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
