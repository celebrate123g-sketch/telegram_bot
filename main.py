import asyncio
import io
import json
import logging
import os
import tempfile
import time

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction, ContentType

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

whisper_model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

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
user_last_time = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "history": history,
                "user_settings": user_settings,
                "last_answer": last_answer,
                "last_prompt": last_prompt
            },
            f,
            ensure_ascii=False,
            indent=2
        )

def build_system_prompt(user_id: int, user_name: str = "") -> str:
    settings = user_settings.get(user_id, {})
    lang = settings.get("lang", "ru")
    verbose = settings.get("verbose", "short")
    mode = settings.get("mode", "normal")
    format_ = settings.get("format", "text")

    prompt = "Ты умный AI-ассистент."

    if user_name:
        prompt += f" Общайся с пользователем по имени {user_name}."

    if lang == "ru":
        prompt += " Отвечай строго на русском языке."
    else:
        prompt += " Answer strictly in English."

    if verbose == "short":
        prompt += " Отвечай кратко и по делу."
    else:
        prompt += " Отвечай подробно, с объяснениями и примерами."

    if mode == "smart":
        prompt += " Делай внутренние логические выводы и показывай только итог."
    elif mode == "teacher":
        prompt += " Объясняй максимально просто, как для новичка."
    elif mode == "creative":
        prompt += " Будь креативным, допускаются метафоры."

    if format_ == "list":
        prompt += " Форматируй ответ в виде списка."
    elif format_ == "json":
        prompt += " Ответь строго в JSON без пояснений."

    prompt += " Не повторяй вопрос пользователя."

    return prompt

async def gemini_request(messages: list) -> str:
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=messages
        )
        return response.text.strip()
    except Exception:
        logging.exception("Gemini error")
        return "Ошибка при обращении к AI"

main_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⚙ Настройки", callback_data="settings")],
    [InlineKeyboardButton(text="🧠 Режим мышления", callback_data="modes")],
    [InlineKeyboardButton(text="📐 Формат ответа", callback_data="format")],
    [InlineKeyboardButton(text="🧹 Очистить историю", callback_data="clear")]
])

settings_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton(text="🇺🇸 English", callback_data="lang_en")
    ],
    [
        InlineKeyboardButton(text="✂ Кратко", callback_data="short"),
        InlineKeyboardButton(text="📖 Подробно", callback_data="long")
    ]
])

modes_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="⚡ Обычный", callback_data="mode_normal"),
        InlineKeyboardButton(text="🧠 Умный", callback_data="mode_smart")
    ],
    [
        InlineKeyboardButton(text="🎓 Учитель", callback_data="mode_teacher"),
        InlineKeyboardButton(text="🎭 Креатив", callback_data="mode_creative")
    ]
])

format_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="📝 Текст", callback_data="fmt_text"),
        InlineKeyboardButton(text="📋 Список", callback_data="fmt_list"),
        InlineKeyboardButton(text="🔢 JSON", callback_data="fmt_json")
    ]
])

answer_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔁 Перегенерировать", callback_data="regen")],
    [InlineKeyboardButton(text="🔊 Ответить голосом", callback_data="voice")]
])

@router.message(CommandStart())
async def start(message: Message):
    uid = message.from_user.id
    history.setdefault(uid, [])
    user_settings.setdefault(uid, {
        "lang": "ru",
        "verbose": "short",
        "mode": "normal",
        "format": "text"
    })

    await message.answer(
        "Привет! Я AI-бот на Gemini\nПиши текстом, голосом или отправляй файлы",
        reply_markup=main_keyboard
    )

@router.message(F.text == "/settings")
async def settings_cmd(message: Message):
    await message.answer("Настройки:", reply_markup=settings_keyboard)

@router.message(F.text == "/mode")
async def mode_cmd(message: Message):
    await message.answer("Режим мышления:", reply_markup=modes_keyboard)

@router.message(F.text == "/format")
async def format_cmd(message: Message):
    await message.answer("Формат ответа:", reply_markup=format_keyboard)

@router.message(F.text == "/clear")
async def clear_cmd(message: Message):
    history.pop(message.from_user.id, None)
    save_data()
    await message.answer("История очищена")

@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery):
    await callback.message.answer("Настройки:", reply_markup=settings_keyboard)
    await callback.answer()

@router.callback_query(F.data == "modes")
async def modes(callback: CallbackQuery):
    await callback.message.answer("Режим мышления:", reply_markup=modes_keyboard)
    await callback.answer()

