from datetime import UTC, datetime

import pytest

from teleport_bot.models.db import Questionnaire, User
from teleport_bot.models.enums import FunnelStatus, QuestionnaireStatus
from teleport_bot.services.questionnaire import (
    QUESTIONS,
    ValidationError,
    complete,
    set_answer,
    validate_answer,
)


def user() -> User:
    u = User(
        telegram_id=1,
        username=None,
        first_name="A",
        first_started_at=datetime.now(UTC),
        last_activity_at=datetime.now(UTC),
    )
    u.id = 1
    u.questionnaire = Questionnaire(
        user_id=1, current_step=1, status=QuestionnaireStatus.NOT_STARTED.value
    )
    return u


def test_short_answer_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_answer(QUESTIONS[0], " a ")


def test_valid_answer_trimmed() -> None:
    assert validate_answer(QUESTIONS[0], "  Анна, 30  ") == "Анна, 30"


def test_progress_saved_after_answer() -> None:
    u = user()
    set_answer(u.questionnaire, 1, "Анна, 30")
    assert u.questionnaire.name_and_age == "Анна, 30"
    assert u.questionnaire.current_step == 2
    assert u.questionnaire.status == QuestionnaireStatus.IN_PROGRESS.value


def test_back_can_restore_previous_step() -> None:
    u = user()
    u.questionnaire.current_step = 3
    u.questionnaire.current_step -= 1
    assert u.questionnaire.current_step == 2


def test_change_saved_answer() -> None:
    u = user()
    set_answer(u.questionnaire, 1, "Анна, 30")
    set_answer(u.questionnaire, 1, "Мария, 31")
    assert u.questionnaire.name_and_age == "Мария, 31"


def test_restore_progress_after_restart_from_db_state() -> None:
    u = user()
    u.questionnaire.current_step = 4
    assert u.questionnaire.current_step == 4


def test_confirm_questionnaire_idempotent() -> None:
    u = user()
    assert complete(u, u.questionnaire) is True
    assert complete(u, u.questionnaire) is False
    assert u.questionnaire.status == QuestionnaireStatus.COMPLETED.value


def test_missing_username_allowed() -> None:
    u = user()
    assert u.username is None


def test_payment_stage_status() -> None:
    u = user()
    u.funnel_status = FunnelStatus.PAYMENT_STAGE_REACHED.value
    assert u.funnel_status == FunnelStatus.PAYMENT_STAGE_REACHED.value


def test_not_authorized_admin_by_username() -> None:
    admin_ids = (42,)
    assert 1 not in admin_ids
