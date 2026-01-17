import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.enums import ChatAction, ContentType
from google import genai
from google.genai import types
from config import BOT_TOKEN, GEMINI_API_KEY

bot = Bot(BOT_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)
router = Router()

history = {}
MAX_HISTORY = 10

SYSTEM_PROMPT = (
    "Ты Telegram-бот на Gemini AI. "
    "Отвечай кратко, понятно и на русском языке."
)

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Помощь", callback_data="help")],
    [InlineKeyboardButton(text="Очистить историю", callback_data="clear")]
])

@router.message(CommandStart())
async def start(message: Message):
    history[message.from_user.id] = []
    user = message.from_user
    name = f"@{user.username}" if user.username else user.first_name
    await message.answer(
        f"Привет, {name}.\n"
        "Я бот на Gemini AI. Задай любой вопрос или отправь фото / видео.",
        reply_markup=keyboard
    )

@router.message(F.text == "/help")
async def help_cmd(message: Message):
    await message.answer(
        "Доступные возможности:\n"
        "Текстовые вопросы\n"
        "Анализ изображений\n"
        "Анализ видео\n"
        "/clear — очистить историю диалога",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "help")
async def help_callback(callback: CallbackQuery):
    await callback.message.answer(
        "Доступные возможности:\n"
        "Текстовые вопросы\n"
        "Анализ изображений\n"
        "Анализ видео\n"
        "/clear — очистить историю диалога",
        reply_markup=keyboard
    )
    await callback.answer()

@router.callback_query(F.data == "clear")
async def clear_callback(callback: CallbackQuery):
    history.pop(callback.from_user.id, None)
    await callback.message.answer("История очищена.", reply_markup=keyboard)
    await callback.answer()

async def gemini_request(prompt: str) -> str:
    try:
        response = await client.responses.acreate(
            model="gemini-1.5",
            input=prompt
        )
        if response.candidates:
            for part in response.candidates[0].content:
                if part.type == "output_text":
                    return part.text
        return "Gemini не вернул ответ."
    except Exception as e:
        return f"Ошибка Gemini: {e}"

def gemini_image_request(image_bytes: bytes, prompt: str) -> str:
    try:
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
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
                types.Part.from_bytes(data=video_bytes, mime_type="video/mp4"),
                prompt
            ]
        )
        return response.text
    except Exception:
        return "Не удалось проанализировать видео."

@router.message(F.text)
async def ai_answer(message: Message):
    if len(message.text) > 3000:
        await message.answer("Сообщение слишком длинное.")
        return

    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action=ChatAction.TYPING
    )

    user_id = message.from_user.id
    history.setdefault(user_id, [])
    history[user_id].append(f"Пользователь: {message.text}")

    context = SYSTEM_PROMPT + "\n" + "\n".join(history[user_id][-MAX_HISTORY:])
    answer = await gemini_request(context)

    history[user_id].append(f"Бот: {answer}")
    await message.answer(answer, reply_markup=keyboard)

@router.message(F.content_type == ContentType.PHOTO)
async def photo_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    image_bytes = await message.bot.download_file(file.file_path)

    answer = await asyncio.to_thread(
        gemini_image_request,
        image_bytes.read(),
        "Опиши подробно, что изображено на этом фото."
    )

    await message.answer(answer, reply_markup=keyboard)

@router.message(F.content_type == ContentType.VIDEO)
async def video_handler(message: Message):
    await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)

    video = message.video
    if video.file_size > 20 * 1024 * 1024:
        await message.answer("Видео слишком большое.")
        return

    file = await message.bot.get_file(video.file_id)
    video_bytes = await message.bot.download_file(file.file_path)

    answer = await asyncio.to_thread(
        gemini_video_request,
        video_bytes.read(),
        "Опиши, что происходит в этом видео."
    )

    await message.answer(answer, reply_markup=keyboard)

@router.message(F.text == "/clear")
async def clear_cmd(message: Message):
    history.pop(message.from_user.id, None)
    await message.answer("История очищена.", reply_markup=keyboard)

async def main():
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
