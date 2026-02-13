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
EXAM_TIME_LIMIT = 30

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

def system_prompt(uid):
    mode = user_settings.get(uid, {}).get("mode", "assistant")
    if mode == "coder":
        return "Ты программист. Пиши код без лишнего текста."
    if mode == "teacher":
        return "Ты учитель. Объясняй подробно и понятно."
    if mode == "strict":
        return "Отвечай максимально кратко."
    return "Ты полезный AI ассистент."

async def gemini(messages):
    loop = asyncio.get_running_loop()
    def call():
        return client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
    return await loop.run_in_executor(None, call)

async def send_question(m, uid):
    state = exam_state[uid]
    messages = [
        {"role": "system", "parts": [f"Создай 1 вопрос по теме {state['topic']} сложность {state['difficulty']} без ответа."]}
    ]
    r = await gemini(messages)
    state["last_question"] = r.text
    state["question_time"] = time.time()
    await m.answer(f"Вопрос {state['number']+1}/5\n\n{r.text}\n\nУ тебя 30 секунд.")

@router.message(CommandStart())
async def start(m: Message):
    uid = str(m.from_user.id)
    history.setdefault(uid, [])
    user_settings.setdefault(uid, {"mode": "assistant"})
    stats.setdefault(uid, {"messages": 0, "exams": 0, "avg_score": 0})
    await m.answer("Команды:\n/rates\n/convert\n/exam <topic>\n/mode\n/stats")

@router.message(Command("stats"))
async def stats_cmd(m: Message):
    uid = str(m.from_user.id)
    s = stats.get(uid, {"messages": 0, "exams": 0, "avg_score": 0})
    await m.answer(
        f"Сообщений: {s['messages']}\n"
        f"Экзаменов: {s['exams']}\n"
        f"Средний результат: {s['avg_score']}%"
    )

@router.message(Command("mode"))
async def mode_cmd(m: Message):
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("assistant, coder, teacher, strict")
    uid = str(m.from_user.id)
    user_settings.setdefault(uid, {})
    user_settings[uid]["mode"] = parts[1]
    save()
    await m.answer("Режим обновлен")

@router.message(Command("rates"))
async def rates_cmd(m: Message):
    rates = get_rates()
    text = (
        f"USD → RUB: {rates.get('RUB',0):.2f}\n"
        f"USD → UZS: {rates.get('UZS',0):.2f}\n"
        f"EUR → RUB: {rates.get('EUR',0)*rates.get('RUB',0):.2f}\n"
        f"GBP → RUB: {rates.get('GBP',0)*rates.get('RUB',0):.2f}"
    )
    await m.answer(text)

@router.message(Command("convert"))
async def convert_cmd(m: Message):
    parts = m.text.split()
    if len(parts) != 4:
        return await m.answer("Пример: /convert 100 usd rub")
    try:
        amount = float(parts[1])
    except:
        return await m.answer("Сумма должна быть числом")
    from_cur = parts[2].upper()
    to_cur = parts[3].upper()
    rates = get_rates()
    if from_cur not in rates or to_cur not in rates:
        return await m.answer("Валюта не найдена")
    if from_cur != "USD":
        amount = amount / rates[from_cur]
    result = amount * rates[to_cur]
    await m.answer(f"{amount:.2f} {from_cur} = {result:.2f} {to_cur}")

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
        "last_question": "",
        "question_time": 0
    }
    await m.answer("Экзамен начат")
    await send_question(m, uid)

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)
    if not flood(uid):
        return

    if uid in exam_state:
        state = exam_state[uid]
        if time.time() - state["question_time"] > EXAM_TIME_LIMIT:
            state["number"] += 1
            state["difficulty"] = max(1, state["difficulty"]-1)
            await m.answer("Время вышло")
        else:
            messages = [
                {"role": "system", "parts": ["Ответь только correct или wrong"]},
                {"role": "user", "parts": [f"Вопрос: {state['last_question']}\nОтвет: {m.text}"]}
            ]
            r = await gemini(messages)
            if "correct" in r.text.lower():
                state["correct"] += 1
                state["difficulty"] = min(5, state["difficulty"]+1)
            else:
                state["difficulty"] = max(1, state["difficulty"]-1)
            state["number"] += 1

        if state["number"] >= 5:
            percent = state["correct"]*20
            stats[uid]["exams"] += 1
            prev_avg = stats[uid]["avg_score"]
            total_exams = stats[uid]["exams"]
            stats[uid]["avg_score"] = int((prev_avg*(total_exams-1)+percent)/total_exams)
            del exam_state[uid]
            save()
            return await m.answer(f"Экзамен завершен\nРезультат: {percent}%")

        save()
        return await send_question(m, uid)

    stats[uid]["messages"] += 1

    recent_history = history.get(uid, [])[-6:]
    messages = [{"role": "system", "parts": [system_prompt(uid)]}]
    for msg in recent_history:
        messages.append({"role": "user", "parts": [msg]})
    messages.append({"role": "user", "parts": [m.text]})

    r = await gemini(messages)
    await m.answer(r.text)

    history.setdefault(uid, [])
    history[uid].append(m.text)
    history[uid].append(r.text)
    history[uid] = history[uid][-10:]
    save()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
