import asyncio
import logging
import os
import time
import re
import json
import aiosqlite

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command

from google import genai

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

DATABASE = "bot.db"
FLOOD_DELAY = 1.5
DAILY_XP = 20
MAX_HISTORY = 10
MAX_DAILY_MSG_XP = 100

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

client = genai.Client(api_key=GEMINI_API_KEY)

db = None
gemini_semaphore = asyncio.Semaphore(3)

user_last_time = {}
history = {}
exam_state = {}

async def init_db():
    global db
    db = await aiosqlite.connect(DATABASE)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            xp INTEGER,
            level INTEGER,
            messages INTEGER,
            streak INTEGER,
            max_streak INTEGER,
            correct_answers INTEGER,
            exams_passed INTEGER,
            last_daily INTEGER,
            daily_msg_xp INTEGER,
            last_msg_day INTEGER
        )
    """)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id TEXT,
            name TEXT,
            PRIMARY KEY (user_id, name)
        )
    """)
    await db.commit()

def flood(uid):
    now = time.time()
    if now - user_last_time.get(uid, 0) < FLOOD_DELAY:
        return False
    user_last_time[uid] = now
    return True

def xp_for_next_level(level):
    return int(100 * (level ** 1.5))

def calculate_level(xp):
    level = 1
    while xp >= xp_for_next_level(level):
        xp -= xp_for_next_level(level)
        level += 1
    return level

def get_rank(level):
    if level <= 3:
        return "🥉 Новичок", 1.0
    if level <= 7:
        return "🥈 Ученик", 1.05
    if level <= 12:
        return "🥇 Продвинутый", 1.1
    if level <= 20:
        return "💎 Эксперт", 1.2
    return "👑 Мастер", 1.3

async def get_user(uid):
    cur = await db.execute("SELECT * FROM users WHERE user_id=?", (uid,))
    row = await cur.fetchone()
    if not row:
        await db.execute(
            "INSERT INTO users VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (uid, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0)
        )
        await db.commit()
        return await get_user(uid)
    return row

async def update_user(uid, **kwargs):
    allowed = {
        "xp","level","messages","streak","max_streak",
        "correct_answers","exams_passed","last_daily",
        "daily_msg_xp","last_msg_day"
    }
    for k, v in kwargs.items():
        if k in allowed:
            await db.execute(f"UPDATE users SET {k}=? WHERE user_id=?", (v, uid))
    await db.commit()

async def add_xp(uid, amount):
    user = await get_user(uid)
    xp, level = user[1], user[2]
    rank_name, bonus = get_rank(level)
    amount = int(amount * bonus)
    xp += amount
    new_level = calculate_level(xp)
    await update_user(uid, xp=xp, level=new_level)
    return new_level > level, new_level, amount

