import os
import re
import random
import asyncio
import html

from aiohttp import web
from docx import Document

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# =========================================================
# НАСТРОЙКИ
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_NAME = os.path.join(BASE_DIR, "ТЕСТЫ.docx")

QUESTIONS_PER_TEST = 30
TEST_TIME = 30 * 60


if not TOKEN:
    raise Exception("BOT_TOKEN не найден")

if not RENDER_URL:
    raise Exception("RENDER_EXTERNAL_URL не найден")


bot = Bot(TOKEN)
dp = Dispatcher()

TESTS = {}
USERS = {}
TIMERS = {}


# =========================================================
# НАЗВАНИЯ ПРЕДМЕТОВ
# =========================================================

SUBJECT_NAMES = [
    "ВКРУз, ПИВП.",
    "Правила полётов и основы воздушной навигации.",
    "Авиационные правила в части ОВД, РОВД.",
    "Радиотелефонная связь в ГА (АП-96).",
    "Авиационная метеорология.",
    "Радиотехнические Средства УВД.",
    "Авиапроисшествия связанные с ОВД."
]


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================

def clean(text):
    text = text.replace("\xa0", " ")
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def esc(text):
    return html.escape(str(text))


# =========================================================
# ЧТЕНИЕ WORD
# =========================================================

def parse_docx():

    if not os.path.exists(FILE_NAME):
        raise Exception(
            f"Файл не найден: {FILE_NAME}"
        )

    doc = Document(FILE_NAME)

    subjects = []

    current_subject = []
    subject_index = 0

    previous_number = None

    print("====================================")
    print("ЧТЕНИЕ ТЕСТОВ")
    print("====================================")


    for table_index, table in enumerate(doc.tables):

        if not table.rows:
            continue


        # -------------------------------------------------
        # ПЕРВАЯ СТРОКА ТАБЛИЦЫ = Задание #...
        # -------------------------------------------------

        first_text = clean(
            table.cell(0, 0).text
        )

        match = re.search(
            r"Задание\s*#\s*(\d+)",
            first_text,
            re.IGNORECASE
        )


        if not match:
            continue


        question_number = int(
            match.group(1)
        )


        # -------------------------------------------------
        # Если номер снова стал 1,
        # начинается новый предмет
        # -------------------------------------------------

        if (
            previous_number is not None
            and question_number == 1
            and current_subject
        ):

            subjects.append(
                current_subject
            )

            current_subject = []

            subject_index += 1


        previous_number = question_number


        # -------------------------------------------------
        # ВТОРАЯ СТРОКА = ВОПРОС
        # -------------------------------------------------

        if len(table.rows) < 2:
            continue


        question_text = clean(
            table.cell(1, 0).text
        )


        if not question_text:
            continue


        # -------------------------------------------------
        # ИЩЕМ ВАРИАНТЫ
        #
        # колонка 0 = номер
        # колонка 1 = + или -
        # колонка 2 = текст
        # -------------------------------------------------

        options = []


        for row in table.rows[3:]:

            if len(row.cells) < 3:
                continue


            number_text = clean(
                row.cells[0].text
            )

            sign = clean(
                row.cells[1].text
            )

            option_text = clean(
                row.cells[2].text
            )


            number_match = re.search(
                r"(\d+)",
                number_text
            )


            if not number_match:
                continue


            number = int(
                number_match.group(1)
            )


            if not option_text:
                continue


            is_correct = (
                "+" in sign
            )


            options.append({

                "number": number,

                "text": option_text,

                "correct": is_correct
            })


        # -------------------------------------------------
        # Проверяем вопрос
        # -------------------------------------------------

        if len(options) < 2:
            print(
                f"Пропущен вопрос #{question_number}: "
                f"мало вариантов"
            )
            continue


        correct_answers = [
            x for x in options
            if x["correct"]
        ]


        if len(correct_answers) != 1:

            print(
                f"Проблема #{question_number}: "
                f"правильных ответов = "
                f"{len(correct_answers)}"
            )

            continue


        current_subject.append({

            "number":
                question_number,

            "question":
                question_text,

            "options":
                options,

            "correct":
                correct_answers[0]["number"]
        })


    # Добавляем последний предмет

    if current_subject:
        subjects.append(
            current_subject
        )


    # -------------------------------------------------
    # Привязываем названия
    # -------------------------------------------------

    result = {}


    for i, questions in enumerate(subjects):

        if i < len(SUBJECT_NAMES):

            name = SUBJECT_NAMES[i]

        else:

            name = f"Предмет {i + 1}"


        result[name] = questions


    print("")
    print("====================================")
    print("РЕЗУЛЬТАТ")
    print("====================================")


    total = 0


    for name, questions in result.items():

        print(
            f"{name}: "
            f"{len(questions)} вопросов"
        )

        total += len(questions)


    print("------------------------------------")
    print(
        f"ВСЕГО ВОПРОСОВ: {total}"
    )

    print("====================================")


    return result


