import os
import re
import random
import asyncio
from datetime import datetime, timedelta

from docx import Document

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder


# =========================================================
# НАСТРОЙКИ
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("Не найден BOT_TOKEN")

TEST_FILE = "ТЕСТЫ.docx"

QUESTIONS_PER_TEST = 30
TEST_TIME_MINUTES = 30


bot = Bot(token=TOKEN)
dp = Dispatcher()


# =========================================================
# ДАННЫЕ
# =========================================================

# Все предметы
TESTS = {}

# Активные тесты пользователей
users = {}

# Таймеры пользователей
timers = {}


# =========================================================
# ЧТЕНИЕ WORD
# =========================================================

def read_docx(filename):

    document = Document(filename)

    lines = []

    for paragraph in document.paragraphs:

        text = paragraph.text.strip()

        if text:
            lines.append(text)

    return lines


# =========================================================
# РАЗБОР ТЕСТЫ.DOCX
# =========================================================

def parse_tests(filename):

    lines = read_docx(filename)

    subjects = {}

    current_subject = None
    current_question = None
    current_option = None

    def save_question():

        nonlocal current_question

        if current_question is None:
            return

        # Добавляем вопрос только если:
        # есть текст, варианты и правильный ответ
        if (
            current_question["question"].strip()
            and len(current_question["options"]) >= 2
            and current_question["correct"] is not None
        ):

            subjects.setdefault(
                current_question["subject"],
                []
            ).append(current_question)

        current_question = None

    def finish_option():

        nonlocal current_option

        if current_question is None:
            current_option = None
            return

        if current_option is not None:

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

    for line in lines:

        # -------------------------------------------------
        # НОВЫЙ ПРЕДМЕТ
        # -------------------------------------------------

        subject_match = re.match(
            r"^Тест\s*:\s*(.+)$",
            line,
            re.IGNORECASE
        )

        if subject_match:

            finish_option()
            save_question()

            current_subject = subject_match.group(1).strip()

            subjects.setdefault(
                current_subject,
                []
            )

            continue


        # -------------------------------------------------
        # ЗАГОЛОВОК "Тестируемый"
        # -------------------------------------------------

        if line.lower().startswith("тестируемый"):
            continue


        # -------------------------------------------------
        # НОВЫЙ ВОПРОС
        # -------------------------------------------------

        question_match = re.match(
            r"^Задание\s*#\s*(\d+)",
            line,
            re.IGNORECASE
        )

        if question_match:

            finish_option()
            save_question()

            current_question = {
                "number": int(question_match.group(1)),
                "subject": current_subject or "Без предмета",
                "question": "",
                "options": [],
                "correct": None
            }

            continue


        # -------------------------------------------------
        # СТРОКА "ВЫБЕРИТЕ..."
        # -------------------------------------------------

        if re.match(
            r"^Выберите один из",
            line,
            re.IGNORECASE
        ):
            continue


        # -------------------------------------------------
        # НОВЫЙ ВАРИАНТ ОТВЕТА
        #
        # Примеры:
        # 1) + текст
        # 2) - текст
        # 3) +
        # текст следующей строкой
        # -------------------------------------------------

        option_match = re.match(
            r"^(\d+)\)\s*(?:([+-]))?\s*(.*)$",
            line
        )

        if option_match and current_question is not None:

            finish_option()

            number = int(option_match.group(1))
            sign = option_match.group(2)
            text = option_match.group(3).strip()

            current_option = {
                "number": number,
                "text": text,
                "correct": sign == "+"
            }

            continue


        # -------------------------------------------------
        # ПРОДОЛЖЕНИЕ ВОПРОСА
        # -------------------------------------------------

        if current_question is not None:

            if current_option is not None:

                # Продолжение варианта ответа
                if current_option["text"]:
                    current_option["text"] += "\n" + line
                else:
                    current_option["text"] = line

            else:

                # Текст вопроса
                if current_question["question"]:
                    current_question["question"] += " " + line
                else:
                    current_question["question"] = line


    # Сохраняем последние данные
    finish_option()
    save_question()

    return subjects


# Загружаем вопросы
TESTS = parse_tests(TEST_FILE)


# =========================================================
# ПРОВЕРКА БАЗЫ
# =========================================================

print()
print("====================================")
print("       БОТ ЗАПУЩЕН")
print("====================================")
print()

for subject, questions in TESTS.items():

    print(
        f"{subject}: {len(questions)} вопросов"
    )

print()


# =========================================================
# КНОПКИ ПРЕДМЕТОВ
# =========================================================

