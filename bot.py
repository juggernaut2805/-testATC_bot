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
# ЧТЕНИЕ DOCX
# =========================================================

def parse_docx():

    if not os.path.exists(FILE_NAME):
        raise Exception(
            f"Файл не найден: {FILE_NAME}"
        )

    doc = Document(FILE_NAME)

    lines = []

    # -----------------------------------------------------
    # Читаем обычные абзацы
    # -----------------------------------------------------

    for paragraph in doc.paragraphs:

        text = paragraph.text.strip()

        if text:
            lines.append(text)


    # -----------------------------------------------------
    # На всякий случай читаем также таблицы
    # -----------------------------------------------------

    for table in doc.tables:

        for row in table.rows:

            row_text = []

            for cell in row.cells:

                cell_text = clean(
                    cell.text
                )

                if cell_text:
                    row_text.append(
                        cell_text
                    )

            if row_text:

                lines.append(
                    " ".join(row_text)
                )


    subjects = {}

    current_subject = None
    current_question = None
    current_option = None


    # =====================================================
    # СОХРАНИТЬ ВАРИАНТ
    # =====================================================

    def save_option():

        nonlocal current_option

        if current_option is None:
            return

        if current_question is None:

            current_option = None
            return


        text = clean(
            current_option["text"]
        )


        if not text:

            current_option = None
            return


        current_question["options"].append({

            "number":
                current_option["number"],

            "text":
                text,

            "correct":
                current_option["correct"]
        })


        current_option = None


    # =====================================================
    # СОХРАНИТЬ ВОПРОС
    # =====================================================

    def save_question():

        nonlocal current_question

        save_option()


        if current_question is None:
            return


        if current_subject is None:

            current_question = None
            return


        options = current_question["options"]


        correct = None


        for option in options:

            if option["correct"]:

                correct = option["number"]
                break


        # Нормальный вопрос
        if (
            current_question["question"]
            and len(options) >= 2
            and correct is not None
        ):

            subjects.setdefault(
                current_subject,
                []
            )


            subjects[
                current_subject
            ].append({

                "number":
                    current_question["number"],

                "question":
                    current_question["question"],

                "options":
                    options,

                "correct":
                    correct
            })


        current_question = None


    # =====================================================
    # РАЗБИРАЕМ ДОКУМЕНТ
    # =====================================================

    for raw in lines:

        line = clean(raw)


        if not line:
            continue


        # -------------------------------------------------
        # ПРЕДМЕТ
        #
        # Тест: ВКРУз, ПИВП.
        # -------------------------------------------------

        match = re.match(
            r"^\s*Тест\s*:\s*(.+?)\s*$",
            line,
            re.IGNORECASE
        )


        if match:

            save_question()


            current_subject = clean(
                match.group(1)
            )


            subjects.setdefault(
                current_subject,
                []
            )


            continue


        # -------------------------------------------------
        # ВОПРОС
        #
        # Задание #1
        # Задание #2
        # -------------------------------------------------

        match = re.match(
            r"^\s*Задание\s*#\s*(\d+)\s*$",
            line,
            re.IGNORECASE
        )


        if match:

            save_question()


            current_question = {

                "number":
                    int(match.group(1)),

                "question":
                    "",

                "options":
                    [],

                "correct":
                    None
            }


            current_option = None

            continue


        # -------------------------------------------------
        # СЛУЖЕБНЫЕ СТРОКИ
        # -------------------------------------------------

        if line.lower().startswith(
            "тестируемый:"
        ):

            continue


        if line.lower().startswith(
            "выберите один"
        ):

            continue


        # -------------------------------------------------
        # ВАРИАНТ ОТВЕТА
        #
        # 1) - текст
        # 2) + текст
        #
        # или:
        #
        # 1) -
        # текст
        # -------------------------------------------------

        option_match = re.match(
            r"^\s*(\d+)\)\s*([+-])?\s*(.*)$",
            line
        )


        if (
            option_match
            and current_question is not None
        ):

            save_option()


            sign = option_match.group(2)


            if sign == "+":

                correct = True

            else:

                correct = False


            current_option = {

                "number":
                    int(
                        option_match.group(1)
                    ),

                "text":
                    option_match.group(3).strip(),

                "correct":
                    correct
            }


            continue


        # -------------------------------------------------
        # ОТДЕЛЬНОЕ ЗНАЧЕНИЕ +
        #
        # Иногда файл может выглядеть:
        #
        # 2)
        # +
        # текст
        # -------------------------------------------------

        if (
            line == "+"
            and current_option is not None
        ):

            current_option["correct"] = True

            continue


        # -------------------------------------------------
        # ОТДЕЛЬНОЕ ЗНАЧЕНИЕ -
        # -------------------------------------------------

        if (
            line == "-"
            and current_option is not None
        ):

            current_option["correct"] = False

            continue


        # -------------------------------------------------
        # ПРОДОЛЖЕНИЕ ТЕКСТА ВАРИАНТА
        # -------------------------------------------------

        if current_option is not None:

            if current_option["text"]:

                current_option["text"] += (
                    " " + line
                )

            else:

                current_option["text"] = line


            continue


        # -------------------------------------------------
        # ТЕКСТ ВОПРОСА
        # -------------------------------------------------

        if current_question is not None:

            if current_question["question"]:

                current_question["question"] += (
                    " " + line
                )

            else:

                current_question["question"] = line


    # =====================================================
    # СОХРАНЯЕМ ПОСЛЕДНИЙ ВОПРОС
    # =====================================================

    save_question()


    # =====================================================
    # ВЫВОД В LOGS
    # =====================================================

    print("")
    print("========================================")
    print("📚 РЕЗУЛЬТАТ ЧТЕНИЯ ТЕСТОВ")
    print("========================================")


    total = 0


    for subject, questions in subjects.items():

        print(
            f"📖 {subject} -> "
            f"{len(questions)} вопросов"
        )


        total += len(questions)


    print("----------------------------------------")


    print(
        f"📊 ВСЕГО: {total} вопросов"
    )


    print("========================================")
    print("")


    return subjects