# =========================================================
# ЗАГРУЖАЕМ ТЕСТЫ
# =========================================================

TESTS = parse_docx()


# =========================================================
# КНОПКИ ПРЕДМЕТОВ
# =========================================================

def subject_keyboard():

    kb = InlineKeyboardBuilder()


    for i, (subject, questions) in enumerate(
        TESTS.items()
    ):

        kb.button(

            text=f"📚 {subject} ({len(questions)})",

            callback_data=f"subject:{i}"
        )


    kb.adjust(1)

    return kb.as_markup()


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start(message):

    await message.answer(

        "✈️ <b>ATC TEST TRAINER</b>\n\n"

        "Выбери предмет:\n\n"

        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🔀 Вопросы перемешиваются\n"
        "🎲 Варианты ответов перемешиваются\n"
        "📊 Результат и правильные ответы — в конце.",

        parse_mode="HTML",

        reply_markup=subject_keyboard()
    )


# =========================================================
# ВЫБОР ПРЕДМЕТА
# =========================================================

@dp.callback_query(
    F.data.startswith("subject:")
)
async def choose_subject(
    callback: CallbackQuery
):

    user_id = callback.from_user.id


    index = int(
        callback.data.split(":")[1]
    )


    subjects = list(
        TESTS.keys()
    )


    if index >= len(subjects):

        await callback.answer(
            "Ошибка"
        )

        return


    subject = subjects[index]

    questions = TESTS[subject]


    print(
        f"Выбран предмет: "
        f"{subject} "
        f"({len(questions)})"
    )


    if len(questions) < 30:

        await callback.message.answer(

            f"❌ В этом предмете найдено "
            f"<b>{len(questions)}</b> вопросов.\n\n"

            f"Нужно минимум <b>30</b>.",

            parse_mode="HTML"
        )

        await callback.answer()

        return


    # -------------------------------------------------
    # 30 случайных вопросов
    # -------------------------------------------------

    selected = random.sample(
        questions,
        QUESTIONS_PER_TEST
    )


    test_questions = []


    for question in selected:

        options = [
            dict(x)
            for x in question["options"]
        ]


        # Перемешиваем варианты

        random.shuffle(
            options
        )


        test_questions.append({

            "number":
                question["number"],

            "question":
                question["question"],

            "options":
                options,

            "correct":
                question["correct"]
        })


    USERS[user_id] = {

        "subject":
            subject,

        "questions":
            test_questions,

        "current":
            0,

        "answers":
            [],

        "finished":
            False
    }


    # Останавливаем старый таймер

    old_timer = TIMERS.pop(
        user_id,
        None
    )


    if old_timer:
        old_timer.cancel()


    # Запускаем новый

    TIMERS[user_id] = asyncio.create_task(
        test_timer(user_id)
    )


    await callback.message.answer(

        f"🚀 <b>{esc(subject)}</b>\n\n"

        "Тест начинается!\n\n"

        "📝 30 вопросов\n"
        "⏱ 30 минут\n\n"

        "Удачи! ✈️",

        parse_mode="HTML"
    )


    await send_question(
        user_id
    )


    await callback.answer()


# =========================================================
# ТАЙМЕР
# =========================================================

async def test_timer(user_id):

    try:

        await asyncio.sleep(
            TEST_TIME
        )


        if user_id in USERS:

            await finish_test(
                user_id,
                timeout=True
            )


    except asyncio.CancelledError:

        pass


# =========================================================
# ОТПРАВКА ВОПРОСА
# =========================================================

async def send_question(user_id):

    if user_id not in USERS:
        return


    user = USERS[user_id]


    if user["finished"]:
        return


    current = user["current"]


    if current >= QUESTIONS_PER_TEST:

        await finish_test(
            user_id
        )

        return


    question = user["questions"][
        current
    ]


    text = (

        f"📝 <b>Вопрос "
        f"{current + 1}/30</b>\n\n"

        f"{esc(question['question'])}"
    )


    kb = InlineKeyboardBuilder()


    for option in question["options"]:

        kb.button(

            text=(
                f"{option['number']}) "
                f"{option['text']}"
            ),

            callback_data=
                f"answer:{option['number']}"
        )


    kb.adjust(1)


    await bot.send_message(

        user_id,

        text,

        parse_mode="HTML",

        reply_markup=
            kb.as_markup()
    )


# =========================================================
# ОТВЕТ
# =========================================================

