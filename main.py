import asyncio
import io
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction, ContentType

from google import genai
from google.genai import types

import pdfplumber

from config import BOT_TOKEN, GEMINI_API_KEY

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)

MAX_HISTORY = 10

history = {}
user_mode = {}

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
    name = message.from_user.first_name
    await message.answer(
        f"Привет, {name}\nЯ бот на Gemini AI\nЗадай вопрос или отправь файл",
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
    await callback.message.answer("История очищена", reply_markup=main_keyboard)
    await callback.answer()

@router.message(F.text)
async def text_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    user_id = message.from_user.id
    history.setdefault(user_id, [])

    history[user_id].append({
        "role": "user",
        "content": message.text
    })

    system_prompt = MODE_PROMPTS.get(user_mode.get(user_id, "chat"), DEFAULT_PROMPT)

    contents = [{"role": "system", "content": system_prompt}]
    contents.extend(history[user_id][-MAX_HISTORY:])

    answer = await gemini_text_request(contents)

    history[user_id].append({
        "role": "assistant",
        "content": answer
    })

    await message.answer(answer, reply_markup=main_keyboard)

@router.message(F.content_type == ContentType.PHOTO)
async def photo_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    data = await message.bot.download_file(file.file_path)

    answer = await asyncio.to_thread(
        gemini_image_request,
        data.read(),
        "Опиши подробно, что изображено на фото"
    )

    await message.answer(answer, reply_markup=main_keyboard)

@router.message(F.content_type == ContentType.VIDEO)
async def video_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    if message.video.file_size > 20 * 1024 * 1024:
        await message.answer("Видео слишком большое")
        return

    file = await message.bot.get_file(message.video.file_id)
    data = await message.bot.download_file(file.file_path)

    answer = await asyncio.to_thread(
        gemini_video_request,
        data.read(),
        "Опиши, что происходит в этом видео"
    )

    await message.answer(answer, reply_markup=main_keyboard)

@router.message(F.document)
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
        {"role": "system", "content": "Проанализируй документ и кратко объясни его содержание"},
        {"role": "user", "content": text}
    ]

    answer = await gemini_text_request(contents)

    await message.answer(answer, reply_markup=main_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