def subject_keyboard():

    builder = InlineKeyboardBuilder()

    subjects = list(TESTS.keys())

    for index, subject in enumerate(subjects):

        builder.button(
            text=subject,
            callback_data=f"subject:{index}"
        )

    builder.adjust(1)

    return builder.as_markup()


# =========================================================
# /START
# =========================================================

@dp.message(Command("start"))
async def start(message: Message):

    await message.answer(
        "✈️ <b>Тренажёр экзаменационных тестов</b>\n\n"
        "Выбери предмет:\n\n"
        "📝 30 вопросов\n"
        "⏱ 30 минут\n"
        "🎲 Вопросы и варианты перемешиваются\n"
        "📊 В конце — результат и правильные ответы.",
        parse_mode="HTML",
        reply_markup=subject_keyboard()
    )


# =========================================================
# ВЫБОР ПРЕДМЕТА
# =========================================================

@dp.callback_query(F.data.startswith("subject:"))
async def choose_subject(callback: CallbackQuery):

    user_id = callback.from_user.id

    index = int(
        callback.data.split(":")[1]
    )

    subjects = list(TESTS.keys())

    if index >= len(subjects):

        await callback.answer(
            "Предмет не найден"
        )

        return

    subject = subjects[index]

    all_questions = TESTS[subject]

    if len(all_questions) < QUESTIONS_PER_TEST:

        await callback.message.answer(
            f"❌ В предмете <b>{subject}</b> "
            f"только {len(all_questions)} вопросов.\n\n"
            f"Нужно минимум {QUESTIONS_PER_TEST}.",
            parse_mode="HTML"
        )

        await callback.answer()

        return


    # Если у пользователя уже был тест
    if user_id in users:

        old_timer = timers.get(user_id)

        if old_timer:

            old_timer.cancel()

        users.pop(user_id, None)


    # Берём случайные 30 вопросов
    selected_questions = random.sample(
        all_questions,
        QUESTIONS_PER_TEST
    )


    # Делаем копии вопросов,
    # чтобы не менять оригинальную базу
    questions = []

    for q in selected_questions:

        question_copy = {
            "number": q["number"],
            "subject": q["subject"],
            "question": q["question"],
            "options": [dict(x) for x in q["options"]],
            "correct": q["correct"]
        }

        # Перемешиваем варианты
        random.shuffle(
            question_copy["options"]
        )

        questions.append(
            question_copy
        )


    end_time = (
        datetime.now()
        + timedelta(minutes=TEST_TIME_MINUTES)
    )


    users[user_id] = {
        "subject": subject,
        "questions": questions,
        "current": 0,
        "answers": [],
        "end_time": end_time
    }


    await callback.message.answer(
        f"🛫 <b>{subject}</b>\n\n"
        f"Вопросов: <b>30</b>\n"
        f"Время: <b>30 минут</b>\n\n"
        "Удачи! Начинаем.",
        parse_mode="HTML"
    )


    await send_question(user_id)


    # Запускаем таймер
    timers[user_id] = asyncio.create_task(
        timer_task(user_id)
    )


    await callback.answer()


# =========================================================
# ОТПРАВКА ВОПРОСА
# =========================================================

async def send_question(user_id):

    if user_id not in users:
        return

    user = users[user_id]

    current = user["current"]

    if current >= QUESTIONS_PER_TEST:

        await finish_test(
            user_id,
            time_finished=False
        )

        return


    question = user["questions"][current]


    # Сколько времени осталось
    remaining = (
        user["end_time"]
        - datetime.now()
    )

    seconds = max(
        0,
        int(remaining.total_seconds())
    )

    minutes = seconds // 60
    sec = seconds % 60


    text = (
        f"📝 <b>Вопрос {current + 1}/30</b>\n"
        f"⏱ Осталось: <b>{minutes:02d}:{sec:02d}</b>\n\n"
        f"{question['question']}\n"
    )


    builder = InlineKeyboardBuilder()


    for option in question["options"]:

        button_text = (
            f"{option['number']}) "
            f"{option['text']}"
        )

        builder.button(
            text=button_text,
            callback_data=(
                f"answer:{option['number']}"
            )
        )


    builder.adjust(1)


    await bot.send_message(
        user_id,
        text,
        parse_mode="HTML",
        reply_markup=builder.as_markup()
    )


# =========================================================
# ОТВЕТ ПОЛЬЗОВАТЕЛЯ
# =========================================================