# =========================================================
# ЗАГРУЖАЕМ ФАЙЛ
# =========================================================

TESTS = parse_docx()


# =========================================================
# КНОПКИ ПРЕДМЕТОВ
# =========================================================

def subject_keyboard():

    kb = InlineKeyboardBuilder()


    for i, (
        subject,
        questions
    ) in enumerate(
        TESTS.items()
    ):

        kb.button(

            text=(
                f"📚 {subject} "
                f"({len(questions)})"
            ),

            callback_data=
                f"subject:{i}"
        )


    kb.adjust(1)


    return kb.as_markup()


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start(message):

    if not TESTS:

        await message.answer(
            "❌ В файле не найдено тестов."
        )

        return


    await message.answer(

        "✈️ <b>ATC TEST TRAINER</b>\n\n"

        "Выбери предмет:\n\n"

        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🔀 Вопросы перемешиваются\n"
        "🎲 Варианты перемешиваются\n"
        "📊 Ответы показываются в конце.",

        parse_mode="HTML",

        reply_markup=
            subject_keyboard()
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


    all_questions = TESTS[
        subject
    ]


    print(
        f"Пользователь выбрал: "
        f"{subject} "
        f"({len(all_questions)})"
    )


    # -----------------------------------------------------
    # Нужно минимум 30
    # -----------------------------------------------------

    if len(all_questions) < 30:

        await callback.message.answer(

            "❌ В этом предмете найдено "
            f"<b>{len(all_questions)}</b> вопросов.\n\n"

            "Нужно минимум "
            "<b>30</b>.",

            parse_mode="HTML"
        )


        await callback.answer()

        return


    # -----------------------------------------------------
    # Выбираем 30 случайных вопросов
    # -----------------------------------------------------

    selected = random.sample(
        all_questions,
        30
    )


    test_questions = []


    for question in selected:

        options = [
            dict(option)
            for option
            in question["options"]
        ]


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


    # -----------------------------------------------------
    # Старый таймер
    # -----------------------------------------------------

    old_timer = TIMERS.pop(
        user_id,
        None
    )


    if old_timer:

        old_timer.cancel()


    # -----------------------------------------------------
    # Новый таймер
    # -----------------------------------------------------

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
# ОТПРАВИТЬ ВОПРОС
# =========================================================

async def send_question(
    user_id
):

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
# ОТВЕТ ПОЛЬЗОВАТЕЛЯ
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
            "Тест завершён."
        )

        return


    user = USERS[user_id]


    if user["finished"]:

        await callback.answer(
            "Тест завершён."
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
# ПОЛУЧИТЬ ТЕКСТ ОТВЕТА
# =========================================================

def option_text(
    options,
    number
):

    for option in options:

        if option["number"] == number:

            return option["text"]


    return "—"


# =========================================================
# ЗАВЕРШЕНИЕ ТЕСТА
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

        title = (
            "⏰ <b>ВРЕМЯ ВЫШЛО!</b>"
        )

    else:

        title = (
            "🏁 <b>ТЕСТ ЗАВЕРШЁН!</b>"
        )


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


    # =====================================================
    # ОТВЕТЫ
    # =====================================================

    result = (
        "📋 <b>ПРАВИЛЬНЫЕ ОТВЕТЫ</b>\n\n"
    )


    for i, answer in enumerate(
        answers,
        1
    ):

        correct_number = (
            answer["correct"]
        )


        selected_number = (
            answer["selected"]
        )


        correct_text = option_text(
            answer["options"],
            correct_number
        )


        selected_text = option_text(
            answer["options"],
            selected_number
        )


        if (
            selected_number
            == correct_number
        ):

            mark = "✅"

        else:

            mark = "❌"


        block = (

            f"<b>{i}. Вопрос "
            f"№{answer['number']}</b>\n"

            f"Правильный: "
            f"<b>{correct_number})</b> "
            f"{esc(correct_text)}\n"

            f"Ваш ответ: "
            f"<b>{selected_number})</b> "
            f"{esc(selected_text)} "
            f"{mark}\n\n"
        )


        # Telegram ограничивает длину сообщения

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

        "🔄 Новый тест — нажми /start"
    )


    USERS.pop(
        user_id,
        None
    )


# =========================================================
# RENDER WEBHOOK
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
    print("========================================")
    print("🚀 ATC TEST BOT ЗАПУЩЕН")
    print("========================================")


    for subject, questions in TESTS.items():

        print(
            f"📚 {subject}: "
            f"{len(questions)}"
        )


    print("----------------------------------------")


    print(
        "📊 ВСЕГО:",
        sum(
            len(q)
            for q in TESTS.values()
        )
    )


    print(
        "🌐 WEBHOOK:",
        webhook_url
    )


    print("========================================")


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