async def check_daily(uid):
    user = await get_user(uid)
    today = int(time.time() // 86400)
    streak = user[4]
    max_streak = user[5]
    if user[8] != today:
        if user[8] == today - 1:
            streak += 1
        else:
            streak = 1
        max_streak = max(max_streak, streak)
        await update_user(uid, last_daily=today, streak=streak, max_streak=max_streak)
        bonus = DAILY_XP + streak * 2
        return await add_xp(uid, bonus)
    return False, user[2], 0

async def check_achievements(uid):
    user = await get_user(uid)
    achievements = []
    checks = [
        ("💬 100 сообщений", user[3] >= 100),
        ("🧠 50 правильных ответов", user[6] >= 50),
        ("🎓 5 экзаменов", user[7] >= 5),
        ("🔥 Стрик 7 дней", user[4] >= 7)
    ]
    for name, condition in checks:
        if condition:
            cur = await db.execute(
                "SELECT 1 FROM achievements WHERE user_id=? AND name=?",
                (uid, name)
            )
            exists = await cur.fetchone()
            if not exists:
                await db.execute(
                    "INSERT INTO achievements VALUES (?,?)",
                    (uid, name)
                )
                achievements.append(name)
    await db.commit()
    return achievements

async def gemini(messages):
    async with gemini_semaphore:
        loop = asyncio.get_running_loop()
        def call():
            return client.models.generate_content(
                model="gemini-1.5-flash",
                contents=messages,
                generation_config={"temperature": 0}
            )
        try:
            return await loop.run_in_executor(None, call)
        except Exception as e:
            logging.error(f"Gemini error: {e}")
            return None

@router.message(CommandStart())
async def start(m: Message):
    uid = str(m.from_user.id)
    await get_user(uid)
    level_up, lvl, bonus = await check_daily(uid)
    text = "/profile\n/top\n/exam <topic> <easy|medium|hard>"
    if bonus:
        text += f"\n🎁 Ежедневный бонус +{bonus} XP"
    if level_up:
        text += f"\n🎉 Новый уровень: {lvl}"
    await m.answer(text)

@router.message(Command("profile"))
async def profile_cmd(m: Message):
    uid = str(m.from_user.id)
    user = await get_user(uid)
    xp, level = user[1], user[2]
    rank_name, _ = get_rank(level)
    xp_needed = xp_for_next_level(level)
    temp_xp = xp
    for i in range(1, level):
        temp_xp -= xp_for_next_level(i)
    percent = int((temp_xp / xp_needed) * 100)
    bar = "█" * (percent // 10) + "░" * (10 - percent // 10)
    await m.answer(
        f"🏆 Уровень {level} ({rank_name})\nXP: {temp_xp}/{xp_needed}\n[{bar}] {percent}%\nСообщений: {user[3]}\nЭкзаменов: {user[7]}\nСтрик: {user[4]}"
    )

@router.message(Command("top"))
async def top_cmd(m: Message):
    cur = await db.execute("SELECT user_id, xp FROM users ORDER BY xp DESC LIMIT 10")
    rows = await cur.fetchall()
    text = "🏆 Топ 10\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]} — {row[1]} XP\n"
    await m.answer(text)

@router.message(Command("exam"))
async def exam_cmd(m: Message):
    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer("/exam python easy")
    uid = str(m.from_user.id)
    topic = parts[1]
    difficulty = parts[2]
    level = (await get_user(uid))[2]
    questions = 10 if level % 10 == 0 else 5
    exam_state[uid] = {
        "topic": topic,
        "difficulty": difficulty,
        "number": 0,
        "correct": 0,
        "total": questions
    }
    await m.answer("Экзамен начат")
    await send_question(uid, m)

async def send_question(uid, m):
    state = exam_state[uid]
    r = await gemini([{
        "role": "system",
        "parts": [f"Создай JSON {{\"question\":\"...\",\"answer\":\"...\"}} 1 {state['difficulty']} вопрос по теме {state['topic']}"]
    }])
    if r:
        match = re.search(r'\{.*\}', r.text, re.S)
        if match:
            data = json.loads(match.group())
            state["question"] = data["question"]
            state["answer"] = data["answer"]
            await m.answer(state["question"])

@router.message(F.text)
async def text_handler(m: Message):
    uid = str(m.from_user.id)
    if not flood(uid):
        return
    user = await get_user(uid)
    today = int(time.time() // 86400)
    daily_msg_xp = user[9]
    if user[10] != today:
        daily_msg_xp = 0
        await update_user(uid, last_msg_day=today, daily_msg_xp=0)
    await update_user(uid, messages=user[3] + 1)
    if len(m.text) > 3 and daily_msg_xp < MAX_DAILY_MSG_XP:
        level_up, lvl, gained = await add_xp(uid, 2)
        daily_msg_xp += gained
        await update_user(uid, daily_msg_xp=daily_msg_xp)
        if level_up:
            await m.answer(f"🎉 Новый уровень: {lvl}")
    if uid in exam_state:
        state = exam_state[uid]
        if m.text.strip().lower() == state["answer"].strip().lower():
            state["correct"] += 1
            user = await get_user(uid)
            await update_user(uid, correct_answers=user[6] + 1)
            level_up, lvl, gained = await add_xp(uid, 15)
            await m.answer(f"✅ Верно +{gained} XP")
            if level_up:
                await m.answer(f"🎉 Новый уровень: {lvl}")
        else:
            await m.answer(f"❌ Неверно\nПравильный ответ: {state['answer']}")
        state["number"] += 1
        if state["number"] >= state["total"]:
            percent = int(state["correct"] / state["total"] * 100)
            user = await get_user(uid)
            await update_user(uid, exams_passed=user[7] + 1)
            await add_xp(uid, 40)
            del exam_state[uid]
            await m.answer(f"Экзамен завершен: {percent}%")
            new_ach = await check_achievements(uid)
            for a in new_ach:
                await m.answer(f"🏆 Достижение получено: {a}")
            return
        await send_question(uid, m)
        return
    history.setdefault(uid, [])
    history[uid].append({"role": "user", "parts": [m.text]})
    history[uid] = history[uid][-MAX_HISTORY:]
    r = await gemini(history[uid])
    if r:
        history[uid].append({"role": "model", "parts": [r.text]})
        history[uid] = history[uid][-MAX_HISTORY:]
        await m.answer(r.text)

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
