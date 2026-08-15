import os
import re
import random
from datetime import datetime, timedelta

from aiohttp import web
from docx import Document

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application


# ============================================================
# НАСТРОЙКИ
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", "10000"))
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")

TEST_FILE = "ТЕСТЫ.docx"

QUESTIONS_PER_TEST = 30
TEST_TIME_MINUTES = 30


if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден")

if not RENDER_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL не найден")


bot = Bot(token=TOKEN)
dp = Dispatcher()

TESTS = {}
USERS = {}


# ============================================================
# НОРМАЛИЗАЦИЯ ТЕКСТА
# ============================================================

def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ")
    text = text.replace("\r", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================
# ЧТЕНИЕ WORD
# ЧИТАЕТ И АБЗАЦЫ, И ТАБЛИЦЫ
# ============================================================

def read_docx(filename):

    document = Document(filename)

    lines = []

    # Обычные абзацы
    for paragraph in document.paragraphs:

        text = clean_text(paragraph.text)

        if text:
            lines.append(text)

    # Таблицы
    for table in document.tables:

        for row in table.rows:

            for cell in row.cells:

                for paragraph in cell.paragraphs:

                    text = clean_text(paragraph.text)

                    if text:
                        lines.append(text)

    return lines


# ============================================================
# РАЗБОР ТЕСТОВ
# ============================================================

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

        if current_option is None:
            return

        text = clean_text(
            current_option["text"]
        )

        if not text:
            current_option = None
            return

        option = {
            "number": current_option["number"],
            "text": text,
            "correct": current_option["correct"]
        }

        current_question["options"].append(option)

        if option["correct"]:
            current_question["correct"] = option["number"]

        current_option = None


    def save_question():

        nonlocal current_question

        save_option()

        if current_question is None:
            return

        question_text = clean_text(
            current_question["question"]
        )

        options = current_question["options"]

        correct = current_question["correct"]

        if (
            question_text
            and len(options) >= 2
            and correct is not None
        ):

            subject = current_question["subject"]

            subjects.setdefault(
                subject,
                []
            ).append({
                "number": current_question["number"],
                "question": question_text,
                "options": options,
                "correct": correct
            })

        current_question = None


    question_counter = 0


    for line in lines:

        # ----------------------------------------------------
        # ПРЕДМЕТ
        # ----------------------------------------------------

        subject_match = re.match(
            r"^Тест\s*:\s*(.+)$",
            line,
            re.IGNORECASE
        )

        if subject_match:

            save_question()

            current_subject = clean_text(
                subject_match.group(1)
            )

            subjects.setdefault(
                current_subject,
                []
            )

            continue


        # ----------------------------------------------------
        # СТАРЫЕ/СЛУЖЕБНЫЕ СТРОКИ
        # ----------------------------------------------------

        if line.lower().startswith("тестируемый"):
            continue

        if line.lower().startswith("выберите один"):
            continue

        if line.lower().startswith("правильный ответ"):
            continue


        # ----------------------------------------------------
        # НОВЫЙ ВОПРОС
        #
        # Поддерживает:
        #
        # Задание #1
        # Задание # 1
        # Задание №1
        # Вопрос 1
        # ----------------------------------------------------

        question_match = re.match(
            r"^(?:Задание|Вопрос)\s*[#№]?\s*(\d+)\s*[\.\:\-]?\s*(.*)$",
            line,
            re.IGNORECASE
        )

        if question_match:

            save_question()

            question_counter += 1

            number = int(
                question_match.group(1)
            )

            question_text = clean_text(
                question_match.group(2)
            )

            current_question = {
                "number": number,
                "subject": current_subject or "Без предмета",
                "question": question_text,
                "options": [],
                "correct": None
            }

            continue


        # ----------------------------------------------------
        # ВАРИАНТ ОТВЕТА
        #
        # Поддерживает:
        #
        # 1) + текст
        # 2) - текст
        # 3) текст
        # 1. + текст
        # ----------------------------------------------------

        option_match = re.match(
            r"^(\d+)[\)\.]\s*([+-])?\s*(.*)$",
            line
        )

        if (
            option_match
            and current_question is not None
        ):

            save_option()

            number = int(
                option_match.group(1)
            )

            sign = option_match.group(2)

            text = clean_text(
                option_match.group(3)
            )

            current_option = {
                "number": number,
                "text": text,
                "correct": sign == "+"
            }

            continue


        # ----------------------------------------------------
        # ЕСЛИ ЭТО ПРОДОЛЖЕНИЕ ВОПРОСА/ОТВЕТА
        # ----------------------------------------------------

        if current_question is not None:

            if current_option is not None:

                if current_option["text"]:

                    current_option["text"] += (
                        " " + line
                    )

                else:

                    current_option["text"] = line

            else:

                if current_question["question"]:

                    current_question["question"] += (
                        " " + line
                    )

                else:

                    current_question["question"] = line


    # Сохраняем последний вопрос
    save_question()

    return subjects


# ============================================================
# ЗАГРУЖАЕМ БАЗУ
# ============================================================

TESTS = parse_tests(TEST_FILE)


print("")
print("========================================")
print("        ATC TEST BOT STARTED")
print("========================================")
print("")


for subject, questions in TESTS.items():

    print(
        f"{subject}: {len(questions)} вопросов"
    )


print("")
print(
    "Всего предметов:",
    len(TESTS)
)
print("")


# ============================================================
# КНОПКИ ПРЕДМЕТОВ
# ============================================================

def subjects_keyboard():

    keyboard = InlineKeyboardBuilder()

    for index, subject in enumerate(
        TESTS.keys()
    ):

        keyboard.button(
            text=subject,
            callback_data=f"subject:{index}"
        )

    keyboard.adjust(1)

    return keyboard.as_markup()


# ============================================================
# /START
# ============================================================

@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        "✈️ <b>ATC TEST TRAINER</b>\n\n"
        "Выбери предмет:\n\n"
        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🎲 Вопросы перемешиваются\n"
        "🔀 Варианты ответов перемешиваются\n"
        "📊 Результат в конце",
        parse_mode="HTML",
        reply_markup=subjects_keyboard()
    )


