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
from faster_whisper import WhisperModel
import pdfplumber
from docx import Document

from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

DATA_FILE = "bot_data.json"
MAX_TEXT_LEN = 6000
FLOOD_DELAY = 2.0

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

history = data.get("history", {})
summary = data.get("summary", {})
user_settings = data.get("user_settings", {})
user_memory = data.get("user_memory", {})
stats = data.get("stats", {})
learning_state = data.get("learning_state", {})
exam_state = data.get("exam_state", {})
last_prompt = {}
user_last_time = {}

courses = {
    "python": {
        "beginner": "Основы Python",
        "middle": "Функции и структуры данных",
        "advanced": "Асинхронность и ООП"
    },
    "math": {
        "beginner": "Базовая алгебра",
        "middle": "Функции и графики",
        "advanced": "Производные и интегралы"
    }
}

def save():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "history": history,
                "summary": summary,
                "user_settings": user_settings,
                "user_memory": user_memory,
                "stats": stats,
                "learning_state": learning_state,
                "exam_state": exam_state
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

def system_prompt(uid, name=""):
    mem = user_memory.get(uid, {})
    role = user_settings.get(uid, {}).get("role")

    p = "Ты умный AI-ассистент. "

    if role:
        p += f"Твоя роль: {role}. "

    if name:
        p += f"Пользователя зовут {name}. "

    if mem:
        p += "Факты о пользователе: "
        for k, v in mem.items():
            p += f"{k}: {v}. "

    if summary.get(uid):
        p += f"Контекст: {summary[uid]}. "

    p += "Отвечай кратко."
    return p

async def gemini(messages, uid, stream=False):
    model = user_settings.get(uid, {}).get("model", "flash")
    model_name = "gemini-1.5-pro" if model == "pro" else "gemini-1.5-flash"
    loop = asyncio.get_running_loop()

    def call():
        return client.models.generate_content(
            model=model_name,
            contents=messages,
            stream=stream
        )

    return await loop.run_in_executor(None, call)

async def stream_answer(message: Message, messages, uid):
    msg = await message.answer("✍️ Думаю...")
    text = ""
    response = await gemini(messages, uid, stream=True)
    for chunk in response:
        if chunk.text:
            text += chunk.text
            await msg.edit_text(text[:4096])
    return text

def get_rates():
    url = "https://open.er-api.com/v6/latest/USD"
    r = requests.get(url, timeout=10).json()
    rates = r["rates"]
    usd = 1
    rub = rates.get("RUB")
    uzs = rates.get("UZS")
    eur = rates.get("EUR")
    gbp = rates.get("GBP")
    return usd, rub, uzs, eur, gbp

main_kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Очистить", callback_data="clear")],
        [InlineKeyboardButton(text="🧠 Память", callback_data="memory")],
        [InlineKeyboardButton(text="🔁 Перегенерировать", callback_data="regen")]
    ]
)

@router.message(CommandStart())
async def start(m: Message):
    uid = str(m.from_user.id)
    history.setdefault(uid, [])
    summary.setdefault(uid, "")
    user_settings.setdefault(uid, {"model": "flash", "role": None})
    user_memory.setdefault(uid, {})
    stats.setdefault(uid, {"messages": 0})

    await m.answer(
        "🤖 AI Ассистент\n\n"
        "/rates\n"
        "/courses\n"
        "/exam",
        reply_markup=main_kb
    )

@router.message(Command("rates"))
async def rates_cmd(m: Message):
    try:
        usd, rub, uzs, eur, gbp = get_rates()
        text = (
            "💱 Курсы валют\n\n"
            f"USD → RUB: {rub:.2f}\n"
            f"USD → UZS: {uzs:.2f}\n"
            f"EUR → RUB: {eur * rub:.2f}\n"
            f"EUR → UZS: {eur * uzs:.2f}\n"
            f"GBP → RUB: {gbp * rub:.2f}\n"
            f"GBP → UZS: {gbp * uzs:.2f}"
        )
        await m.answer(text)
    except:
        await m.answer("Ошибка получения курсов")

@router.message(Command("exam"))
async def start_exam(m: Message):
    uid = str(m.from_user.id)
    exam_state[uid] = {
        "topic": "Общая тема",
        "question_number": 0,
        "correct": 0,
        "current_difficulty": 2,
        "last_question": None
    }
    save()
    await m.answer("Экзамен начат")

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)

    if not flood(uid):
        return

    messages = [
        {"role": "system", "parts": [system_prompt(uid, m.from_user.first_name)]},
        {"role": "user", "parts": [m.text]}
    ]

    answer = await stream_answer(m, messages, uid)

    history.setdefault(uid, [])
    history[uid].extend([m.text, answer])
    history[uid] = history[uid][-10:]
    save()

@router.callback_query(F.data == "clear")
async def clear_cb(c: CallbackQuery):
    uid = str(c.from_user.id)
    history[uid] = []
    summary[uid] = ""
    save()
    await c.message.edit_text("История очищена")

@router.callback_query(F.data == "memory")
async def memory_cb(c: CallbackQuery):
    uid = str(c.from_user.id)
    mem = user_memory.get(uid, {})
    if not mem:
        return await c.answer("Память пуста", show_alert=True)
    await c.message.answer("\n".join(f"{k}: {v}" for k, v in mem.items()))

@router.callback_query(F.data == "regen")
async def regen(c: CallbackQuery):
    uid = str(c.from_user.id)
    if uid not in last_prompt:
        return
    answer = await stream_answer(c.message, last_prompt[uid], uid)
    history[uid].append(answer)
    save()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
