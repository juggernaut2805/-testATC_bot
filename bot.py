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

FILE_NAME = "ТЕСТЫ.docx"

QUESTIONS_COUNT = 30
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
# ЧИСТКА ТЕКСТА
# =========================================================

def clean(text):
    text = text.replace("\xa0", " ")
    text = text.replace("\r", "\n")

    lines = []

    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            lines.append(line)

    return "\n".join(lines).strip()


def one_line(text):
    return re.sub(
        r"\s+",
        " ",
        text
    ).strip()


def esc(text):
    return html.escape(str(text))


# =========================================================
# ЧИТАЕМ DOCX
# =========================================================

def read_document():

    if not os.path.exists(FILE_NAME):
        raise Exception(
            f"Файл {FILE_NAME} не найден"
        )

    doc = Document(FILE_NAME)

    parts = []

    # Все обычные абзацы
    for paragraph in doc.paragraphs:

        if paragraph.text.strip():
            parts.append(
                paragraph.text
            )

    # На случай таблиц
    for table in doc.tables:

        for row in table.rows:

            for cell in row.cells:

                for paragraph in cell.paragraphs:

                    if paragraph.text.strip():
                        parts.append(
                            paragraph.text
                        )

    return "\n".join(parts)


# =========================================================
# РАЗБОР ДОКУМЕНТА
# =========================================================

def parse_document():

    text = read_document()

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Убираем пустые строки
    text = re.sub(
        r"\n[ \t]*\n+",
        "\n",
        text
    )


    subjects = {}


    # ---------------------------------------------------------
    # ИЩЕМ ПРЕДМЕТЫ
    #
    # Тест: ВКРУз, ПИВП.
    # Тест: Правила полетов...
    # ---------------------------------------------------------

    subject_pattern = re.compile(
        r"(?im)^\s*Тест\s*:\s*(.+?)\s*$"
    )

    subject_matches = list(
        subject_pattern.finditer(text)
    )


    print(
        "Найдено предметов:",
        len(subject_matches)
    )


    for index, subject_match in enumerate(
        subject_matches
    ):

        subject_name = one_line(
            subject_match.group(1)
        )


        start = subject_match.end()


        if index + 1 < len(subject_matches):

            end = subject_matches[
                index + 1
            ].start()

        else:

            end = len(text)


        subject_text = text[
            start:end
        ]


        questions = parse_questions(
            subject_text
        )


        subjects[subject_name] = questions


        print(
            f"ПРЕДМЕТ: {subject_name} "
            f"-> {len(questions)} вопросов"
        )


    return subjects


# =========================================================
# РАЗБОР ВОПРОСОВ
# =========================================================

def parse_questions(text):

    questions = []


    # ---------------------------------------------------------
    # Ищем:
    #
    # Задание #1
    # Задание #2
    # Задание #3
    #
    # и т.д.
    # ---------------------------------------------------------

    question_pattern = re.compile(
        r"(?im)^\s*Задание\s*#\s*(\d+)\s*$"
    )


    matches = list(
        question_pattern.finditer(text)
    )


    for index, match in enumerate(matches):

        question_number = int(
            match.group(1)
        )


        start = match.end()


        if index + 1 < len(matches):

            end = matches[
                index + 1
            ].start()

        else:

            end = len(text)


        block = text[
            start:end
        ].strip()


        question = parse_question_block(
            question_number,
            block
        )


        if question is not None:

            questions.append(
                question
            )


    return questions


# =========================================================
# РАЗБОР ОДНОГО ВОПРОСА
# =========================================================

