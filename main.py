import asyncio
import json
import logging
import os
import time
import math
import requests

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

from google import genai
from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)

DATA_FILE = "bot_data.json"
FLOOD_DELAY = 1.5
RATES_CACHE_TTL = 600
DAILY_XP = 20

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

history = data.get("history", {})
user_settings = data.get("user_settings", {})
exam_state = data.get("exam_state", {})
stats = data.get("stats", {})
rates_cache = {"time": 0, "data": None}
user_last_time = {}

def save():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "history": history,
                "user_settings": user_settings,
                "exam_state": exam_state,
                "stats": stats
            },
            f,
            ensure_ascii=False,
            indent=2
        )

def flood(uid):
    now = time.time()
    if now - user_last_time.get(uid, 0) < FLOOD_DELAY:
        return False
    user_last_time[uid] = now
    return True

def xp_for_next_level(level):
    return int(100 * (level ** 1.5))

def calculate_level(xp):
    level = 1
    while xp >= xp_for_next_level(level):
        xp -= xp_for_next_level(level)
        level += 1
    return level

def progress_bar(current, total, length=10):
    percent = current / total if total else 0
    filled = int(length * percent)
    return "█" * filled + "░" * (length - filled)

def get_rank(level):
    if level <= 3:
        return "Новичок"
    if level <= 7:
        return "Ученик"
    if level <= 12:
        return "Продвинутый"
    if level <= 20:
        return "Эксперт"
    return "Мастер"

def add_xp(uid, amount):
    stats.setdefault(uid, {
        "messages": 0,
        "xp": 0,
        "level": 1,
        "streak": 0,
        "max_streak": 0,
        "correct_answers": 0,
        "exams_passed": 0,
        "last_daily": 0
    })

    old_level = stats[uid]["level"]
    stats[uid]["xp"] += amount
    new_level = calculate_level(stats[uid]["xp"])
    stats[uid]["level"] = new_level
    save()
    return new_level > old_level, new_level

def check_daily(uid):
    today = int(time.time() // 86400)
    if stats[uid]["last_daily"] != today:
        stats[uid]["last_daily"] = today
        level_up, lvl = add_xp(uid, DAILY_XP)
        return True, level_up, lvl
    return False, False, stats[uid]["level"]

def get_rates():
    now = time.time()
    if rates_cache["data"] and now - rates_cache["time"] < RATES_CACHE_TTL:
        return rates_cache["data"]
    r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
    rates_cache["data"] = r["rates"]
    rates_cache["time"] = now
    return rates_cache["data"]

async def gemini(messages):
    loop = asyncio.get_running_loop()
    def call():
        return client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
    return await loop.run_in_executor(None, call)

@router.message(CommandStart())
async def start(m: Message):
    uid = str(m.from_user.id)
    stats.setdefault(uid, {
        "messages": 0,
        "xp": 0,
        "level": 1,
        "streak": 0,
        "max_streak": 0,
        "correct_answers": 0,
        "exams_passed": 0,
        "last_daily": 0
    })

    daily, level_up, lvl = check_daily(uid)

    text = "Добро пожаловать!\n\n/rates\n/convert\n/exam <topic>\n/profile"

    if daily:
        text += f"\n\n🎁 Ежедневный бонус +{DAILY_XP} XP"
        if level_up:
            text += f"\n🎉 Новый уровень: {lvl}"

    await m.answer(text)

@router.message(Command("profile"))
async def profile_cmd(m: Message):
    uid = str(m.from_user.id)
    s = stats.get(uid)

    level = s["level"]
    xp_total = s["xp"]

    xp_needed = xp_for_next_level(level)
    xp_current = xp_total
    temp_level = 1

    while temp_level < level:
        xp_current -= xp_for_next_level(temp_level)
        temp_level += 1

    bar = progress_bar(xp_current, xp_needed)

    text = (
        f"🏆 Профиль\n\n"
        f"Уровень: {level} ({get_rank(level)})\n"
        f"XP: {xp_current}/{xp_needed}\n"
        f"{bar}\n\n"
        f"Сообщений: {s['messages']}\n"
        f"Правильных ответов: {s['correct_answers']}\n"
        f"Макс серия: {s['max_streak']}"
    )

    await m.answer(text)

@router.message(Command("exam"))
async def exam_cmd(m: Message):
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("Пример: /exam python")

    uid = str(m.from_user.id)

    exam_state[uid] = {
        "topic": parts[1],
        "number": 0,
        "correct": 0,
        "last_question": ""
    }

    await m.answer("Экзамен начат")

    r = await gemini([{
        "role": "system",
        "parts": [f"Создай 1 вопрос по теме {parts[1]} без ответа"]
    }])

    exam_state[uid]["last_question"] = r.text
    await m.answer(r.text)

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)
    if not flood(uid):
        return

    stats.setdefault(uid, {
        "messages": 0,
        "xp": 0,
        "level": 1,
        "streak": 0,
        "max_streak": 0,
        "correct_answers": 0,
        "exams_passed": 0,
        "last_daily": 0
    })

    stats[uid]["messages"] += 1
    level_up, lvl = add_xp(uid, 2)

    if level_up:
        await m.answer(f"🎉 Новый уровень: {lvl}")

    if uid in exam_state:
        state = exam_state[uid]

        r = await gemini([
            {"role": "system", "parts": ["Ответь только correct или wrong"]},
            {"role": "user", "parts": [f"Вопрос: {state['last_question']}\nОтвет: {m.text}"]}
        ])

        if "correct" in r.text.lower():
            state["correct"] += 1
            stats[uid]["correct_answers"] += 1
            stats[uid]["streak"] += 1
            stats[uid]["max_streak"] = max(stats[uid]["max_streak"], stats[uid]["streak"])

            bonus = 5 if stats[uid]["streak"] % 3 == 0 else 0
            total_xp = 15 + bonus

            level_up, lvl = add_xp(uid, total_xp)

            msg = f"✅ Верно! +{total_xp} XP"
            if bonus:
                msg += f"\n🔥 Бонус за серию!"
            if level_up:
                msg += f"\n🎉 Новый уровень: {lvl}"

            await m.answer(msg)
        else:
            stats[uid]["streak"] = 0
            await m.answer("❌ Неверно")

        state["number"] += 1

        if state["number"] >= 5:
            percent = state["correct"] * 20
            stats[uid]["exams_passed"] += 1
            add_xp(uid, 40)
            del exam_state[uid]
            return await m.answer(f"Экзамен завершен: {percent}%")

        r = await gemini([{
            "role": "system",
            "parts": [f"Создай 1 вопрос по теме {state['topic']} без ответа"]
        }])

        state["last_question"] = r.text
        return await m.answer(r.text)

    r = await gemini([
        {"role": "user", "parts": [m.text]}
    ])

    await m.answer(r.text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
