import asyncio
from datetime import datetime, timedelta, time as dtime
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

TOKEN = ""

bot = Bot(token=TOKEN)
dp = Dispatcher()
sched = AsyncIOScheduler()

engine = create_engine("sqlite:///reminders.db", echo=False)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine)

CATEGORIES = ["Учеба", "Спорт", "Здоровье", "Дом", "Работа", "Другое"]
PRIORITIES = ["Низкая", "Средняя", "Высокая"]

class Reminder(Base):
    __tablename__ = "reminders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    text = Column(Text)
    datetime = Column(DateTime, nullable=True)
    type = Column(String, default="once")
    days = Column(String, nullable=True)
    category = Column(String, default="Другое")
    priority = Column(String, default="Средняя")
    created_at = Column(DateTime, default=datetime.utcnow)
    triggered_at = Column(DateTime, nullable=True)

class History(Base):
    __tablename__ = "history"
    id = Column(Integer, primary_key=True)
    reminder_id = Column(Integer)
    user_id = Column(Integer)
    action = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)

def main_menu_markup() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Поставить напоминание (по времени)", callback_data="menu_at")
    kb.button(text="Ежедневное (HH:MM)", callback_data="menu_atd")
    kb.button(text="По дате (on)", callback_data="menu_on")
    kb.button(text="Еженедельно (weekly)", callback_data="menu_weekly")
    kb.button(text="По дате: показать", callback_data="menu_date")
    kb.button(text="Список", callback_data="menu_list")
    kb.button(text="История", callback_data="menu_history")
    kb.button(text="Статистика", callback_data="menu_stats")
    kb.adjust(1)
    return kb.as_markup()

def back_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

def edit_menu_markup(rid: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Изменить время", callback_data=f"edit_time|{rid}")
    kb.button(text="Изменить текст", callback_data=f"edit_text|{rid}")
    kb.button(text="Изменить тип", callback_data=f"edit_type|{rid}")
    kb.button(text="Изменить важность", callback_data=f"edit_prio|{rid}")
    kb.button(text="Изменить категорию", callback_data=f"edit_cat|{rid}")
    kb.button(text="Удалить", callback_data=f"del|{rid}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    return kb.as_markup()

def day_name_to_cron(day_code: str) -> str:
    mapping = {
        "mon": "mon",
        "tue": "tue",
        "wed": "wed",
        "thu": "thu",
        "fri": "fri",
        "sat": "sat",
        "sun": "sun"
    }
    return mapping.get(day_code, "")

async def send_reminder(reminder_id: int):
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=reminder_id).first()
        if not r:
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Выполнено", callback_data=f"done|{r.id}")],
            [InlineKeyboardButton(text="Не выполнено", callback_data=f"missed|{r.id}")],
            [InlineKeyboardButton(text="Отложить 10 мин", callback_data=f"snooze|{r.id}|10")]
        ])
        await bot.send_message(r.user_id, f"Напоминание: {r.text}\nВажность: {r.priority}\nКатегория: {r.category}", reply_markup=keyboard)
        r.triggered_at = datetime.utcnow()
        session.add(History(reminder_id=r.id, user_id=r.user_id, action="triggered"))
        session.commit()
    finally:
        session.close()

def schedule_db_reminder(r: Reminder):
    if r.type == "once" and r.datetime:
        trigger = DateTrigger(run_date=r.datetime)
        sched.add_job(lambda rid=r.id: asyncio.create_task(send_reminder(rid)), trigger=trigger, id=f"rem_{r.id}")
    elif r.type == "daily" and r.datetime:
        hh = r.datetime.hour
        mm = r.datetime.minute
        sched.add_job(lambda rid=r.id: asyncio.create_task(send_reminder(rid)), CronTrigger(hour=hh, minute=mm), id=f"rem_{r.id}")
    elif r.type == "weekly" and r.days and r.datetime:
        hh = r.datetime.hour
        mm = r.datetime.minute
        days = r.days
        day_of_week = ",".join(days.split(","))
        sched.add_job(lambda rid=r.id: asyncio.create_task(send_reminder(rid)), CronTrigger(day_of_week=day_of_week, hour=hh, minute=mm), id=f"rem_{r.id}")

def load_and_schedule_all():
    session = SessionLocal()
    try:
        rows = session.query(Reminder).all()
        for r in rows:
            try:
                if sched.get_job(f"rem_{r.id}"):
                    continue
                schedule_db_reminder(r)
            except Exception:
                pass
    finally:
        session.close()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user = message.from_user
    name = f"@{user.username}" if user.username else user.first_name
    await message.answer(f"Привет, {name}! Меню:", reply_markup=main_menu_markup())