def parse_question_block(
    question_number,
    block
):

    lines = block.split("\n")


    # ---------------------------------------------------------
    # Убираем:
    #
    # Выберите один из 3 вариантов ответа:
    # ---------------------------------------------------------

    filtered = []

    for line in lines:

        line = line.strip()

        if not line:
            continue


        if re.match(
            r"^Выберите один",
            line,
            re.IGNORECASE
        ):

            continue


        filtered.append(line)


    lines = filtered


    if not lines:
        return None


    # ---------------------------------------------------------
    # Находим первый вариант
    # ---------------------------------------------------------

    first_option = None


    for i, line in enumerate(lines):

        if re.match(
            r"^\s*\d+\)\s*[+-]?",
            line
        ):

            first_option = i
            break


    if first_option is None:
        return None


    # Всё до первого варианта = вопрос
    question_text = " ".join(
        lines[:first_option]
    )


    question_text = one_line(
        question_text
    )


    if not question_text:
        return None


    option_lines = lines[
        first_option:
    ]


    options = []


    current = None


    for line in option_lines:

        # -----------------------------------------------------
        # Вариант:
        #
        # 1) - текст
        # 2) + текст
        #
        # или:
        #
        # 1) -
        # текст
        # -----------------------------------------------------

        match = re.match(
            r"^\s*(\d+)\)\s*([+-])?\s*(.*)$",
            line
        )


        if match:

            # Сохраняем предыдущий
            if current is not None:

                save_option(
                    options,
                    current
                )


            current = {

                "number":
                    int(match.group(1)),

                "correct":
                    (
                        True
                        if match.group(2) == "+"
                        else
                        False
                        if match.group(2) == "-"
                        else None
                    ),

                "text":
                    match.group(3).strip()
            }


            continue


        # -----------------------------------------------------
        # Если отдельной строкой стоит +
        # -----------------------------------------------------

        if current is not None:

            stripped = line.strip()


            if (
                stripped == "+"
                and current["correct"] is None
            ):

                current["correct"] = True
                continue


            if (
                stripped == "-"
                and current["correct"] is None
            ):

                current["correct"] = False
                continue


            # Продолжение текста ответа
            if current["text"]:

                current["text"] += (
                    " " + stripped
                )

            else:

                current["text"] = stripped


    # Последний вариант
    if current is not None:

        save_option(
            options,
            current
        )


    # ---------------------------------------------------------
    # Проверяем
    # ---------------------------------------------------------

    if len(options) < 2:
        return None


    correct = None


    for option in options:

        if option["correct"]:

            correct = option["number"]
            break


    if correct is None:
        return None


    return {

        "number":
            question_number,

        "question":
            question_text,

        "options":
            options,

        "correct":
            correct
    }


# =========================================================
# СОХРАНЕНИЕ ВАРИАНТА
# =========================================================

def save_option(
    options,
    option
):

    text = one_line(
        option["text"]
    )


    if not text:
        return


    options.append({

        "number":
            option["number"],

        "text":
            text,

        "correct":
            bool(option["correct"])
    })


# =========================================================
# ЗАГРУЗКА
# =========================================================

TESTS = parse_document()


print("")
print("========================================")
print("ATC TEST BOT")
print("========================================")


total = 0


for subject, questions in TESTS.items():

    print(
        f"{subject}: "
        f"{len(questions)} вопросов"
    )

    total += len(questions)


print("----------------------------------------")

print(
    f"ВСЕГО: {total}"
)

print("========================================")
print("")


# =========================================================
# КНОПКИ
# =========================================================

def subject_keyboard():

    kb = InlineKeyboardBuilder()


    for i, subject in enumerate(
        TESTS.keys()
    ):

        count = len(
            TESTS[subject]
        )


        kb.button(

            text=(
                f"📚 {subject} "
                f"({count})"
            ),

            callback_data=
                f"subject:{i}"
        )


    kb.adjust(1)


    return kb.as_markup()


# =========================================================
# START
# =========================================================

