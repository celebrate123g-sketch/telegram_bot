import asyncio
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from google import genai
from config import BOT_TOKEN, GEMINI_API_KEY
from aiogram.enums import ChatAction


client = genai.Client(api_key=GEMINI_API_KEY)
router = Router()
history = {}
MAX_HISTORY = 10

@router.message(CommandStart())
async def start(message: Message):
    history[message.from_user.id] = []
    user = message.from_user
    name = f"@{user.username}" if user.username else user.first_name
    await message.answer(
        f"Привет, {name}. Я бот на Gemini AI. Задай любой вопрос.\n"
        f"Автор: @bbabnanz. В случае возникновения ошибки бота можете обращаться к нему."
    )

async def gemini_request(prompt: str) -> str:
    try:
        response = await client.responses.acreate(
            model="gemini-1.5",
            input=prompt
        )
        # текст из первого candidate
        if response.candidates and len(response.candidates) > 0:
            text_parts = response.candidates[0].content
            # content это список частей с типом 'output_text'
            for part in text_parts:
                if part.type == "output_text":
                    return part.text
        return "Gemini не вернул ответ."
    except Exception as e:
        return f"Gemini не вернул ответ. Ошибка: {e}"

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

    context = "\n".join(history[user_id][-MAX_HISTORY:])

    answer = await asyncio.to_thread(gemini_request, context)

    history[user_id].append(f"Бот: {answer}")
    await message.answer(answer)

@router.message(F.text == "/clear")
async def clear_history(message: Message):
    history.pop(message.from_user.id, None)
    await message.answer("История очищена.")

async def main():
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
