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
last_answer = data.get("last_answer", {})
last_prompt = {}
stats = data.get("stats", {})
user_last_time = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "history": history,
                "user_settings": user_settings,
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
    lang = s.get("lang", "ru")
    verbose = s.get("verbose", "short")
    mode = s.get("mode", "normal")

    p = "Ты умный AI-ассистент."
    if name:
        p += f" Общайся с пользователем по имени {name}."
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

async def gemini_request(messages):
    try:
        r = client.models.generate_content(model="gemini-1.5-flash", contents=messages)
        return r.text.strip()
    except Exception:
        return "Ошибка AI"

def split_text(text, size=4000):
    return [text[i:i + size] for i in range(0, len(text), size)]

async def summarize(system, text):
    chunks = split_text(text)
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(await gemini_request([system, f"Часть {i}:\n{c}"]))
    return await gemini_request([system, "Сделай итоговое резюме:\n" + "\n".join(parts)])

answer_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔁 Перегенерировать", callback_data="regen")]]
)

@router.message(CommandStart())
async def start(message: Message):
    uid = str(message.from_user.id)
    history.setdefault(uid, [])
    stats.setdefault(uid, {"messages": 0, "files": 0, "voice": 0})
    user_settings.setdefault(uid, {"lang": "ru", "verbose": "short", "mode": "normal"})
    await message.answer("Привет. Пиши текстом, голосом или отправляй файлы")

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

    user_settings.setdefault(uid_s, {"lang": "ru", "verbose": "short", "mode": "normal"})
    user_settings[uid_s]["lang"] = detect_lang(message.text)

    system = build_system_prompt(uid, message.from_user.first_name)

    messages = [system] + history.get(uid_s, []) + [message.text]
    last_prompt[uid_s] = messages

    answer = await gemini_request(messages)

    history.setdefault(uid_s, []).extend([message.text, answer])
    history[uid_s] = history[uid_s][-MAX_HISTORY:]

    last_answer[uid_s] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.message(F.voice)
async def voice_handler(message: Message):
    uid_s = str(message.from_user.id)
    stats.setdefault(uid_s, {"messages": 0, "files": 0, "voice": 0})
    stats[uid_s]["voice"] += 1

    file = await bot.get_file(message.voice.file_id)
    ogg = tempfile.mktemp(".ogg")
    mp3 = tempfile.mktemp(".mp3")

    await bot.download_file(file.file_path, ogg)
    segments, _ = whisper_model.transcribe(ogg)
    text = "".join(s.text for s in segments)

    system = build_system_prompt(uid_s, message.from_user.first_name)
    answer = await gemini_request([system, text])

    gTTS(answer, lang=user_settings.get(uid_s, {}).get("lang", "ru")).save(mp3)
    last_answer[uid_s] = answer

    await message.answer_voice(open(mp3, "rb"))

    os.remove(ogg)
    os.remove(mp3)

@router.message(F.content_type == ContentType.DOCUMENT)
async def document_handler(message: Message):
    uid_s = str(message.from_user.id)
    stats.setdefault(uid_s, {"messages": 0, "files": 0, "voice": 0})
    stats[uid_s]["files"] += 1

    file = await bot.get_file(message.document.file_id)
    data = await bot.download_file(file.file_path)
    raw = data.read()
    text = ""

    if message.document.mime_type == "application/pdf":
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for p in pdf.pages:
                text += p.extract_text() or ""
    elif message.document.mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        doc = Document(io.BytesIO(raw))
        text = "\n".join(p.text for p in doc.paragraphs)
    else:
        text = raw.decode("utf-8", errors="ignore")

    if not text.strip():
        return await message.answer("Файл пуст или не читается")

    system = build_system_prompt(uid_s, message.from_user.first_name)
    answer = await summarize(system, text)

    last_answer[uid_s] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.callback_query(F.data == "regen")
async def regen(call: CallbackQuery):
    uid_s = str(call.from_user.id)
    if uid_s not in last_prompt:
        return await call.answer("Нечего перегенерировать", show_alert=True)

    answer = await gemini_request(last_prompt[uid_s])
    last_answer[uid_s] = answer
    save_data()

    await call.message.answer(answer, reply_markup=answer_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
