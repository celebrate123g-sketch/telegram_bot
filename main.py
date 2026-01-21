import asyncio
import io
import logging
import tempfile
import os
import json

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction, ContentType

from google import genai
from google.genai import types

import pdfplumber
import whisper

from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)
whisper_model = whisper.load_model("base")

MAX_HISTORY = 10

HISTORY_FILE = "bot_history.json"

if os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        saved_data = json.load(f)
        history = saved_data.get("history", {})
        user_mode = saved_data.get("user_mode", {})
        last_answer = saved_data.get("last_answer", {})
else:
    history = {}
    user_mode = {}
    last_answer = {}

DEFAULT_PROMPT = "Ты Telegram-бот на Gemini AI. Отвечай кратко и понятно на русском языке."

MODE_PROMPTS = {
    "chat": DEFAULT_PROMPT,
    "code": "Ты помощник-программист. Отвечай с примерами кода и краткими объяснениями.",
    "study": "Ты объясняешь как учитель — просто, по шагам, с примерами."
}

main_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⚙ Режим", callback_data="settings")],
    [InlineKeyboardButton(text="🧹 Очистить историю", callback_data="clear")]
])

settings_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="💬 Обычный", callback_data="mode_chat")],
    [InlineKeyboardButton(text="💻 Программирование", callback_data="mode_code")],
    [InlineKeyboardButton(text="📚 Учёба", callback_data="mode_study")]
])

answer_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="✏ Упростить", callback_data="simplify")],
    [InlineKeyboardButton(text="🧠 Исправить", callback_data="fix")],
    [InlineKeyboardButton(text="➡ Продолжить", callback_data="continue")],
    [InlineKeyboardButton(text="🌍 Перевести", callback_data="translate")]
])

def save_history():
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "history": history,
            "user_mode": user_mode,
            "last_answer": last_answer
        }, f, ensure_ascii=False, indent=2)

async def gemini_text_request(contents: list) -> str:
    try:
        response = await client.responses.acreate(
            model="gemini-1.5",
            input=contents
        )
        for item in response.output:
            if item["type"] == "message":
                for part in item["content"]:
                    if part["type"] == "output_text":
                        return part["text"]
        return "Gemini не вернул ответ."
    except Exception as e:
        logging.error(e)
        return "Ошибка при обращении к Gemini."

@router.message(CommandStart())
async def start(message: Message):
    history.setdefault(message.from_user.id, [])
    user_mode.setdefault(message.from_user.id, "chat")
    await message.answer(
        "Привет. Я бот на Gemini AI.\nМожешь писать, отправлять голос, фото, видео и документы.",
        reply_markup=main_keyboard
    )

@router.callback_query(F.data == "settings")
async def settings(callback: CallbackQuery):
    await callback.message.answer("Выбери режим:", reply_markup=settings_keyboard)
    await callback.answer()

@router.callback_query(F.data.startswith("mode_"))
async def set_mode(callback: CallbackQuery):
    mode = callback.data.replace("mode_", "")
    user_mode[callback.from_user.id] = mode
    save_history()
    await callback.message.answer(f"Режим установлен: {mode}", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data == "clear")
async def clear_history(callback: CallbackQuery):
    history.pop(callback.from_user.id, None)
    last_answer.pop(callback.from_user.id, None)
    save_history()
    await callback.message.answer("История очищена", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data.in_({"simplify", "fix", "continue", "translate"}))
async def answer_actions(callback: CallbackQuery):
    text = last_answer.get(callback.from_user.id)
    if not text:
        await callback.answer("Нет ответа для обработки", show_alert=True)
        return

    prompts = {
        "simplify": "Упрости этот текст:",
        "fix": "Исправь ошибки и улучши текст:",
        "continue": "Продолжи мысль:",
        "translate": "Переведи этот текст на английский:"
    }

    contents = [
        {"role": "system", "content": DEFAULT_PROMPT},
        {"role": "user", "content": f"{prompts[callback.data]}\n{text}"}
    ]

    answer = await gemini_text_request(contents)
    last_answer[callback.from_user.id] = answer
    save_history()

    await callback.message.answer(answer, reply_markup=answer_keyboard)
    await callback.answer()

@router.message(F.text)
async def text_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    user_id = message.from_user.id
    history.setdefault(user_id, [])

    history[user_id].append({"role": "user", "content": message.text})

    system_prompt = MODE_PROMPTS.get(user_mode.get(user_id, "chat"), DEFAULT_PROMPT)

    contents = [{"role": "system", "content": system_prompt}]
    contents.extend(history[user_id][-MAX_HISTORY:])

    answer = await gemini_text_request(contents)

    history[user_id].append({"role": "assistant", "content": answer})
    last_answer[user_id] = answer
    save_history()

    await message.answer(answer, reply_markup=answer_keyboard)

@router.message(F.voice)
async def voice_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    file = await message.bot.get_file(message.voice.file_id)
    data = await message.bot.download_file(file.file_path)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
        tmp.write(data.read())
        tmp_path = tmp.name

    result = whisper_model.transcribe(tmp_path, language="ru")
    os.remove(tmp_path)

    text = result["text"].strip()
    if not text:
        await message.answer("Не удалось распознать речь")
        return

    await text_handler(Message(
        message_id=message.message_id,
        from_user=message.from_user,
        chat=message.chat,
        text=text
    ))

@router.message(F.content_type == ContentType.DOCUMENT)
async def document_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    file = await message.bot.get_file(message.document.file_id)
    data = await message.bot.download_file(file.file_path)

    text = ""
    if message.document.mime_type == "application/pdf":
        with pdfplumber.open(io.BytesIO(data.read())) as pdf:
            for page in pdf.pages:
                text += page.extract_text() or ""
    else:
        text = data.read().decode("utf-8", errors="ignore")

    text = text[:15000]

    contents = [
        {"role": "system", "content": "Кратко объясни содержание документа"},
        {"role": "user", "content": text}
    ]

    answer = await gemini_text_request(contents)
    last_answer[message.from_user.id] = answer
    save_history()

    await message.answer(answer, reply_markup=answer_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
