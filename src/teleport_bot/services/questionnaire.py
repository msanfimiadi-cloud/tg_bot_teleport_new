from dataclasses import dataclass
from datetime import UTC, datetime

from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import FunnelStatus, OnboardingStatus, QuestionnaireStatus


@dataclass(frozen=True)
class Question:
    number: int
    field: str
    text: str
    min_length: int
    max_length: int
    error: str


QUESTIONS: tuple[Question, ...] = (
    Question(
        1,
        "name_and_age",
        "1) Имя, возраст.",
        3,
        200,
        "Напиши имя и возраст минимум тремя символами.",
    ),
    Question(
        2,
        "what_annoys",
        "2) Что бесит?\n\nКакие качества или привычки мешают тебе?\nНапиши пару предложений.",
        10,
        2000,
        "Напиши минимум 10 символов.",
    ),
    Question(
        3,
        "what_is_important",
        "3) Что важно?\n\nКакие качества ты хочешь развить?\nНапиши пару предложений.",
        10,
        2000,
        "Напиши минимум 10 символов.",
    ),
    Question(
        4,
        "self_definition",
        (
            "4) Кто ты?\n\nДай своё жизненное определение: предприниматель, йог, мечтатель, "
            "художник или что-то своё.\n\nНапиши пару предложений."
        ),
        10,
        2000,
        "Напиши минимум 10 символов.",
    ),
    Question(
        5,
        "intention",
        (
            "5) Твоё намерение на этот жизненный отрезок\n\nНапример:\n\n"
            "«Хочу перестать бояться»\n«Хочу быть счастливым»\n«Хочу найти опору»\n\n"
            "Напиши пару предложений."
        ),
        10,
        2000,
        "Напиши минимум 10 символов.",
    ),
)


class ValidationError(ValueError):
    pass


def validate_answer(question: Question, value: str) -> str:
    answer = value.strip()
    if len(answer) < question.min_length:
        raise ValidationError(question.error)
    if len(answer) > question.max_length:
        raise ValidationError(f"Ответ слишком длинный. Максимум {question.max_length} символов.")
    return answer


def get_question(step: int) -> Question:
    return QUESTIONS[step - 1]


def progress_text(step: int) -> str:
    return f"Вопрос {step} из {len(QUESTIONS)}"


def set_answer(questionnaire: Questionnaire, step: int, answer: str) -> None:
    question = get_question(step)
    setattr(questionnaire, question.field, answer)
    questionnaire.status = QuestionnaireStatus.IN_PROGRESS.value
    questionnaire.current_step = min(step + 1, len(QUESTIONS))


def render_summary(questionnaire: Questionnaire) -> str:
    parts = ["Проверь анкету:"]
    for question in QUESTIONS:
        parts.append(f"\n{question.text}\nОтвет: {getattr(questionnaire, question.field) or '—'}")
    return "\n".join(parts)


def complete(user: User, questionnaire: Questionnaire) -> bool:
    if questionnaire.status == QuestionnaireStatus.COMPLETED.value:
        return False
    questionnaire.status = QuestionnaireStatus.COMPLETED.value
    questionnaire.current_step = len(QUESTIONS)
    questionnaire.completed_at = datetime.now(UTC)
    user.onboarding_status = OnboardingStatus.QUESTIONNAIRE_COMPLETED.value
    user.funnel_status = FunnelStatus.QUESTIONNAIRE_COMPLETED.value
    return True
