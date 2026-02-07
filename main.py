import asyncio
import io
import json
import logging
import os
import tempfile
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ContentType

from google import genai
from faster_whisper import WhisperModel
from gtts import gTTS
import pdfplumber
from docx import Document

from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)
whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

MAX_HISTORY = 10
MAX_TEXT_LEN = 6000
DATA_FILE = "bot_data.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

history = data.get("history", {})
user_settings = data.get("user_settings", {})
user_memory = data.get("user_memory", {})
last_answer = data.get("last_answer", {})
stats = data.get("stats", {})
last_prompt = {}
user_last_time = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "history": history,
                "user_settings": user_settings,
                "user_memory": user_memory,
                "last_answer": last_answer,
                "stats": stats
            },
            f,
            ensure_ascii=False,
            indent=2
        )

def check_flood(uid, delay=2.0):
    now = time.time()
    if now - user_last_time.get(uid, 0) < delay:
        return False
    user_last_time[uid] = now
    return True

def detect_lang(text):
    ru = sum("а" <= c <= "я" or "А" <= c <= "Я" for c in text)
    en = sum("a" <= c.lower() <= "z" for c in text)
    return "ru" if ru >= en else "en"

def build_system_prompt(uid, name=""):
    s = user_settings.get(str(uid), {})
    m = user_memory.get(str(uid), {})
    lang = s.get("lang", "ru")
    verbose = s.get("verbose", "short")
    mode = s.get("mode", "normal")
    model = s.get("model", "flash")

    p = "Ты умный AI-ассистент."
    if name:
        p += f" Пользователя зовут {name}."
    if m:
        p += " Факты о пользователе:"
        for k, v in m.items():
            p += f" {k}: {v}."
    p += " Отвечай строго на русском." if lang == "ru" else " Answer strictly in English."
    p += " Кратко и по делу." if verbose == "short" else " Подробно и с примерами."

    if mode == "smart":
        p += " Сначала сделай анализ, потом вывод."
    elif mode == "teacher":
        p += " Объясняй максимально просто."
    elif mode == "creative":
        p += " Будь креативным."

    p += " Не повторяй вопрос."
    return p

async def gemini_request(messages, uid):
    model = user_settings.get(str(uid), {}).get("model", "flash")
    model_name = "gemini-1.5-pro" if model == "pro" else "gemini-1.5-flash"
    try:
        r = client.models.generate_content(model=model_name, contents=messages)
        return r.text.strip()
    except Exception:
        return "Ошибка AI"

def split_text(text, size=4000):
    return [text[i:i + size] for i in range(0, len(text), size)]

async def summarize(system, text, uid):
    chunks = split_text(text)
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(await gemini_request([system, f"Часть {i}:\n{c}"], uid))
    return await gemini_request([system, "Сделай итоговое резюме:\n" + "\n".join(parts)], uid)

answer_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔁 Перегенерировать", callback_data="regen")]]
)

@router.message(CommandStart())
async def start(message: Message):
    uid = str(message.from_user.id)
    history.setdefault(uid, [])
    stats.setdefault(uid, {"messages": 0, "files": 0, "voice": 0})
    user_settings.setdefault(uid, {"lang": "ru", "verbose": "short", "mode": "normal", "model": "flash"})
    user_memory.setdefault(uid, {})
    await message.answer("Привет. Я могу запоминать факты о тебе и использовать их в ответах.\nПримеры:\nзови меня Алекс\nя люблю программирование\nя живу в Ташкенте\n/model flash или /model pro")

@router.message(F.text.startswith("/model"))
async def set_model(message: Message):
    uid = str(message.from_user.id)
    model = message.text.replace("/model", "").strip()
    if model not in ("flash", "pro"):
        return await message.answer("Используй /model flash или /model pro")
    user_settings.setdefault(uid, {})
    user_settings[uid]["model"] = model
    save_data()
    await message.answer(f"Модель установлена: {model}")

@router.message(F.text.regexp(r"^(зови меня|меня зовут) "))
async def set_name(message: Message):
    uid = str(message.from_user.id)
    name = message.text.split(" ", 2)[-1]
    user_memory.setdefault(uid, {})
    user_memory[uid]["имя"] = name
    save_data()
    await message.answer(f"Хорошо, буду звать тебя {name}")

@router.message(F.text.regexp(r"^я люблю "))
async def set_love(message: Message):
    uid = str(message.from_user.id)
    val = message.text.replace("я люблю", "").strip()
    user_memory.setdefault(uid, {})
    user_memory[uid]["любит"] = val
    save_data()
    await message.answer("Запомнил")

@router.message(F.text.regexp(r"^я живу "))
async def set_live(message: Message):
    uid = str(message.from_user.id)
    val = message.text.replace("я живу", "").strip()
    user_memory.setdefault(uid, {})
    user_memory[uid]["место жительства"] = val
    save_data()
    await message.answer("Запомнил")

@router.message(F.text)
async def text_handler(message: Message):
    uid = message.from_user.id
    uid_s = str(uid)

    if not check_flood(uid):
        return

    if len(message.text) > MAX_TEXT_LEN:
        return await message.answer("Слишком длинный текст")

    stats.setdefault(uid_s, {"messages": 0, "files": 0, "voice": 0})
    stats[uid_s]["messages"] += 1

    user_settings.setdefault(uid_s, {"lang": "ru", "verbose": "short", "mode": "normal", "model": "flash"})
    user_settings[uid_s]["lang"] = detect_lang(message.text)

    system = build_system_prompt(uid, message.from_user.first_name)
    messages = [system] + history.get(uid_s, []) + [message.text]
    last_prompt[uid_s] = messages

    answer = await gemini_request(messages, uid)

    history.setdefault(uid_s, []).extend([message.text, answer])
    history[uid_s] = history[uid_s][-MAX_HISTORY:]

    last_answer[uid_s] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.callback_query(F.data == "regen")
async def regen(call: CallbackQuery):
    uid_s = str(call.from_user.id)
    if uid_s not in last_prompt:
        return await call.answer("Нечего перегенерировать", show_alert=True)
    answer = await gemini_request(last_prompt[uid_s], call.from_user.id)
    last_answer[uid_s] = answer
    save_data()
    await call.message.answer(answer, reply_markup=answer_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