@dp.callback_query(F.data.startswith("answer:"))
async def answer_question(callback: CallbackQuery):

    user_id = callback.from_user.id

    if user_id not in users:

        await callback.answer(
            "Тест закончился. Напиши /start"
        )

        return


    user = users[user_id]


    # Проверяем время
    if datetime.now() >= user["end_time"]:

        await finish_test(
            user_id,
            time_finished=True
        )

        await callback.answer()

        return


    answer_number = int(
        callback.data.split(":")[1]
    )


    question = user["questions"][
        user["current"]
    ]


    # Сохраняем ответ
    user["answers"].append({
        "question_number": question["number"],
        "question": question["question"],
        "selected": answer_number,
        "correct": question["correct"],
        "options": question["options"]
    })


    user["current"] += 1


    # Удаляем старый вопрос
    try:

        await callback.message.delete()

    except Exception:
        pass


    if user["current"] >= QUESTIONS_PER_TEST:

        await finish_test(
            user_id,
            time_finished=False
        )

    else:

        await send_question(user_id)


    await callback.answer()


# =========================================================
# ТАЙМЕР
# =========================================================

async def timer_task(user_id):

    try:

        while user_id in users:

            user = users[user_id]

            remaining = (
                user["end_time"]
                - datetime.now()
            )


            if remaining.total_seconds() <= 0:

                await finish_test(
                    user_id,
                    time_finished=True
                )

                return


            await asyncio.sleep(1)


    except asyncio.CancelledError:

        return


# =========================================================
# ЗАВЕРШЕНИЕ ТЕСТА
# =========================================================

async def finish_test(
    user_id,
    time_finished=False
):

    if user_id not in users:
        return


    user = users[user_id]

    answers = user["answers"]


    # Останавливаем таймер
    timer = timers.pop(
        user_id,
        None
    )

    if timer:

        timer.cancel()


    correct_count = 0


    for answer in answers:

        if (
            answer["selected"]
            == answer["correct"]
        ):
            correct_count += 1


    total = len(answers)

    wrong_count = (
        total - correct_count
    )


    if total:

        percentage = round(
            correct_count
            / total
            * 100
        )

    else:

        percentage = 0


    if time_finished:

        status = (
            "⏰ <b>Время вышло!</b>"
        )

    else:

        status = (
            "🏁 <b>Тест завершён!</b>"
        )


    result = (
        f"{status}\n\n"
        f"📚 Предмет: <b>{user['subject']}</b>\n"
        f"📝 Отвечено: <b>{total}/30</b>\n"
        f"✅ Правильных: <b>{correct_count}</b>\n"
        f"❌ Ошибок: <b>{wrong_count}</b>\n"
        f"📊 Результат: <b>{percentage}%</b>\n\n"
        f"<b>ПРАВИЛЬНЫЕ ОТВЕТЫ</b>\n"
    )


    # Показываем ответы
    for i, answer in enumerate(
        answers,
        start=1
    ):

        result += (
            f"\n<b>{i}.</b> "
            f"{answer['correct']}) "
        )

        # Находим текст правильного ответа
        correct_text = ""

        for option in answer["options"]:

            if option["number"] == answer["correct"]:

                correct_text = option["text"]

                break


        result += correct_text

        result += (
            f"\nВаш ответ: "
            f"{answer['selected']})"
        )

        if (
            answer["selected"]
            == answer["correct"]
        ):

            result += " ✅"

        else:

            result += " ❌"


    # Telegram ограничивает сообщение примерно 4096 символами.
    # Поэтому разбиваем результат на части.
    chunks = []

    while len(result) > 4000:

        cut = result.rfind(
            "\n",
            0,
            4000
        )

        if cut == -1:
            cut = 4000

        chunks.append(
            result[:cut]
        )

        result = result[cut:]


    if result:
        chunks.append(result)


    for chunk in chunks:

        await bot.send_message(
            user_id,
            chunk,
            parse_mode="HTML"
        )


    # Удаляем тест
    users.pop(
        user_id,
        None
    )


    # Предлагаем начать заново
    await bot.send_message(
        user_id,
        "🔄 Хочешь пройти ещё один тест?\n\n"
        "Нажми /start"
    )


# =========================================================
# КОМАНДА /TEST
# =========================================================

@dp.message(Command("test"))
async def test_command(message: Message):

    await message.answer(
        "Выбери предмет:",
        reply_markup=subject_keyboard()
    )


# =========================================================
# ЗАПУСК
# =========================================================

async def main():

    print("================================")
    print("Telegram Test Bot started")
    print("================================")

    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())
