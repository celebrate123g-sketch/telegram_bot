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

DEFAULT_PROMPT = "Ты Telegram-бот на Gemini AI. Отвечай кратко и понятно на русском языке."

MODE_PROMPTS = {
    "chat": DEFAULT_PROMPT,
    "code": "Ты помощник-программист. Отвечай с примерами кода и краткими объяснениями.",
    "study": "Ты объясняешь как учитель — просто, по шагам, с примерами."
}

MAX_HISTORY = 10

history = {}
user_mode = {}
last_answer = {}

main_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Режим", callback_data="settings")],
    [InlineKeyboardButton(text="Очистить историю", callback_data="clear")]
])

settings_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Обычный", callback_data="mode_chat")],
    [InlineKeyboardButton(text="Программирование", callback_data="mode_code")],
    [InlineKeyboardButton(text="Учёба", callback_data="mode_study")]
])

answer_keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Упростить", callback_data="simplify")],
    [InlineKeyboardButton(text="Исправить", callback_data="fix")],
    [InlineKeyboardButton(text="Продолжить", callback_data="continue")],
    [InlineKeyboardButton(text="Перевести", callback_data="translate")]
])

async def gemini_text_request(messages):
    try:
        contents = []

        for msg in messages:
            contents.append(
                types.Content(
                    role=msg["role"],
                    parts=[types.Part(text=msg["content"])]
                )
            )

        response = client.models.generate_content(
            model="gemini-1.5-pro",
            contents=contents
        )

        return response.text.strip()
    except Exception as e:
        logging.error(e)
        return "Ошибка при обращении к Gemini"

@router.message(CommandStart())
async def start(message: Message):
    history[message.from_user.id] = []
    user_mode[message.from_user.id] = "chat"
    await message.answer(
        "Привет. Я бот на Gemini AI.\nПиши текст или отправляй документы.",
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

    messages = [
        {"role": "system", "content": DEFAULT_PROMPT},
        {"role": "user", "content": prompts[callback.data] + "\n" + text}
    ]

    answer = await gemini_text_request(messages)
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

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[user_id][-MAX_HISTORY:])

    answer = await gemini_text_request(messages)

    history[user_id].append({"role": "assistant", "content": answer})
    last_answer[user_id] = answer

    await message.answer(answer, reply_markup=answer_keyboard)

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

    messages = [
        {"role": "system", "content": "Кратко объясни содержание документа"},
        {"role": "user", "content": text}
    ]

    answer = await gemini_text_request(messages)
    last_answer[message.from_user.id] = answer

    await message.answer(answer, reply_markup=answer_keyboard)

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