@dp.callback_query(
    F.data.startswith("answer:")
)
async def answer_question(
    callback: CallbackQuery
):

    user_id = callback.from_user.id


    if user_id not in USERS:

        await callback.answer(
            "Тест уже завершён."
        )

        return


    user = USERS[user_id]


    if user["finished"]:

        await callback.answer(
            "Тест уже завершён."
        )

        return


    selected = int(
        callback.data.split(":")[1]
    )


    current = user["current"]


    question = user["questions"][
        current
    ]


    user["answers"].append({

        "number":
            question["number"],

        "question":
            question["question"],

        "selected":
            selected,

        "correct":
            question["correct"],

        "options":
            question["options"]
    })


    user["current"] += 1


    try:

        await callback.message.delete()

    except Exception:

        pass


    if user["current"] >= 30:

        await finish_test(
            user_id
        )

    else:

        await send_question(
            user_id
        )


    await callback.answer()


# =========================================================
# ТЕКСТ ВАРИАНТА
# =========================================================

def option_text(options, number):

    for option in options:

        if option["number"] == number:

            return option["text"]


    return "—"


# =========================================================
# РЕЗУЛЬТАТ
# =========================================================

async def finish_test(
    user_id,
    timeout=False
):

    if user_id not in USERS:
        return


    user = USERS[user_id]


    if user["finished"]:
        return


    user["finished"] = True


    timer = TIMERS.pop(
        user_id,
        None
    )


    if timer:

        timer.cancel()


    answers = user["answers"]


    correct = 0


    for answer in answers:

        if (
            answer["selected"]
            == answer["correct"]
        ):

            correct += 1


    wrong = len(answers) - correct


    percent = (

        round(
            correct
            / len(answers)
            * 100
        )

        if answers

        else 0
    )


    if timeout:

        title = "⏰ <b>ВРЕМЯ ВЫШЛО!</b>"

    else:

        title = "🏁 <b>ТЕСТ ЗАВЕРШЁН!</b>"


    await bot.send_message(

        user_id,

        f"{title}\n\n"

        f"📚 {esc(user['subject'])}\n\n"

        f"📝 Отвечено: "
        f"<b>{len(answers)}/30</b>\n"

        f"✅ Правильно: "
        f"<b>{correct}</b>\n"

        f"❌ Ошибок: "
        f"<b>{wrong}</b>\n"

        f"📊 Результат: "
        f"<b>{percent}%</b>",

        parse_mode="HTML"
    )


    # -------------------------------------------------
    # ПРАВИЛЬНЫЕ ОТВЕТЫ
    # -------------------------------------------------

    result = "📋 <b>РАЗБОР ОТВЕТОВ</b>\n\n"


    for i, answer in enumerate(
        answers,
        1
    ):

        correct_number = answer["correct"]

        selected_number = answer["selected"]


        correct_text = option_text(
            answer["options"],
            correct_number
        )


        selected_text = option_text(
            answer["options"],
            selected_number
        )


        if selected_number == correct_number:

            mark = "✅"

        else:

            mark = "❌"


        block = (

            f"<b>{i}. Вопрос "
            f"№{answer['number']}</b>\n"

            f"Правильный ответ: "
            f"<b>{correct_number})</b> "
            f"{esc(correct_text)}\n"

            f"Ваш ответ: "
            f"<b>{selected_number})</b> "
            f"{esc(selected_text)} "
            f"{mark}\n\n"
        )


        # Telegram максимум около 4096 символов

        if len(result) + len(block) > 3800:

            await bot.send_message(

                user_id,

                result,

                parse_mode="HTML"
            )


            result = ""


        result += block


    if result:

        await bot.send_message(

            user_id,

            result,

            parse_mode="HTML"
        )


    await bot.send_message(

        user_id,

        "🔄 Чтобы пройти новый тест, нажми /start"
    )


    USERS.pop(
        user_id,
        None
    )


# =========================================================
# WEBHOOK
# =========================================================

async def startup(app):

    webhook_url = (
        RENDER_URL.rstrip("/")
        + "/webhook"
    )


    await bot.set_webhook(
        webhook_url
    )


    print("")
    print("====================================")
    print("✅ ATC BOT ЗАПУЩЕН")
    print("====================================")


    for subject, questions in TESTS.items():

        print(
            f"{subject}: "
            f"{len(questions)}"
        )


    print("------------------------------------")

    print(
        "Всего:",
        sum(
            len(x)
            for x in TESTS.values()
        )
    )

    print("Webhook:", webhook_url)

    print("====================================")


async def shutdown(app):

    try:
        await bot.delete_webhook()
    except Exception:
        pass


    try:
        await bot.session.close()
    except Exception:
        pass


# =========================================================
# WEB SERVER
# =========================================================

app = web.Application()


handler = SimpleRequestHandler(
    dispatcher=dp,
    bot=bot
)


handler.register(
    app,
    path="/webhook"
)


setup_application(
    app,
    dp,
    bot=bot
)


app.on_startup.append(
    startup
)

app.on_cleanup.append(
    shutdown
)


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    web.run_app(

        app,

        host="0.0.0.0",

        port=PORT
    )