@dp.callback_query(lambda c: c.data == "go_back")
async def cb_go_back(cb: CallbackQuery):
    await cb.message.edit_text("Главное меню:", reply_markup=main_menu_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_list")
async def cb_list(cb: CallbackQuery):
    session = SessionLocal()
    try:
        rows = session.query(Reminder).filter_by(user_id=cb.from_user.id).order_by(Reminder.id).all()
        if not rows:
            await cb.message.edit_text("У тебя нет сохранённых напоминаний.", reply_markup=back_kb())
            await cb.answer()
            return
        text = "Твои напоминания:\n\n"
        for r in rows:
            dt = r.datetime.strftime("%Y-%m-%d %H:%M") if r.datetime else "-"
            text += f"{r.id}. [{r.type}] {dt} — {r.text} (категория: {r.category}, важность: {r.priority})\n"
        await cb.message.edit_text(text, reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data == "menu_date")
async def cb_menu_date(cb: CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="date_today")
    kb.button(text="Завтра", callback_data="date_tomorrow")
    kb.button(text="Выбрать дату", callback_data="date_pick")
    kb.button(text="Все", callback_data="date_all")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Выберите период:", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data == "date_today")
async def cb_date_today(cb: CallbackQuery):
    session = SessionLocal()
    try:
        user_id = cb.from_user.id
        today = datetime.now().date()
        start = datetime.combine(today, dtime.min)
        end = datetime.combine(today, dtime.max)
        rows = session.query(Reminder).filter(Reminder.user_id==user_id, Reminder.datetime>=start, Reminder.datetime<=end).all()
        if not rows:
            await cb.message.edit_text("На сегодня напоминаний нет.", reply_markup=back_kb())
            await cb.answer()
            return
        text = "Напоминания на сегодня:\n\n"
        for r in rows:
            text += f"- {r.datetime.strftime('%H:%M')} — {r.text} (id:{r.id})\n"
        await cb.message.edit_text(text, reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data == "date_tomorrow")
async def cb_date_tomorrow(cb: CallbackQuery):
    session = SessionLocal()
    try:
        user_id = cb.from_user.id
        tomorrow = (datetime.now() + timedelta(days=1)).date()
        start = datetime.combine(tomorrow, dtime.min)
        end = datetime.combine(tomorrow, dtime.max)
        rows = session.query(Reminder).filter(Reminder.user_id==user_id, Reminder.datetime>=start, Reminder.datetime<=end).all()
        if not rows:
            await cb.message.edit_text("На завтра напоминаний нет.", reply_markup=back_kb())
            await cb.answer()
            return
        text = "Напоминания на завтра:\n\n"
        for r in rows:
            text += f"- {r.datetime.strftime('%H:%M')} — {r.text} (id:{r.id})\n"
        await cb.message.edit_text(text, reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

user_temp = {}

@dp.callback_query(lambda c: c.data == "date_pick")
async def cb_date_pick(cb: CallbackQuery):
    user_temp[cb.from_user.id] = {"mode":"pick_date"}
    await cb.message.edit_text("Введи дату в формате YYYY-MM-DD:", reply_markup=back_kb())
    await cb.answer()

@dp.message()
async def catch_general(msg: types.Message):
    uid = msg.from_user.id
    if uid in user_temp:
        temp = user_temp[uid]
        mode = temp.get("mode")
        if mode == "pick_date":
            try:
                sel = datetime.strptime(msg.text.strip(), "%Y-%m-%d").date()
            except ValueError:
                await msg.reply("Неверный формат. Пример: 2025-02-14")
                return
            session = SessionLocal()
            try:
                start = datetime.combine(sel, dtime.min)
                end = datetime.combine(sel, dtime.max)
                rows = session.query(Reminder).filter(Reminder.user_id==uid, Reminder.datetime>=start, Reminder.datetime<=end).all()
                if not rows:
                    await msg.reply("На эту дату напоминаний нет.", reply_markup=back_kb())
                else:
                    text = f"Напоминания на {sel.strftime('%d.%m.%Y')}:\n\n"
                    for r in rows:
                        text += f"- {r.datetime.strftime('%H:%M')} — {r.text} (id:{r.id})\n"
                    await msg.reply(text, reply_markup=back_kb())
            finally:
                session.close()
            user_temp.pop(uid, None)
            return
    if msg.text.startswith("/at "):
        parts = msg.text.split(" ",2)
        if len(parts) < 3:
            await msg.reply("Используй: /at HH:MM текст")
            return
        timestr, text = parts[1], parts[2]
        try:
            tm = datetime.strptime(timestr, "%H:%M").time()
        except ValueError:
            await msg.reply("Неверный формат времени")
            return
        now = datetime.now()
        dt = datetime.combine(now.date(), tm)
        if dt <= now:
            dt += timedelta(days=1)
        session = SessionLocal()
        try:
            r = Reminder(user_id=msg.from_user.id, text=text, datetime=dt, type="once")
            session.add(r)
            session.commit()
            schedule_db_reminder(r)
            await msg.reply(f"Напоминание создано на {dt.strftime('%Y-%m-%d %H:%M')} (id:{r.id})")
        finally:
            session.close()
        return
    if msg.text.startswith("/atd "):
        parts = msg.text.split(" ",2)
        if len(parts) < 3:
            await msg.reply("Используй: /atd HH:MM текст")
            return
        timestr, text = parts[1], parts[2]
        try:
            tm = datetime.strptime(timestr, "%H:%M").time()
        except ValueError:
            await msg.reply("Неверный формат времени")
            return
        session = SessionLocal()
        try:
            today = datetime.now()
            dt = datetime.combine(today.date(), tm)
            r = Reminder(user_id=msg.from_user.id, text=text, datetime=dt, type="daily")
            session.add(r)
            session.commit()
            schedule_db_reminder(r)
            await msg.reply(f"Ежедневное напоминание установлено на {timestr} (id:{r.id})")
        finally:
            session.close()
        return
    if msg.text.startswith("/on "):
        parts = msg.text.split(" ",3)
        if len(parts) < 4:
            await msg.reply("Используй: /on YYYY-MM-DD HH:MM текст")
            return
        date_str, time_str, text = parts[1], parts[2], parts[3]
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            await msg.reply("Неверный формат")
            return
        if dt <= datetime.now():
            await msg.reply("Дата уже прошла")
            return
        session = SessionLocal()
        try:
            r = Reminder(user_id=msg.from_user.id, text=text, datetime=dt, type="once")
            session.add(r)
            session.commit()
            schedule_db_reminder(r)
            await msg.reply(f"Напоминание создано на {dt.strftime('%Y-%m-%d %H:%M')} (id:{r.id})")
        finally:
            session.close()
        return
    if msg.text.startswith("/weekly "):
        parts = msg.text.split(" ",3)
        if len(parts) < 4:
            await msg.reply("Используй: /weekly mon,tue 18:30 текст")
            return
        days_raw, timestr, text = parts[1], parts[2], parts[3]
        days_clean = []
        for d in days_raw.split(","):
            d = d.strip().lower()
            if d in ["mon","tue","wed","thu","fri","sat","sun"]:
                days_clean.append(d)
        if not days_clean:
            await msg.reply("Дни неверны. Используй: mon,tue,...")
            return
        try:
            tm = datetime.strptime(timestr, "%H:%M").time()
        except ValueError:
            await msg.reply("Неверный формат времени")
            return
        today = datetime.now()
        dt = datetime.combine(today.date(), tm)
        session = SessionLocal()
        try:
            r = Reminder(user_id=msg.from_user.id, text=text, datetime=dt, type="weekly", days=",".join(days_clean))
            session.add(r)
            session.commit()
            schedule_db_reminder(r)
            await msg.reply(f"Еженедельное напоминание создано: дни {','.join(days_clean)} в {timestr} (id:{r.id})")
        finally:
            session.close()
        return

@dp.callback_query(lambda c: c.data.startswith("edit|"))
async def cb_edit(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Напоминание не найдено", show_alert=True)
            return
        await cb.message.edit_text(f"Редактирование напоминания {r.id}:\n{r.text}", reply_markup=edit_menu_markup(r.id))
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_time|"))
async def cb_edit_time(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    user_temp[cb.from_user.id] = {"mode":"edit_time","rid":rid}
    await cb.message.edit_text("Введи новое время в формате YYYY-MM-DD HH:MM или HH:MM (для ежедневных/еженедельных):", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_text|"))
async def cb_edit_text(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    user_temp[cb.from_user.id] = {"mode":"edit_text","rid":rid}
    await cb.message.edit_text("Введи новый текст:", reply_markup=back_kb())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_type|"))
async def cb_edit_type(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    kb = InlineKeyboardBuilder()
    kb.button(text="Разовое", callback_data=f"set_type|once|{rid}")
    kb.button(text="Ежедневное", callback_data=f"set_type|daily|{rid}")
    kb.button(text="Еженедельно", callback_data=f"set_type|weekly|{rid}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Выберите тип:", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("set_type|"))
async def cb_set_type(cb: CallbackQuery):
    parts = cb.data.split("|")
    new_type, rid = parts[1], int(parts[2])
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Не найдено", show_alert=True)
            return
        if sched.get_job(f"rem_{r.id}"):
            try:
                sched.remove_job(f"rem_{r.id}")
            except Exception:
                pass
        r.type = new_type
        if new_type == "daily":
            if r.datetime is None:
                r.datetime = datetime.now()
        if new_type == "weekly":
            if r.days is None:
                r.days = "mon"
        session.commit()
        schedule_db_reminder(r)
        await cb.message.edit_text(f"Тип изменён на {new_type}", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_prio|"))
async def cb_edit_prio(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    kb = InlineKeyboardBuilder()
    kb.button(text="Низкая", callback_data=f"set_prio|Низкая|{rid}")
    kb.button(text="Средняя", callback_data=f"set_prio|Средняя|{rid}")
    kb.button(text="Высокая", callback_data=f"set_prio|Высокая|{rid}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Выберите важность:", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("set_prio|"))
async def cb_set_prio(cb: CallbackQuery):
    _, prio, rid = cb.data.split("|")
    rid = int(rid)
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Не найдено", show_alert=True)
            return
        r.priority = prio
        session.commit()
        await cb.message.edit_text(f"Важность изменена на: {prio}", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("edit_cat|"))
async def cb_edit_cat(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    kb = InlineKeyboardBuilder()
    for cat in CATEGORIES:
        kb.button(text=cat, callback_data=f"set_cat|{cat}|{rid}")
    kb.button(text="Назад", callback_data="go_back")
    kb.adjust(1)
    await cb.message.edit_text("Выберите категорию:", reply_markup=kb.as_markup())
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("set_cat|"))
async def cb_set_cat(cb: CallbackQuery):
    _, cat, rid = cb.data.split("|",2)
    rid = int(rid)
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Не найдено", show_alert=True)
            return
        r.category = cat
        session.commit()
        await cb.message.edit_text(f"Категория установлена: {cat}", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("del|"))
async def cb_del(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Не найдено", show_alert=True)
            return
        if sched.get_job(f"rem_{r.id}"):
            try:
                sched.remove_job(f"rem_{r.id}")
            except Exception:
                pass
        session.delete(r)
        session.commit()
        await cb.message.edit_text("Напоминание удалено", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("done|"))
async def cb_done(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if r:
            session.add(History(reminder_id=r.id, user_id=r.user_id, action="done"))
            session.commit()
        await cb.message.edit_text("Отмечено как выполненное", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("missed|"))
async def cb_missed(cb: CallbackQuery):
    rid = int(cb.data.split("|",1)[1])
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if r:
            session.add(History(reminder_id=r.id, user_id=r.user_id, action="missed"))
            session.commit()
        await cb.message.edit_text("Отмечено как не выполнено", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.callback_query(lambda c: c.data.startswith("snooze|"))
async def cb_snooze(cb: CallbackQuery):
    parts = cb.data.split("|")
    rid = int(parts[1])
    minutes = int(parts[2]) if len(parts) > 2 else 10
    session = SessionLocal()
    try:
        r = session.query(Reminder).filter_by(id=rid, user_id=cb.from_user.id).first()
        if not r:
            await cb.answer("Не найдено", show_alert=True)
            return
        new_dt = datetime.utcnow() + timedelta(minutes=minutes)
        r.datetime = new_dt
        r.type = "once"
        session.commit()
        if sched.get_job(f"rem_{r.id}"):
            try:
                sched.remove_job(f"rem_{r.id}")
            except Exception:
                pass
        schedule_db_reminder(r)
        session.add(History(reminder_id=r.id, user_id=r.user_id, action=f"snooze_{minutes}"))
        session.commit()
        await cb.message.edit_text(f"Отложено на {minutes} минут", reply_markup=back_kb())
    finally:
        session.close()
    await cb.answer()

@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    session = SessionLocal()
    try:
        rows = session.query(History).filter_by(user_id=message.from_user.id).order_by(History.created_at.desc()).limit(50).all()
        if not rows:
            await message.reply("История пуста")
            return
        text = "История действий:\n\n"
        for h in rows:
            text += f"- {h.created_at.strftime('%Y-%m-%d %H:%M')} — {h.action} (rem_id:{h.reminder_id})\n"
        await message.reply(text)
    finally:
        session.close()

async def startup():
    load_and_schedule_all()
    sched.start()

async def shutdown():
    await bot.session.close()
    sched.shutdown(wait=False)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(startup())
    try:
        asyncio.run(dp.start_polling(bot))
    except (KeyboardInterrupt, SystemExit):
        asyncio.run(shutdown())