# ============================================================
# /TEST
# ============================================================

@dp.message(Command("test"))
async def test_command(message: Message):

    await message.answer(
        "Выбери предмет:",
        reply_markup=subjects_keyboard()
    )


# ============================================================
# ВЫБОР ПРЕДМЕТА
# ============================================================

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
            "Предмет не найден"
        )

        return


    subject = subjects[index]

    all_questions = TESTS[subject]


    print(
        f"Пользователь {user_id} выбрал "
        f"{subject}: {len(all_questions)} вопросов"
    )


    if len(all_questions) < QUESTIONS_PER_TEST:

        await callback.message.answer(
            f"❌ В этом предмете найдено "
            f"<b>{len(all_questions)}</b> вопросов.\n\n"
            f"Для теста нужно минимум "
            f"<b>{QUESTIONS_PER_TEST}</b>.\n\n"
            f"Значит файл всё ещё читается "
            f"неправильно или в этом разделе "
            f"действительно меньше 30 вопросов.",
            parse_mode="HTML"
        )

        await callback.answer()

        return


    # --------------------------------------------------------
    # Случайные 30 вопросов
    # --------------------------------------------------------

    selected_questions = random.sample(
        all_questions,
        QUESTIONS_PER_TEST
    )


    questions = []


    for question in selected_questions:

        q = {
            "number": question["number"],
            "question": question["question"],
            "options": [
                dict(option)
                for option in question["options"]
            ],
            "correct": question["correct"]
        }

        # Перемешиваем варианты
        random.shuffle(
            q["options"]
        )

        questions.append(q)


    # --------------------------------------------------------
    # Создаём тест пользователя
    # --------------------------------------------------------

    USERS[user_id] = {

        "subject": subject,

        "questions": questions,

        "current": 0,

        "answers": [],

        "end_time":
            datetime.now()
            + timedelta(
                minutes=TEST_TIME_MINUTES
            )
    }


    await callback.message.answer(
        f"🛫 <b>{subject}</b>\n\n"
        f"📝 Вопросов: <b>30</b>\n"
        f"⏱ Время: <b>30 минут</b>\n\n"
        f"Удачи! Начинаем.",
        parse_mode="HTML"
    )


    await send_question(
        user_id
    )


    await callback.answer()


# ============================================================
# ОТПРАВКА ВОПРОСА
# ============================================================

async def send_question(user_id):

    if user_id not in USERS:
        return


    user = USERS[user_id]

    current = user["current"]


    # --------------------------------------------------------
    # Проверяем время
    # --------------------------------------------------------

    if datetime.now() >= user["end_time"]:

        await finish_test(
            user_id,
            True
        )

        return


    # --------------------------------------------------------
    # Проверяем количество вопросов
    # --------------------------------------------------------

    if current >= QUESTIONS_PER_TEST:

        await finish_test(
            user_id,
            False
        )

        return


    question = user["questions"][current]


    # --------------------------------------------------------
    # Остаток времени
    # --------------------------------------------------------

    remaining = (
        user["end_time"]
        - datetime.now()
    )

    seconds = max(
        0,
        int(
            remaining.total_seconds()
        )
    )

    minutes = seconds // 60

    seconds = seconds % 60


    # --------------------------------------------------------
    # Текст вопроса
    # --------------------------------------------------------

    text = (
        f"📝 <b>Вопрос "
        f"{current + 1}/30</b>\n"
        f"⏱ Осталось: "
        f"<b>{minutes:02d}:{seconds:02d}</b>\n\n"
        f"{question['question']}"
    )


    # --------------------------------------------------------
    # Кнопки
    # --------------------------------------------------------

    keyboard = InlineKeyboardBuilder()


    for option in question["options"]:

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


