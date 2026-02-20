import asyncio
import json
import logging
import os
import time
import math
import requests
import re

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
MAX_HISTORY = 10
MAX_DAILY_MSG_XP = 100
ADMIN_ID = "YOUR_TELEGRAM_ID"

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
        return "🥉 Новичок"
    if level <= 7:
        return "🥈 Ученик"
    if level <= 12:
        return "🥇 Продвинутый"
    if level <= 20:
        return "💎 Эксперт"
    return "👑 Мастер"

def check_achievements(uid):
    s = stats[uid]
    s.setdefault("achievements", [])
    new = []

    if s["messages"] >= 100 and "Болтун" not in s["achievements"]:
        s["achievements"].append("Болтун")
        new.append("Болтун")

    if s["exams_passed"] >= 10 and "Студент" not in s["achievements"]:
        s["achievements"].append("Студент")
        new.append("Студент")

    if s["level"] >= 5 and "Растущий" not in s["achievements"]:
        s["achievements"].append("Растущий")
        new.append("Растущий")

    return new

def add_xp(uid, amount):
    stats.setdefault(uid, {
        "messages": 0,
        "xp": 0,
        "level": 1,
        "streak": 0,
        "max_streak": 0,
        "correct_answers": 0,
        "exams_passed": 0,
        "last_daily": 0,
        "daily_msg_xp": 0,
        "last_msg_day": 0,
        "achievements": []
    })

    today = int(time.time() // 86400)
    if stats[uid]["last_msg_day"] != today:
        stats[uid]["last_msg_day"] = today
        stats[uid]["daily_msg_xp"] = 0

    if stats[uid]["daily_msg_xp"] >= MAX_DAILY_MSG_XP:
        return False, stats[uid]["level"]

    stats[uid]["daily_msg_xp"] += amount

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

async def gemini(messages):
    loop = asyncio.get_running_loop()
    def call():
        return client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
    try:
        return await loop.run_in_executor(None, call)
    except:
        return None

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
        "last_daily": 0,
        "daily_msg_xp": 0,
        "last_msg_day": 0,
        "achievements": []
    })

    daily, level_up, lvl = check_daily(uid)

    text = "Добро пожаловать!\n\n/rates\n/convert\n/exam <topic>\n/profile\n/mode\n/top\n/admin_stats"

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

    sorted_users = sorted(stats.items(), key=lambda x: x[1]["xp"], reverse=True)
    position = [u[0] for u in sorted_users].index(uid) + 1

    achievements = ", ".join(s.get("achievements", [])) or "Нет"

    text = (
        f"🏆 Профиль\n\n"
        f"Место: #{position}\n"
        f"Уровень: {level} ({get_rank(level)})\n"
        f"XP: {xp_current}/{xp_needed}\n"
        f"{bar}\n\n"
        f"Сообщений: {s['messages']}\n"
        f"Правильных ответов: {s['correct_answers']}\n"
        f"Макс серия: {s['max_streak']}\n"
        f"Достижения: {achievements}"
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

    save()
    await m.answer("Экзамен начат")

    r = await gemini([{
        "role": "system",
        "parts": [f"Создай 1 вопрос по теме {parts[1]} без ответа"]
    }])

    if r:
        exam_state[uid]["last_question"] = r.text
        save()
        await m.answer(r.text)

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)

    if len(m.text) > 1000:
        return await m.answer("Слишком длинное сообщение")

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
        "last_daily": 0,
        "daily_msg_xp": 0,
        "last_msg_day": 0,
        "achievements": []
    })

    stats[uid]["messages"] += 1

    if len(m.text) > 3:
        level_up, lvl = add_xp(uid, 2)
        if level_up:
            await m.answer(f"🎉 Новый уровень: {lvl}")

    new_ach = check_achievements(uid)
    for a in new_ach:
        await m.answer(f"🏅 Новое достижение: {a}")

    if uid in exam_state:
        state = exam_state[uid]

        r = await gemini([
            {"role": "system", "parts": ["Ответь строго JSON: {\"result\":\"correct\"} или {\"result\":\"wrong\"}"]},
            {"role": "user", "parts": [f"Вопрос: {state['last_question']}\nОтвет: {m.text}"]}
        ])

        if r:
            try:
                match = re.search(r'\{.*\}', r.text, re.S)
                if match:
                    result = json.loads(match.group())
                else:
                    result = {"result": "wrong"}

                if result.get("result") == "correct":
                    state["correct"] += 1
                    stats[uid]["correct_answers"] += 1
                    stats[uid]["streak"] += 1
                    stats[uid]["max_streak"] = max(stats[uid]["max_streak"], stats[uid]["streak"])

                    bonus = 5 if stats[uid]["streak"] % 3 == 0 else 0
                    total_xp = 15 + bonus

                    level_up, lvl = add_xp(uid, total_xp)

                    msg = f"✅ Верно! +{total_xp} XP"
                    if level_up:
                        msg += f"\n🎉 Новый уровень: {lvl}"

                    await m.answer(msg)
                else:
                    stats[uid]["streak"] = 0
                    explain = await gemini([
                        {"role": "system", "parts": ["Кратко объясни почему ответ неправильный"]},
                        {"role": "user", "parts": [f"Вопрос: {state['last_question']}\nОтвет пользователя: {m.text}"]}
                    ])
                    if explain:
                        await m.answer(f"❌ Неверно\n{explain.text}")
                    else:
                        await m.answer("❌ Неверно")
            except:
                await m.answer("Ошибка проверки ответа")

        state["number"] += 1
        save()

        if state["number"] >= 5:
            percent = state["correct"] * 20
            stats[uid]["exams_passed"] += 1
            add_xp(uid, 40)
            del exam_state[uid]
            save()
            return await m.answer(f"Экзамен завершен: {percent}%")

        r = await gemini([{
            "role": "system",
            "parts": [f"Создай 1 вопрос по теме {state['topic']} без ответа"]
        }])

        if r:
            state["last_question"] = r.text
            save()
            return await m.answer(r.text)

    history.setdefault(uid, [])
    history[uid].append({"role": "user", "parts": [m.text]})
    history[uid] = history[uid][-MAX_HISTORY:]

    mode = user_settings.get(uid, "assistant")
    system_prompt = f"Ты работаешь в режиме {mode}"

    r = await gemini(
        [{"role": "system", "parts": [system_prompt]}] + history[uid]
    )

    if r:
        history[uid].append({"role": "model", "parts": [r.text]})
        history[uid] = history[uid][-MAX_HISTORY:]
        save()
        await m.answer(r.text)
    else:
        await m.answer("Ошибка AI. Попробуйте позже.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
