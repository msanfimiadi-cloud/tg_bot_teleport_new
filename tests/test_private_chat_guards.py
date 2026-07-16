import asyncio
import inspect
from types import SimpleNamespace
from typing import Any

from aiogram.enums import ChatType

from teleport_bot.bot.handlers import admin, onboarding
from teleport_bot.bot.handlers.admin import render_chatid_response


class FakeBot:
    async def get_me(self) -> Any:
        return SimpleNamespace(username="ActualTeleportBot")


class FakeMessage:
    def __init__(self, text: str, chat_type: ChatType = ChatType.GROUP) -> None:
        self.text = text
        self.chat = SimpleNamespace(type=chat_type, id=-100, title="Group")
        self.answers: list[tuple[str, Any]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


def test_group_start_sends_private_chat_link_with_actual_bot_username() -> None:
    message = FakeMessage("/start")

    asyncio.run(onboarding.start_in_group(message, FakeBot()))

    assert message.answers[0][0] == onboarding.GROUP_START_TEXT
    button = message.answers[0][1].inline_keyboard[0][0]
    assert button.text == "Открыть бота"
    assert button.url == "https://t.me/ActualTeleportBot?start=group"


def test_group_referral_start_preserves_payload_in_private_chat_link() -> None:
    message = FakeMessage("/start ref_ABC123")

    asyncio.run(onboarding.start_in_group(message, FakeBot()))

    button = message.answers[0][1].inline_keyboard[0][0]
    assert button.url == "https://t.me/ActualTeleportBot?start=ref_ABC123"


def test_group_start_handler_cannot_create_questionnaire_or_change_fsm() -> None:
    params = inspect.signature(onboarding.start_in_group).parameters
    assert "session" not in params
    assert "state" not in params


def test_private_start_handler_keeps_onboarding_dependencies() -> None:
    params = inspect.signature(onboarding.start).parameters
    assert {"session", "state", "settings"}.issubset(params)


def test_text_answer_handlers_are_private_only() -> None:
    assert onboarding.is_private_message(FakeMessage("answer", ChatType.PRIVATE)) is True  # type: ignore[arg-type]
    assert onboarding.is_private_message(FakeMessage("answer", ChatType.GROUP)) is False  # type: ignore[arg-type]
    assert onboarding.is_private_message(FakeMessage("answer", ChatType.SUPERGROUP)) is False  # type: ignore[arg-type]


def test_callback_private_guard_rejects_group_messages() -> None:
    callback = SimpleNamespace(message=FakeMessage("", ChatType.GROUP))
    private_callback = SimpleNamespace(message=FakeMessage("", ChatType.PRIVATE))

    assert onboarding.is_private_callback(callback) is False  # type: ignore[arg-type]
    assert onboarding.is_private_callback(private_callback) is True  # type: ignore[arg-type]


def test_admin_in_group_does_not_open_panel_and_offers_private_chat() -> None:
    message = FakeMessage("/admin", ChatType.GROUP)

    asyncio.run(admin.admin_command(message, object(), object(), FakeBot()))

    assert message.answers[0][0] == admin.OPEN_PRIVATE_TEXT
    assert (
        message.answers[0][1].inline_keyboard[0][0].url
        == "https://t.me/ActualTeleportBot?start=group"
    )


def test_partner_in_group_does_not_show_stats_and_offers_private_chat() -> None:
    message = FakeMessage("/partner", ChatType.SUPERGROUP)

    asyncio.run(admin.partner_command(message, object(), FakeBot()))

    assert message.answers[0][0] == admin.OPEN_PRIVATE_TEXT
    assert (
        message.answers[0][1].inline_keyboard[0][0].url
        == "https://t.me/ActualTeleportBot?start=group"
    )


def test_chatid_still_renders_group_response() -> None:
    assert render_chatid_response(-100123, "Teleport", ChatType.SUPERGROUP) == (
        "ID этого чата:\n-100123\n\nНазвание:\nTeleport\n\nТип:\nsupergroup"
    )
