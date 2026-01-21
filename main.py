import asyncio
import io
import logging
import tempfile
import os

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

history = {}
user_mode = {}
last_answer = {}

DEFAULT_PROMPT = "Ты Telegram-бот на Gemini AI. Отвечай кратко и понятно на русском языке."

MODE_PROMPTS = {
    "chat": DEFAULT_PROMPT,
    "code": "Ты помощник-программист. Отвечай с примерами кода и объяснениями.",
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

def gemini_image_request(image_bytes: bytes, prompt: str) -> str:
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(image_bytes, mime_type="image/jpeg"),
                prompt
            ]
        )
        return response.text
    except Exception:
        return "Не удалось распознать изображение."

def gemini_video_request(video_bytes: bytes, prompt: str) -> str:
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(video_bytes, mime_type="video/mp4"),
                prompt
            ]
        )
        return response.text
    except Exception:
        return "Не удалось проанализировать видео."

@router.message(CommandStart())
async def start(message: Message):
    history[message.from_user.id] = []
    user_mode[message.from_user.id] = "chat"
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
    await callback.message.answer(f"Режим установлен: {mode}", reply_markup=main_keyboard)
    await callback.answer()

@router.callback_query(F.data == "clear")
async def clear_history(callback: CallbackQuery):
    history.pop(callback.from_user.id, None)
    last_answer.pop(callback.from_user.id, None)
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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