# ============================================================
# ОТВЕТ
# ============================================================

@dp.callback_query(
    F.data.startswith("answer:")
)
async def answer_question(
    callback: CallbackQuery
):

    user_id = callback.from_user.id


    if user_id not in USERS:

        await callback.answer(
            "Тест уже завершён. Напиши /start"
        )

        return


    user = USERS[user_id]


    # --------------------------------------------------------
    # Проверяем время
    # --------------------------------------------------------

    if datetime.now() >= user["end_time"]:

        await finish_test(
            user_id,
            True
        )

        await callback.answer()

        return


    selected = int(
        callback.data.split(":")[1]
    )


    question = user["questions"][
        user["current"]
    ]


    # --------------------------------------------------------
    # Запоминаем ответ
    # --------------------------------------------------------

    user["answers"].append({

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


    # --------------------------------------------------------
    # Удаляем старое сообщение
    # --------------------------------------------------------

    try:

        await callback.message.delete()

    except Exception:

        pass


    # --------------------------------------------------------
    # Следующий вопрос
    # --------------------------------------------------------

    if user["current"] >= QUESTIONS_PER_TEST:

        await finish_test(
            user_id,
            False
        )

    else:

        await send_question(
            user_id
        )


    await callback.answer()


# ============================================================
# ЗАВЕРШЕНИЕ ТЕСТА
# ============================================================

async def finish_test(
    user_id,
    time_finished=False
):

    if user_id not in USERS:
        return


    user = USERS[user_id]

    answers = user["answers"]


    correct_count = 0


    for answer in answers:

        if (
            answer["selected"]
            == answer["correct"]
        ):

            correct_count += 1


    total = len(answers)

    wrong_count = (
        total
        - correct_count
    )


    percentage = (

        round(
            correct_count
            / total
            * 100
        )

        if total > 0

        else 0
    )


    # --------------------------------------------------------
    # Результат
    # --------------------------------------------------------

    if time_finished:

        result = (
            "⏰ <b>ВРЕМЯ ВЫШЛО!</b>\n\n"
        )

    else:

        result = (
            "🏁 <b>ТЕСТ ЗАВЕРШЁН!</b>\n\n"
        )


    result += (
        f"📚 Предмет: "
        f"<b>{user['subject']}</b>\n\n"

        f"📝 Отвечено: "
        f"<b>{total}/30</b>\n"

        f"✅ Правильных: "
        f"<b>{correct_count}</b>\n"

        f"❌ Ошибок: "
        f"<b>{wrong_count}</b>\n"

        f"📊 Результат: "
        f"<b>{percentage}%</b>\n\n"

        f"📋 <b>ПРАВИЛЬНЫЕ ОТВЕТЫ</b>\n"
    )


    # --------------------------------------------------------
    # Показываем правильные ответы
    # --------------------------------------------------------

    for index, answer in enumerate(
        answers,
        start=1
    ):

        correct_text = ""


        for option in answer["options"]:

            if (
                option["number"]
                == answer["correct"]
            ):

                correct_text = option["text"]

                break


        result += (
            f"\n<b>{index}.</b> "
            f"Правильный: "
            f"{answer['correct']}) "
            f"{correct_text}\n"
        )


        if (
            answer["selected"]
            == answer["correct"]
        ):

            result += (
                "Ваш ответ: "
                "✅ Правильно\n"
            )

        else:

            result += (
                f"Ваш ответ: "
                f"{answer['selected']}) "
                f"❌ Ошибка\n"
            )


    # --------------------------------------------------------
    # Telegram ограничивает размер сообщения
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Удаляем тест
    # --------------------------------------------------------

    del USERS[user_id]


    await bot.send_message(
        user_id,
        "🔄 Чтобы пройти ещё один тест, "
        "нажми /start"
    )


# ============================================================
# WEBHOOK
# ============================================================

async def on_startup(app):

    webhook_url = (
        RENDER_URL
        + "/webhook"
    )


    print(
        "Устанавливаем webhook:",
        webhook_url
    )


    await bot.set_webhook(
        webhook_url
    )


    print(
        "Webhook установлен!"
    )


async def on_shutdown(app):

    print(
        "Останавливаем бота..."
    )


    await bot.delete_webhook()


    await bot.session.close()


# ============================================================
# WEB SERVER
# ============================================================

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


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    print(
        f"Запускаем сервер на порту {PORT}"
    )


    web.run_app(
        app,
        host="0.0.0.0",
        port=PORT
    )