@dp.message(Command("start"))
async def start(message):

    if not TESTS:

        await message.answer(
            "❌ Тесты не найдены."
        )

        return


    await message.answer(

        "✈️ <b>ATC TEST TRAINER</b>\n\n"

        "Выбери предмет:\n\n"

        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🔀 Вопросы перемешиваются\n"
        "🎲 Варианты перемешиваются\n"
        "📊 Ответы в конце\n\n"

        "Количество вопросов указано "
        "в скобках.",

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


    count = len(
        all_questions
    )


    print(
        f"Выбран предмет: "
        f"{subject} "
        f"({count})"
    )


    if count < 30:

        await callback.message.answer(

            "❌ В этом предмете "
            f"найдено <b>{count}</b> "
            "вопросов.\n\n"

            "Для теста нужно минимум "
            "<b>30</b>.",

            parse_mode="HTML"
        )

        await callback.answer()

        return


    # -----------------------------------------------------
    # 30 случайных вопросов
    # -----------------------------------------------------

    selected = random.sample(
        all_questions,
        30
    )


    test = []


    for q in selected:

        options = [
            dict(option)
            for option in q["options"]
        ]


        random.shuffle(
            options
        )


        test.append({

            "number":
                q["number"],

            "question":
                q["question"],

            "options":
                options,

            "correct":
                q["correct"]
        })


    USERS[user_id] = {

        "subject":
            subject,

        "questions":
            test,

        "current":
            0,

        "answers":
            [],

        "finished":
            False
    }


    # Старый таймер
    old_timer = TIMERS.pop(
        user_id,
        None
    )


    if old_timer:

        old_timer.cancel()


    # Новый таймер
    TIMERS[user_id] = asyncio.create_task(
        timer(user_id)
    )


    await callback.message.answer(

        f"🚀 <b>{esc(subject)}</b>\n\n"

        "Начинаем!\n\n"

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

async def timer(user_id):

    try:

        await asyncio.sleep(
            TEST_TIME
        )


        if user_id in USERS:

            await finish(
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


    if current >= 30:

        await finish(
            user_id
        )

        return


    q = user["questions"][
        current
    ]


    text = (

        f"📝 <b>Вопрос "
        f"{current + 1}/30</b>\n\n"

        f"{esc(q['question'])}"
    )


    kb = InlineKeyboardBuilder()


    for option in q["options"]:

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
async def answer(
    callback: CallbackQuery
):

    user_id = callback.from_user.id


    if user_id not in USERS:

        await callback.answer(
            "Тест завершён"
        )

        return


    user = USERS[user_id]


    if user["finished"]:

        await callback.answer(
            "Тест завершён"
        )

        return


    selected = int(
        callback.data.split(":")[1]
    )


    current = user["current"]


    q = user["questions"][
        current
    ]


    user["answers"].append({

        "number":
            q["number"],

        "question":
            q["question"],

        "selected":
            selected,

        "correct":
            q["correct"],

        "options":
            q["options"]
    })


    user["current"] += 1


    try:

        await callback.message.delete()

    except Exception:

        pass


    if user["current"] >= 30:

        await finish(
            user_id
        )

    else:

        await send_question(
            user_id
        )


    await callback.answer()


# =========================================================
# ТЕКСТ ОТВЕТА
# =========================================================

def get_option_text(
    options,
    number
):

    for option in options:

        if option["number"] == number:

            return option["text"]


    return "—"


# =========================================================
# РЕЗУЛЬТАТ
# =========================================================

async def finish(
    user_id,
    timeout=False
):

    if user_id not in USERS:
        return


    user = USERS[user_id]


    if user["finished"]:
        return


    user["finished"] = True


    timer_task = TIMERS.pop(
        user_id,
        None
    )


    if timer_task:

        timer_task.cancel()


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


    # -----------------------------------------------------
    # ОТВЕТЫ
    # -----------------------------------------------------

    result = (
        "📋 <b>ОТВЕТЫ</b>\n\n"
    )


    for i, answer in enumerate(
        answers,
        1
    ):

        correct_number = (
            answer["correct"]
        )


        correct_text = get_option_text(
            answer["options"],
            correct_number
        )


        selected_number = (
            answer["selected"]
        )


        selected_text = get_option_text(
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

            f"<b>{i}. "
            f"Вопрос №"
            f"{answer['number']}</b>\n"

            f"Правильный: "
            f"{correct_number}) "
            f"{esc(correct_text)}\n"

            f"Ваш ответ: "
            f"{selected_number}) "
            f"{esc(selected_text)} "
            f"{mark}\n\n"
        )


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
# WEBHOOK
# =========================================================

async def startup(app):

    webhook = (
        RENDER_URL.rstrip("/")
        + "/webhook"
    )


    await bot.set_webhook(
        webhook
    )


    print(
        "========================================"
    )

    print(
        "✅ BOT STARTED"
    )

    print(
        "Webhook:",
        webhook
    )

    print(
        "Предметов:",
        len(TESTS)
    )

    print(
        "Всего вопросов:",
        sum(
            len(x)
            for x in TESTS.values()
        )
    )

    print(
        "========================================"
    )


async def shutdown(app):

    try:
        await bot.delete_webhook()
    except:
        pass


    try:
        await bot.session.close()
    except:
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
# START
# =========================================================

if __name__ == "__main__":

    web.run_app(

        app,

        host="0.0.0.0",

        port=PORT
    )
