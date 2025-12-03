import asyncio
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from typing_extensions import overload

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

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    text = Column(String)
    datetime = Column(DateTime)
    type = Column(String)
    category = Column(String, default="default")


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
    kb.button(text="По дате", callback_data="menu_date")
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

def date_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="date_today")
    kb.button(text="Завтра", callback_data="date_tomorrow")
    kb.button(text="Выбрать дату", callback_data="date_pick")
    kb.button(text="Все", callback_data="date_all")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

@dp.callback_query(lambda c: c.data == "date_today")
async def today_reminders(cb: CallbackQuery):
    session = SessionLocal()
    user_id = cb.from_user.id
    today = datetime.now().date()

    items = session.query(Reminder).filter(
        Reminder.user_id == user_id,
        Reminder.datetime >= datetime.combine(today, datetime.min.time()),
        Reminder.datetime <= datetime.combine(today, datetime.max.time())
    ).all()
    session.close()

    if not items:
        return await cb.message.edit_text("На сегодня нет напоминаний.", reply_markup=back_kb())

    text = "Напоминания на сегодня:\n\n"
    for r in items:
        text += f"- {r.datetime.strftime('%H:%M')} — {r.text}\n"

    await cb.message.edit_text(text, reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "date_tomorrow")
async def tomorrow_reminders(cb: CallbackQuery):
    session = SessionLocal()
    user_id = cb.from_user.id
    tomorrow = (datetime.now() + timedelta(days=1)).date()

    items = session.query(Reminder).filter(
        Reminder.user_id == user_id,
        Reminder.datetime >= datetime.combine(tomorrow, datetime.min.time()),
        Reminder.datetime <= datetime.combine(tomorrow, datetime.max.time())
    ).all()
    session.close()

    if not items:
        return await cb.message.edit_text("На завтра нет напоминаний.", reply_markup=back_kb())

    text = "Напоминания на завтра:\n\n"
    for r in items:
        text += f"- {r.datetime.strftime('%H:%M')} — {r.text}\n"

    await cb.message.edit_text(text, reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "date_pick")
async def pick_date(cb: CallbackQuery):
    user_temp[cb.from_user.id] = {"mode": "pick_date"}
    await cb.message.edit_text("Введи дату в формате YYYY-MM-DD:", reply_markup=back_kb())
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

@dp.callback_query(lambda c: c.data.startswith("edit|"))
async def edit_menu(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    user_temp[cb.from_user.id] = {"index": idx, "mode": None}
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить время", callback_data=f"edit_time|{idx}")
    kb.button(text="Изменить текст", callback_data=f"edit_text|{idx}")
    kb.button(text="Изменить тип", callback_data=f"edit_type|{idx}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Что изменить?", reply_markup=kb.as_markup())
    await cb.answer()

@dp.message()
async def edit_handler(msg: types.Message):
    user_id = msg.from_user.id
    if user_id not in user_temp:
        return
    temp = user_temp[user_id]
    idx = temp.get("index")
    if idx is None or idx >= len(reminders):
        await msg.reply("Ошибка: напоминание не найдено")
        user_temp.pop(user_id, None)
        return
    reminder = reminders[idx]
    if temp.get("mode") == "time":
        text_time = msg.text.strip()
        try:
            parsed_time = datetime.strptime(text_time, "%H:%M").time()
        except ValueError:
            await msg.reply("Неверный формат времени. Используй ЧЧ:ММ")
            return
        job = reminder.get("job")
        if job:
            try:
                job.remove()
            except Exception:
                pass
        reminder["time"] = text_time
        if reminder.get("type") == "once":
            now = datetime.now()
            dt = datetime.combine(now.date(), parsed_time)
            if dt <= now:
                dt += timedelta(days=1)
            job = sched.add_job(
                reminder_trigger,
                "date",
                run_date=dt,
                args=[reminder.get("user_id"), reminder.get("text"), idx]
            )
            reminder["job"] = job
        elif reminder.get("type") == "daily":
            job = sched.add_job(
                reminder_trigger,
                "cron",
                hour=parsed_time.hour,
                minute=parsed_time.minute,
                args=[reminder.get("user_id"), reminder.get("text"), idx]
            )
            reminder["job"] = job
        await msg.reply("Время изменено")
        user_temp.pop(user_id, None)
        return
    if temp.get("mode") == "text":
        reminder["text"] = msg.text
        await msg.reply("Текст напоминания обновлён")
        user_temp.pop(user_id, None)
        return
    if temp.get("mode") == "pick_date":
        try:
            selected_date = datetime.strptime(msg.text, "%Y-%m-%d").date()
        except ValueError:
            await msg.reply("Неверный формат даты. Пример: 2025-02-14")
            return
        reminder["date"] = str(selected_date)
        await msg.reply("Дата изменена")
        user_temp.pop(user_id, None)
        return

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

@dp.callback_query(lambda c: c.data.startswith("edit_type|"))
async def edit_type_choice(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    user_temp[cb.from_user.id] = {"index": idx, "mode": "type"}
    kb = InlineKeyboardBuilder()
    kb.button(text="Разовое", callback_data=f"set_type_once|{idx}")
    kb.button(text="Ежедневное", callback_data=f"set_type_daily|{idx}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Выберите тип напоминания:", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("set_type_once|"))
async def set_type_once(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    if idx < 0 or idx >= len(reminders) or reminders[idx] is None:
        await cb.answer("Напоминание не найдено", show_alert=True)
        return
    r = reminders[idx]
    old_job = r.get("job")
    if old_job:
        try:
            old_job.remove()
        except Exception:
            pass
    r["type"] = "once"
    tstr = r.get("time", "")
    dt = None
    try:
        if " " in tstr:
            dt = datetime.strptime(tstr, "%Y-%m-%d %H:%M")
        else:
            tm = datetime.strptime(tstr, "%H:%M").time()
            now = datetime.now()
            dt = datetime.combine(now.date(), tm)
            if dt <= now:
                dt += timedelta(days=1)
    except Exception:
        now = datetime.now()
        dt = now + timedelta(minutes=1)
    job = sched.add_job(reminder_trigger, "date", run_date=dt, args=[r["user_id"], r["text"], idx])
    r["job"] = job
    await cb.message.edit_text("Тип изменён на: разовое", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("set_type_daily|"))
async def set_type_daily(cb: CallbackQuery):
    idx = int(cb.data.split("|")[1])
    if idx < 0 or idx >= len(reminders) or reminders[idx] is None:
        await cb.answer("Напоминание не найдено", show_alert=True)
        return
    r = reminders[idx]
    old_job = r.get("job")
    if old_job:
        try:
            old_job.remove()
        except Exception:
            pass
    r["type"] = "daily"
    tstr = r.get("time", "")
    try:
        if " " in tstr:
            tpart = tstr.split(" ", 1)[1] if " " in tstr else tstr
            tm = datetime.strptime(tpart, "%H:%M").time()
        else:
            tm = datetime.strptime(tstr, "%H:%M").time()
    except Exception:
        tm = (datetime.now() + timedelta(minutes=1)).time()
    job = sched.add_job(reminder_trigger, "cron", hour=tm.hour, minute=tm.minute, args=[r["user_id"], r["text"], idx])
    r["job"] = job
    await cb.message.edit_text("Тип изменён на: ежедневное", reply_markup=back_kb())
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
