import os
import re
import random
import asyncio
from datetime import datetime, timedelta

from aiohttp import web
from docx import Document

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler,
    setup_application
)


# =========================
# SETTINGS
# =========================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not RENDER_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is not set")


TEST_FILE = "ТЕСТЫ.docx"

QUESTIONS_COUNT = 30
TEST_MINUTES = 30


bot = Bot(TOKEN)
dp = Dispatcher()

TESTS = {}
users = {}


# =========================
# READ DOCX
# =========================

def read_docx(filename):
    document = Document(filename)
    return [
        p.text.strip()
        for p in document.paragraphs
        if p.text.strip()
    ]


# =========================
# PARSE TESTS
# =========================

def parse_tests(filename):

    lines = read_docx(filename)

    subjects = {}

    current_subject = None
    current_question = None
    current_option = None

    def save_option():

        nonlocal current_option

        if current_question is None:
            current_option = None
            return

        if current_option:

            text = current_option["text"].strip()

            if text:
                current_question["options"].append({
                    "number": current_option["number"],
                    "text": text,
                    "correct": current_option["correct"]
                })

                if current_option["correct"]:
                    current_question["correct"] = (
                        current_option["number"]
                    )

        current_option = None


    def save_question():

        nonlocal current_question

        save_option()

        if not current_question:
            return

        if (
            current_question["question"]
            and len(current_question["options"]) >= 2
            and current_question["correct"] is not None
        ):

            subjects.setdefault(
                current_question["subject"],
                []
            ).append(current_question)

        current_question = None


    for line in lines:

        # SUBJECT
        m = re.match(
            r"^Тест\s*:\s*(.+)",
            line,
            re.IGNORECASE
        )

        if m:

            save_question()

            current_subject = m.group(1).strip()

            subjects.setdefault(
                current_subject,
                []
            )

            continue


        # QUESTION
        m = re.match(
            r"^Задание\s*#\s*(\d+)",
            line,
            re.IGNORECASE
        )

        if m:

            save_question()

            current_question = {
                "number": int(m.group(1)),
                "subject": current_subject or "Без предмета",
                "question": "",
                "options": [],
                "correct": None
            }

            continue


        # IGNORE INSTRUCTIONS
        if re.match(
            r"^Выберите один",
            line,
            re.IGNORECASE
        ):
            continue


        # ANSWER OPTION
        m = re.match(
            r"^(\d+)\)\s*([+-])?\s*(.*)",
            line
        )

        if m and current_question:

            save_option()

            current_option = {
                "number": int(m.group(1)),
                "text": m.group(3).strip(),
                "correct": m.group(2) == "+"
            }

            continue


        # CONTINUATION
        if current_question:

            if current_option:

                if current_option["text"]:
                    current_option["text"] += " " + line
                else:
                    current_option["text"] = line

            else:

                if current_question["question"]:
                    current_question["question"] += " " + line
                else:
                    current_question["question"] = line


    save_question()

    return subjects


TESTS = parse_tests(TEST_FILE)


print("================================")
print("TEST BOT STARTED")
print("================================")

for subject, questions in TESTS.items():
    print(subject, "-", len(questions))


# =========================
# SUBJECT BUTTONS
# =========================

def subjects_keyboard():

    keyboard = InlineKeyboardBuilder()

    for i, subject in enumerate(TESTS.keys()):

        keyboard.button(
            text=subject,
            callback_data=f"subject:{i}"
        )

    keyboard.adjust(1)

    return keyboard.as_markup()


# =========================
# START
# =========================

@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        "✈️ <b>ATC TEST TRAINER</b>\n\n"
        "Выбери предмет:\n\n"
        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🎲 Вопросы перемешиваются\n"
        "📊 Результат в конце",
        parse_mode="HTML",
        reply_markup=subjects_keyboard()
    )


# =========================
# SUBJECT
# =========================

@dp.callback_query(F.data.startswith("subject:"))
async def choose_subject(callback: CallbackQuery):

    user_id = callback.from_user.id

    index = int(callback.data.split(":")[1])

    subjects = list(TESTS.keys())

    if index >= len(subjects):
        await callback.answer("Ошибка")
        return

    subject = subjects[index]

    all_questions = TESTS[subject]

    if len(all_questions) < QUESTIONS_COUNT:

        await callback.message.answer(
            f"В этом предмете только "
            f"{len(all_questions)} вопросов.\n"
            f"Нужно минимум 30."
        )

        await callback.answer()
        return


    selected = random.sample(
        all_questions,
        QUESTIONS_COUNT
    )


    questions = []

    for q in selected:

        copy = {
            "number": q["number"],
            "question": q["question"],
            "options": [dict(x) for x in q["options"]],
            "correct": q["correct"]
        }

        random.shuffle(copy["options"])

        questions.append(copy)


    users[user_id] = {
        "subject": subject,
        "questions": questions,
        "current": 0,
        "answers": [],
        "end": datetime.now()
               + timedelta(minutes=TEST_MINUTES)
    }


    await callback.message.answer(
        f"🛫 <b>{subject}</b>\n\n"
        "30 вопросов\n"
        "30 минут\n\n"
        "Начинаем!",
        parse_mode="HTML"
    )


    await send_question(user_id)

    await callback.answer()


