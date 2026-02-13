import asyncio
import json
import logging
import os
import time
import requests

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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

def get_rates():
    now = time.time()
    if rates_cache["data"] and now - rates_cache["time"] < RATES_CACHE_TTL:
        return rates_cache["data"]

    r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10).json()
    rates_cache["data"] = r["rates"]
    rates_cache["time"] = now
    return rates_cache["data"]

def calculate_level(xp):
    return int((xp / 100) ** 0.5) + 1

def add_xp(uid, amount):
    stats.setdefault(uid, {"messages": 0, "xp": 0, "level": 1})
    old_level = stats[uid]["level"]
    stats[uid]["xp"] += amount
    new_level = calculate_level(stats[uid]["xp"])
    stats[uid]["level"] = new_level
    save()
    return new_level > old_level, new_level

def system_prompt(uid):
    mode = user_settings.get(uid, {}).get("mode", "assistant")
    if mode == "coder":
        return "Ты программист. Пиши код без лишнего текста."
    if mode == "teacher":
        return "Ты учитель. Объясняй подробно и понятно."
    if mode == "strict":
        return "Отвечай максимально кратко."
    return "Ты полезный AI ассистент."

async def gemini(messages, uid):
    loop = asyncio.get_running_loop()
    def call():
        return client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
    return await loop.run_in_executor(None, call)

async def send_question(m, uid):
    state = exam_state[uid]
    difficulty = state["difficulty"]

    messages = [
        {"role": "system", "parts": [f"Создай 1 вопрос по теме {state['topic']} сложность {difficulty} без ответа."]}
    ]

    r = await gemini(messages, uid)
    state["last_question"] = r.text
    await m.answer(f"Вопрос {state['number']+1}/5\n\n{r.text}")

@router.message(CommandStart())
async def start(m: Message):
    uid = str(m.from_user.id)
    history.setdefault(uid, [])
    user_settings.setdefault(uid, {"mode": "assistant"})
    stats.setdefault(uid, {"messages": 0, "xp": 0, "level": 1})
    await m.answer("Команды:\n/rates\n/convert\n/exam <topic>\n/mode")

@router.message(Command("rates"))
async def rates_cmd(m: Message):
    rates = get_rates()
    text = (
        f"USD → RUB: {rates['RUB']:.2f}\n"
        f"USD → UZS: {rates['UZS']:.2f}\n"
        f"EUR → RUB: {rates['EUR']*rates['RUB']:.2f}\n"
        f"GBP → RUB: {rates['GBP']*rates['RUB']:.2f}"
    )
    await m.answer(text)

@router.message(Command("convert"))
async def convert_cmd(m: Message):
    parts = m.text.split()
    if len(parts) != 4:
        return await m.answer("Пример: /convert 100 usd rub")
    amount = float(parts[1])
    from_cur = parts[2].upper()
    to_cur = parts[3].upper()
    rates = get_rates()
    if from_cur != "USD":
        amount = amount / rates[from_cur]
    result = amount * rates[to_cur]
    await m.answer(f"{result:.2f} {to_cur}")

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
        "difficulty": 2,
        "last_question": ""
    }
    await m.answer("Экзамен начат")
    await send_question(m, uid)

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)
    if not flood(uid):
        return

    stats.setdefault(uid, {"messages": 0, "xp": 0, "level": 1})
    stats[uid]["messages"] += 1

    if uid in exam_state:
        state = exam_state[uid]
        messages = [
            {"role": "system", "parts": ["Ответь только correct или wrong"]},
            {"role": "user", "parts": [f"Вопрос: {state['last_question']}\nОтвет: {m.text}"]}
        ]
        r = await gemini(messages, uid)

        if "correct" in r.text.lower():
            state["correct"] += 1
            level_up, lvl = add_xp(uid, 15)
            if level_up:
                await m.answer(f"🎉 Новый уровень: {lvl}")
        state["number"] += 1

        if state["number"] >= 5:
            percent = state["correct"]*20
            level_up, lvl = add_xp(uid, 40)
            del exam_state[uid]
            if level_up:
                await m.answer(f"🎉 Новый уровень: {lvl}")
            return await m.answer(f"Результат: {percent}%")

        return await send_question(m, uid)

    level_up, lvl = add_xp(uid, 2)
    if level_up:
        await m.answer(f"🎉 Новый уровень: {lvl}")

    messages = [
        {"role": "system", "parts": [system_prompt(uid)]},
        {"role": "user", "parts": [m.text]}
    ]

    r = await gemini(messages, uid)
    await m.answer(r.text)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