@router.callback_query(F.data == "format")
async def choose_format(callback: CallbackQuery):
    await callback.message.answer("Формат ответа:", reply_markup=format_keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("lang_") | F.data.in_({"short", "long"}))
async def set_settings(callback: CallbackQuery):
    uid = callback.from_user.id
    user_settings.setdefault(uid, {})

    if callback.data.startswith("lang"):
        user_settings[uid]["lang"] = callback.data.split("_")[1]
    else:
        user_settings[uid]["verbose"] = callback.data

    save_data()
    await callback.message.answer("Настройки сохранены", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("mode_"))
async def set_mode(callback: CallbackQuery):
    uid = callback.from_user.id
    user_settings.setdefault(uid, {})["mode"] = callback.data.replace("mode_", "")
    save_data()
    await callback.message.answer("Режим изменён", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("fmt_"))
async def set_format(callback: CallbackQuery):
    uid = callback.from_user.id
    user_settings.setdefault(uid, {})["format"] = callback.data.replace("fmt_", "")
    save_data()
    await callback.message.answer("Формат сохранён", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data == "clear")
async def clear(callback: CallbackQuery):
    history.pop(callback.from_user.id, None)
    save_data()
    await callback.message.answer("История очищена")
    await callback.answer()

@router.callback_query(F.data == "regen")
async def regenerate(callback: CallbackQuery):
    uid = callback.from_user.id
    prompt = last_prompt.get(uid)

    if not prompt:
        await callback.answer("Нечего перегенерировать", show_alert=True)
        return

    system = build_system_prompt(uid, callback.from_user.first_name)

    regen_prompt = f"Ответь иначе на вопрос:\n{prompt}"

    answer = await gemini_request([system, regen_prompt])

    last_answer[uid] = answer
    save_data()

    await callback.message.answer(answer, reply_markup=answer_keyboard)
    await callback.answer()

@router.callback_query(F.data == "voice")
async def answer_voice(callback: CallbackQuery):
    uid = callback.from_user.id
    text = last_answer.get(uid)

    if not text:
        await callback.answer("Нет текста", show_alert=True)
        return

    lang = user_settings.get(uid, {}).get("lang", "ru")
    tts = gTTS(text=text[:500], lang=lang)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
        tts.save(f.name)
        audio = FSInputFile(f.name)

    await callback.message.answer_voice(audio)
    os.remove(f.name)
    await callback.answer()

@router.message(F.text)
async def text_handler(message: Message):
    uid = message.from_user.id

    if time.time() - user_last_time.get(uid, 0) < 1:
        return
    user_last_time[uid] = time.time()

    logging.info(f"USER {uid}: {message.text}")

    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    history.setdefault(uid, [])
    history[uid].append({"role": "user", "parts": [message.text]})
    history[uid] = history[uid][-MAX_HISTORY:]

    system = build_system_prompt(uid, message.from_user.first_name)
    answer = await gemini_request([system] + history[uid])

    history[uid].append({"role": "model", "parts": [answer]})

    last_prompt[uid] = message.text
    last_answer[uid] = answer
    save_data()

    logging.info(f"BOT {uid}: {answer[:200]}")

    await message.answer(answer, reply_markup=answer_keyboard)

@router.message(F.voice)
async def voice_handler(message: Message):
    file = await bot.get_file(message.voice.file_id)
    data = await bot.download_file(file.file_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as f:
        f.write(data.read())
        path = f.name

    segments, _ = whisper_model.transcribe(path, language="ru")
    os.remove(path)

    text = "".join(segment.text for segment in segments).strip()

    if not text:
        await message.answer("Не удалось распознать речь")
        return

    await message.answer(f"Распознано:\n{text}")
    message.text = text
    await text_handler(message)

@router.message(F.content_type == ContentType.DOCUMENT)
async def document_handler(message: Message):
    file = await bot.get_file(message.document.file_id)
    data = await bot.download_file(file.file_path)

    text = ""
    if message.document.mime_type == "application/pdf":
        with pdfplumber.open(io.BytesIO(data.read())) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    else:
        text = data.read().decode("utf-8", errors="ignore")

    text = text[:15000]

    system = build_system_prompt(message.from_user.id, message.from_user.first_name)

    answer = await gemini_request([
        system,
        "Кратко объясни содержание документа",
        text
    ])

    last_answer[message.from_user.id] = answer
    save_data()

    await message.answer(answer, reply_markup=answer_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