# =========================
# SEND QUESTION
# =========================

async def send_question(user_id):

    if user_id not in users:
        return

    user = users[user_id]

    if datetime.now() >= user["end"]:
        await finish_test(user_id, True)
        return


    index = user["current"]

    if index >= QUESTIONS_COUNT:
        await finish_test(user_id, False)
        return


    q = user["questions"][index]


    remaining = (
        user["end"] - datetime.now()
    )

    seconds = max(
        0,
        int(remaining.total_seconds())
    )

    minutes = seconds // 60
    seconds %= 60


    text = (
        f"📝 <b>{index + 1}/30</b>\n"
        f"⏱ <b>{minutes:02d}:{seconds:02d}</b>\n\n"
        f"{q['question']}"
    )


    keyboard = InlineKeyboardBuilder()


    for option in q["options"]:

        keyboard.button(
            text=(
                f"{option['number']}) "
                f"{option['text']}"
            ),
            callback_data=(
                f"answer:{option['number']}"
            )
        )


    keyboard.adjust(1)


    await bot.send_message(
        user_id,
        text,
        parse_mode="HTML",
        reply_markup=keyboard.as_markup()
    )


# =========================
# ANSWER
# =========================

@dp.callback_query(F.data.startswith("answer:"))
async def answer(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id not in users:

        await callback.answer(
            "Тест завершён. /start"
        )

        return


    user = users[user_id]

    if datetime.now() >= user["end"]:

        await finish_test(user_id, True)

        await callback.answer()

        return


    selected = int(
        callback.data.split(":")[1]
    )

    q = user["questions"][
        user["current"]
    ]


    user["answers"].append({
        "question": q["question"],
        "selected": selected,
        "correct": q["correct"],
        "options": q["options"]
    })


    user["current"] += 1


    try:
        await callback.message.delete()
    except:
        pass


    if user["current"] >= QUESTIONS_COUNT:

        await finish_test(user_id, False)

    else:

        await send_question(user_id)


    await callback.answer()


# =========================
# FINISH
# =========================

async def finish_test(
    user_id,
    time_finished=False
):

    if user_id not in users:
        return


    user = users[user_id]

    answers = user["answers"]

    correct = 0

    for a in answers:

        if a["selected"] == a["correct"]:
            correct += 1


    total = len(answers)

    wrong = total - correct

    percent = (
        round(correct / total * 100)
        if total else 0
    )


    result = (
        "⏰ ВРЕМЯ ВЫШЛО!\n\n"
        if time_finished
        else "🏁 ТЕСТ ЗАВЕРШЁН!\n\n"
    )


    result += (
        f"📚 <b>{user['subject']}</b>\n\n"
        f"📝 Отвечено: {total}/30\n"
        f"✅ Правильных: {correct}\n"
        f"❌ Ошибок: {wrong}\n"
        f"📊 Результат: {percent}%\n\n"
        f"<b>ПРАВИЛЬНЫЕ ОТВЕТЫ:</b>\n"
    )


    for i, a in enumerate(answers, 1):

        correct_text = ""

        for option in a["options"]:

            if option["number"] == a["correct"]:
                correct_text = option["text"]
                break


        result += (
            f"\n<b>{i}.</b> "
            f"Правильный ответ: "
            f"{a['correct']}) "
            f"{correct_text}\n"
        )


        if a["selected"] != a["correct"]:

            result += (
                f"Ваш ответ: "
                f"{a['selected']}) ❌\n"
            )

        else:

            result += "Ваш ответ: ✅\n"


    # Telegram message limit
    while len(result) > 4000:

        cut = result.rfind(
            "\n",
            0,
            4000
        )

        if cut == -1:
            cut = 4000

        await bot.send_message(
            user_id,
            result[:cut],
            parse_mode="HTML"
        )

        result = result[cut:]


    if result:

        await bot.send_message(
            user_id,
            result,
            parse_mode="HTML"
        )


    del users[user_id]


    await bot.send_message(
        user_id,
        "🔄 Для нового теста нажми /start"
    )


# =========================
# WEBHOOK
# =========================

async def on_startup(app):

    webhook_url = (
        f"{RENDER_URL}/webhook"
    )

    await bot.set_webhook(
        webhook_url
    )

    print(
        "Webhook:",
        webhook_url
    )


async def on_shutdown(app):

    await bot.delete_webhook()

    await bot.session.close()


# =========================
# WEB SERVER
# =========================

app = web.Application()


webhook_handler = SimpleRequestHandler(
    dispatcher=dp,
    bot=bot
)

webhook_handler.register(
    app,
    path="/webhook"
)


setup_application(
    app,
    dp,
    bot=bot
)


app.on_startup.append(
    on_startup
)

app.on_cleanup.append(
    on_shutdown
)


# =========================
# RUN
# =========================

if __name__ == "__main__":

    web.run_app(
        app,
        host="0.0.0.0",
        port=PORT
    )
