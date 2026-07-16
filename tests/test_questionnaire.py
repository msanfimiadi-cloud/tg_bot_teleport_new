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

class FakeBot:
    def __init__(self, fail_on: int | None = None) -> None:
        self.messages: list[tuple[int | str, str]] = []
        self.fail_on = fail_on

    async def send_message(self, chat_id: int | str, text: str, **kwargs: object) -> None:
        if self.fail_on is not None and len(self.messages) + 1 == self.fail_on:
            raise RuntimeError("telegram down")
        self.messages.append((chat_id, text))


class FakeEvents:
    def __init__(self) -> None:
        self.rows: list[tuple[object, User | None, dict[str, object] | None]] = []

    async def add(
        self,
        event_type: object,
        user: User | None,
        payload: dict[str, object] | None = None,
    ) -> object:
        self.rows.append((event_type, user, payload))
        return object()


async def test_successful_questionnaire_publication_sends_group_welcome() -> None:
    from teleport_bot.config.settings import Settings
    from teleport_bot.services.public_welcome import (
        PUBLIC_WELCOME_TEXT,
        publish_questionnaire_and_send_welcome,
    )

    u = user()
    complete(u, u.questionnaire)
    bot = FakeBot()
    sent = await publish_questionnaire_and_send_welcome(
        bot, Settings(private_chat_id=-100, admin_ids=""), FakeEvents(), u, u.questionnaire  # type: ignore[arg-type]
    )

    assert sent is True
    assert bot.messages[-1] == (-100, PUBLIC_WELCOME_TEXT)
    assert u.welcome_message_sent_at is not None


async def test_unpublished_questionnaire_does_not_send_welcome() -> None:
    from teleport_bot.config.settings import Settings
    from teleport_bot.services.public_welcome import publish_questionnaire_and_send_welcome

    u = user()
    bot = FakeBot()
    sent = await publish_questionnaire_and_send_welcome(
        bot, Settings(private_chat_id=-100, admin_ids=""), FakeEvents(), u, u.questionnaire  # type: ignore[arg-type]
    )

    assert sent is False
    assert bot.messages == []
    assert u.welcome_message_sent_at is None


async def test_repeat_chat_member_update_does_not_duplicate_welcome() -> None:
    from teleport_bot.config.settings import Settings
    from teleport_bot.services.public_welcome import publish_questionnaire_and_send_welcome

    u = user()
    complete(u, u.questionnaire)
    bot = FakeBot()
    settings = Settings(private_chat_id=-100, admin_ids="")
    events = FakeEvents()

    await publish_questionnaire_and_send_welcome(bot, settings, events, u, u.questionnaire)  # type: ignore[arg-type]
    await publish_questionnaire_and_send_welcome(bot, settings, events, u, u.questionnaire)  # type: ignore[arg-type]

    assert len(bot.messages) == 2


async def test_rejoin_does_not_duplicate_welcome() -> None:
    from teleport_bot.config.settings import Settings
    from teleport_bot.services.public_welcome import publish_questionnaire_and_send_welcome

    u = user()
    complete(u, u.questionnaire)
    bot = FakeBot()
    settings = Settings(private_chat_id=-100, admin_ids="")
    events = FakeEvents()

    await publish_questionnaire_and_send_welcome(bot, settings, events, u, u.questionnaire)  # type: ignore[arg-type]
    u.questionnaire.status = QuestionnaireStatus.COMPLETED.value
    await publish_questionnaire_and_send_welcome(bot, settings, events, u, u.questionnaire)  # type: ignore[arg-type]

    assert len(bot.messages) == 2


async def test_telegram_api_error_does_not_set_welcome_timestamp() -> None:
    from teleport_bot.config.settings import Settings
    from teleport_bot.services.public_welcome import publish_questionnaire_and_send_welcome

    u = user()
    complete(u, u.questionnaire)
    bot = FakeBot(fail_on=2)
    events = FakeEvents()
    sent = await publish_questionnaire_and_send_welcome(
        bot, Settings(private_chat_id=-100, admin_ids=""), events, u, u.questionnaire  # type: ignore[arg-type]
    )

    assert sent is False
    assert len(bot.messages) == 1
    assert u.welcome_message_sent_at is None
    assert events.rows

class FakeStatus:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class FakeMember:
    def __init__(self, status: str) -> None:
        self.status = FakeStatus(status)


class FakeChatMemberUpdated:
    def __init__(self, chat_id: int, old_status: str, new_status: str) -> None:
        self.chat = FakeChat(chat_id)
        self.old_chat_member = FakeMember(old_status)
        self.new_chat_member = FakeMember(new_status)


def test_private_chat_join_detected_only_for_real_join_to_private_chat() -> None:
    from teleport_bot.bot.handlers.onboarding import _is_private_chat_join

    assert _is_private_chat_join(FakeChatMemberUpdated(-100, "left", "member"), -100) is True  # type: ignore[arg-type]
    assert _is_private_chat_join(FakeChatMemberUpdated(-100, "member", "member"), -100) is False  # type: ignore[arg-type]
    assert _is_private_chat_join(FakeChatMemberUpdated(-200, "left", "member"), -100) is False  # type: ignore[arg-type]
    assert _is_private_chat_join(FakeChatMemberUpdated(-100, "member", "left"), -100) is False  # type: ignore[arg-type]
