from __future__ import annotations

import json
from typing import Any, ClassVar, cast

import pytest
from aiohttp import ClientResponse

from teleport_bot.bot.handlers import onboarding
from teleport_bot.config.settings import Settings
from teleport_bot.services.yookassa import YooKassaGateway, YooKassaRequestError


class FakeResponse:
    def __init__(self, status: int, body: str, json_data: dict[str, Any] | None = None) -> None:
        self.status = status
        self._body = body
        self._json_data = json_data

    async def text(self) -> str:
        return self._body

    async def json(self) -> dict[str, Any]:
        if self._json_data is None:
            raise ValueError("invalid json")
        return self._json_data


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[str] = []

    async def answer(self, text: str, **_: Any) -> None:
        self.answers.append(text)


class FakeCallback:
    data = "payment:start"

    def __init__(self, message: FakeMessage) -> None:
        self.message = message
        self.from_user = type("FromUser", (), {"id": 12345})()
        self.answered = False

    async def answer(self) -> None:
        self.answered = True


class FakeUser:
    id = 1
    telegram_id = 12345
    email = "saved@example.com"
    funnel_status = ""
    onboarding_status = ""
    subscription = None


class FakeUserRepository:
    def __init__(self, _: Any) -> None:
        pass

    async def get_by_telegram_id(self, _: int) -> FakeUser:
        return FakeUser()


class FakeEventRepository:
    def __init__(self, _: Any) -> None:
        pass

    async def add(self, *_: Any, **__: Any) -> None:
        return None


class FakePaymentService:
    def __init__(self, *_: Any) -> None:
        pass

    async def create_or_reuse_payment(self, _: int) -> None:
        raise YooKassaRequestError(
            status=400,
            error_code="invalid_request",
            description="bad request with secret-value",
            parameter="amount.value",
        )


class FakeAdminNotifier:
    sent: ClassVar[list[str]] = []

    def __init__(self, bot: Any, admin_ids: tuple[int, ...], events: Any) -> None:
        self.bot = bot
        self.admin_ids = admin_ids
        self.events = events

    async def payment_stage_reached(self, user: Any) -> None:
        return None

    async def payment_creation_failed(
        self,
        user: Any,
        *,
        status: int,
        error_code: str | None = None,
        parameter: str | None = None,
    ) -> None:
        self.sent.append(
            "Ошибка создания платежа YooKassa "
            f"status={status} code={error_code} parameter={parameter}"
        )


def _settings() -> Settings:
    return Settings(
        bot_token="bot-token-value",
        yookassa_secret_key="secret-value",
        yookassa_shop_id="shop-id",
    )


@pytest.mark.parametrize(
    "body,json_data,code,description,parameter",
    [
        (
            json.dumps(
                {
                    "type": "error",
                    "id": "err-id",
                    "code": "invalid_request",
                    "description": "Invalid amount",
                    "parameter": "amount.value",
                    "payment_method": {"id": "pm-full", "card": {"first6": "123456"}},
                    "secret": "secret-value",
                    "token": "bot-token-value",
                }
            ),
            {
                "type": "error",
                "id": "err-id",
                "code": "invalid_request",
                "description": "Invalid amount",
                "parameter": "amount.value",
                "payment_method": {"id": "pm-full", "card": {"first6": "123456"}},
                "secret": "secret-value",
                "token": "bot-token-value",
            },
            "invalid_request",
            "Invalid amount",
            "amount.value",
        ),
    ],
)
async def test_create_payment_logs_json_400_safely(
    capsys: pytest.CaptureFixture[str],
    body: str,
    json_data: dict[str, Any],
    code: str,
    description: str,
    parameter: str,
) -> None:
    gateway = YooKassaGateway(_settings())
    with pytest.raises(YooKassaRequestError) as exc_info:
        await gateway._raise_for_error(
            cast(ClientResponse, FakeResponse(400, body, json_data)),
            operation="create_payment",
            idempotency_key="idem-key",
        )

    assert exc_info.value.status == 400
    assert exc_info.value.error_code == code
    assert exc_info.value.description == description
    assert exc_info.value.parameter == parameter
    logs = capsys.readouterr().out
    assert "create_payment" in logs
    assert "idem-key" in logs
    assert "invalid_request" in logs
    assert "amount.value" in logs
    assert "secret-value" not in logs
    assert "bot-token-value" not in logs
    assert "pm-full" not in logs


async def test_create_payment_logs_non_json_400_safely(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gateway = YooKassaGateway(_settings())
    body = "bad secret-value BOT_TOKEN " + ("x" * 3000)

    with pytest.raises(YooKassaRequestError) as exc_info:
        await gateway._raise_for_error(
            cast(ClientResponse, FakeResponse(400, body)),
            operation="create_payment",
            idempotency_key="idem-key",
        )

    assert exc_info.value.status == 400
    assert exc_info.value.error_code is None
    logs = capsys.readouterr().out
    assert "create_payment" in logs
    assert "idem-key" in logs
    assert "<truncated>" in logs
    assert "secret-value" not in logs
    assert "BOT_TOKEN" not in logs


async def test_payment_start_uses_neutral_user_message_and_safe_admin_notification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeAdminNotifier.sent = []
    monkeypatch.setattr(onboarding, "UserRepository", FakeUserRepository)
    monkeypatch.setattr(onboarding, "EventRepository", FakeEventRepository)
    monkeypatch.setattr(onboarding, "PaymentService", FakePaymentService)
    monkeypatch.setattr(onboarding, "AdminNotifier", FakeAdminNotifier)
    monkeypatch.setattr(onboarding, "callback_message", lambda callback: callback.message)

    message = FakeMessage()
    callback = FakeCallback(message)
    settings = Settings(
        admin_ids="100", yookassa_secret_key="secret-value", bot_token="bot-token-value"
    )

    await onboarding.payment_start(callback, object(), object(), object(), settings)

    assert callback.answered is True
    assert message.answers == [
        "Не удалось создать платёж. Попробуй ещё раз немного позже. "
        "Если ошибка повторится — напиши в поддержку."
    ]
    assert FakeAdminNotifier.sent
    admin_text = "\n".join(FakeAdminNotifier.sent)
    assert "status=400" in admin_text
    assert "invalid_request" in admin_text
    assert "amount.value" in admin_text
    assert "secret-value" not in admin_text
    assert "bot-token-value" not in admin_text
