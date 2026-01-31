import asyncio
import io
import json
import logging
import os
import tempfile
import time
import random

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ContentType

from google import genai
from faster_whisper import WhisperModel
from gtts import gTTS
import pdfplumber

from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)

whisper_model = WhisperModel("base", device="cpu", compute_type="int8")

MAX_HISTORY = 10
DATA_FILE = "bot_data.json"

if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {}

history = data.get("history", {})
user_settings = data.get("user_settings", {})
last_answer = data.get("last_answer", {})
last_prompt = data.get("last_prompt", {})
stats = data.get("stats", {})
user_last_time = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "history": history,
            "user_settings": user_settings,
            "last_answer": last_answer,
            "last_prompt": last_prompt,
            "stats": stats
        }, f, ensure_ascii=False, indent=2)

def check_flood(uid: int, delay: float = 2.0) -> bool:
    now = time.time()
    if now - user_last_time.get(uid, 0) < delay:
        return False
    user_last_time[uid] = now
    return True

def detect_lang(text: str) -> str:
    ru = sum("а" <= c <= "я" or "А" <= c <= "Я" for c in text)
    en = sum("a" <= c.lower() <= "z" for c in text)
    return "ru" if ru >= en else "en"

def build_system_prompt(uid: int, name: str = "") -> str:
    s = user_settings.get(str(uid), {})
    lang = s.get("lang", "ru")
    verbose = s.get("verbose", "short")
    mode = s.get("mode", "normal")
    fmt = s.get("format", "text")

    p = "Ты умный AI-ассистент."
    if name:
        p += f" Общайся с пользователем по имени {name}."
    p += " Отвечай строго на русском." if lang == "ru" else " Answer strictly in English."
    p += " Кратко и по делу." if verbose == "short" else " Подробно, с примерами."

    if mode == "smart":
        p += " Сначала проанализируй, затем дай итог."
    elif mode == "teacher":
        p += " Объясняй как новичку, по шагам."
    elif mode == "creative":
        p += " Используй метафоры и нестандартный стиль."

    if fmt == "list":
        p += " Формат — список."
    elif fmt == "json":
        p += " Ответ строго JSON."

    p += " Не повторяй вопрос."
    return p

async def gemini_request(messages: list) -> str:
    try:
        r = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
        return r.text.strip()
    except Exception:
        return "Ошибка AI"

def split_text(text, size=4000):
    return [text[i:i+size] for i in range(0, len(text), size)]

async def summarize(system, text):
    chunks = split_text(text)
    res = []
    for i, c in enumerate(chunks, 1):
        r = await gemini_request([system, f"Часть {i}:\n{c}"])
        res.append(r)
    return await gemini_request([system, "Сделай итоговое резюме:\n" + "\n".join(res)])

answer_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔁 Перегенерировать", callback_data="regen")]
])

@router.message(CommandStart())
async def start(message: Message):
    uid = str(message.from_user.id)
    history.setdefault(uid, [])
    stats.setdefault(uid, {"messages": 0, "files": 0})
    user_settings.setdefault(uid, {
        "lang": "ru",
        "verbose": "short",
        "mode": "normal",
        "format": "text"
    })
    await message.answer("👋 Gemini AI бот\nПиши текст или отправляй файлы")

@router.message(F.text == "/stats")
async def show_stats(message: Message):
    s = stats.get(str(message.from_user.id), {})
    await message.answer(
        f"📊 Статистика\n"
        f"Сообщений: {s.get('messages',0)}\n"
        f"Файлов: {s.get('files',0)}"
    )

@router.message(F.text)
async def text_handler(message: Message):
    uid = message.from_user.id
    uid_s = str(uid)

    if not check_flood(uid):
        return

    stats.setdefault(uid_s, {"messages": 0, "files": 0})
    stats[uid_s]["messages"] += 1

    user_settings[uid_s]["lang"] = detect_lang(message.text)

    system = build_system_prompt(uid, message.from_user.first_name)
    answer = await gemini_request([system, message.text])

    last_answer[uid_s] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.message(F.content_type == ContentType.DOCUMENT)
async def document_handler(message: Message):
    uid = str(message.from_user.id)
    stats.setdefault(uid, {"messages": 0, "files": 0})
    stats[uid]["files"] += 1

    file = await bot.get_file(message.document.file_id)
    data = await bot.download_file(file.file_path)

    text = ""
    if message.document.mime_type == "application/pdf":
        with pdfplumber.open(io.BytesIO(data.read())) as pdf:
            for p in pdf.pages:
                text += p.extract_text() or ""
    else:
        text = data.read().decode("utf-8", errors="ignore")

    system = build_system_prompt(message.from_user.id, message.from_user.first_name)

    name = message.document.file_name.lower()
    if name.endswith(".py"):
        answer = await gemini_request([system, "Объясни код и найди ошибки:\n" + text])
    elif name.endswith(".json"):
        answer = await gemini_request([system, "Объясни структуру JSON:\n" + text])
    else:
        answer = await summarize(system, text)

    last_answer[uid] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.callback_query(F.data == "regen")
async def regen(call: CallbackQuery):
    uid = str(call.from_user.id)
    if uid in last_answer:
        await call.message.answer(last_answer[uid])

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
