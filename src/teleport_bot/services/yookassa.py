from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

import aiohttp
from aiohttp import BasicAuth, ClientResponse, ClientTimeout
from structlog.stdlib import get_logger

from teleport_bot.config.settings import Settings

logger = get_logger(__name__)

_SAFE_TEXT_LIMIT = 2000
_LOG_JSON_FIELDS = ("code", "description", "parameter", "type", "id")


@dataclass(frozen=True)
class ProviderPayment:
    provider_payment_id: str
    status: str
    amount: Decimal
    currency: str
    confirmation_url: str | None = None
    paid: bool = False
    payment_method_id: str | None = None
    payment_method_saved: bool = False
    payment_method_title: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    metadata: dict[str, Any] | None = None


class YooKassaRequestError(RuntimeError):
    def __init__(
        self,
        *,
        status: int,
        error_code: str | None = None,
        description: str | None = None,
        parameter: str | None = None,
    ) -> None:
        super().__init__(f"YooKassa request failed with status {status}")
        self.status = status
        self.error_code = error_code
        self.description = description
        self.parameter = parameter


class YooKassaGatewayProtocol(Protocol):
    async def create_payment(
        self,
        *,
        idempotency_key: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,
        customer_phone: str | None = None,
    ) -> ProviderPayment: ...
    async def get_payment(self, provider_payment_id: str) -> ProviderPayment: ...


class YooKassaGateway:
    api_base = "https://api.yookassa.ru/v3"
    timeout = ClientTimeout(total=20)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_payment(
        self,
        *,
        idempotency_key: str,
        metadata: dict[str, Any],
        customer_email: str | None = None,
        customer_phone: str | None = None,
    ) -> ProviderPayment:
        payload = self._build_payment_payload(
            metadata=metadata, customer_email=customer_email, customer_phone=customer_phone
        )
        async with aiohttp.ClientSession(
            auth=BasicAuth(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key)
        ) as client:
            async with client.post(
                f"{self.api_base}/payments",
                json=payload,
                headers={"Idempotence-Key": idempotency_key},
                timeout=self.timeout,
            ) as resp:
                await self._raise_for_error(
                    resp, operation="create_payment", idempotency_key=idempotency_key
                )
                return self._parse(await resp.json())

    def _build_payment_payload(
        self,
        *,
        metadata: dict[str, Any],
        customer_email: str | None = None,
        customer_phone: str | None = None,
    ) -> dict[str, Any]:
        if not customer_email and not customer_phone:
            raise ValueError("receipt_customer_contact_required")
        amount = {
            "value": str(self.settings.subscription_price),
            "currency": self.settings.yookassa_currency,
        }
        customer = {}
        if customer_email:
            customer["email"] = customer_email
        if customer_phone:
            customer["phone"] = customer_phone
        payload: dict[str, Any] = {
            "amount": amount,
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": self.settings.yookassa_return_url},
            "description": self.settings.subscription_description,
            "metadata": metadata,
            "save_payment_method": self.settings.payment_save_method_enabled,
            "receipt": {
                "customer": customer,
                "items": [
                    {
                        "description": self.settings.subscription_title
                        or self.settings.subscription_description,
                        "quantity": "1",
                        "amount": amount.copy(),
                        "vat_code": self.settings.yookassa_vat_code,
                        "payment_mode": self.settings.yookassa_payment_mode,
                        "payment_subject": self.settings.yookassa_payment_subject,
                    }
                ],
            },
        }
        return payload

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment:
        async with aiohttp.ClientSession(
            auth=BasicAuth(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key)
        ) as client:
            async with client.get(
                f"{self.api_base}/payments/{provider_payment_id}", timeout=self.timeout
            ) as resp:
                resp.raise_for_status()
                return self._parse(await resp.json())

    async def _raise_for_error(
        self, resp: ClientResponse, *, operation: str, idempotency_key: str
    ) -> None:
        if resp.status < 400:
            return
        text = await resp.text()
        data: dict[str, Any] | None = None
        try:
            parsed = await resp.json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            data = parsed
        fields = {name: data.get(name) for name in _LOG_JSON_FIELDS if data and data.get(name)}
        safe_body: dict[str, Any] | str
        if data is not None:
            safe_body = self._safe_json(data)
        else:
            safe_body = _limit_text(self._redact_text(text))
        logger.error(
            "yookassa_request_failed",
            operation=operation,
            status=resp.status,
            idempotency_key=idempotency_key,
            yookassa_error=fields,
            response_body=safe_body,
        )
        raise YooKassaRequestError(
            status=resp.status,
            error_code=str(fields["code"]) if "code" in fields else None,
            description=str(fields["description"]) if "description" in fields else None,
            parameter=str(fields["parameter"]) if "parameter" in fields else None,
        )

    def _safe_json(self, value: Any) -> Any:
        return _safe_json(value, secrets=self._redaction_values())

    def _redact_text(self, text: str) -> str:
        return _redact_text(text, secrets=self._redaction_values())

    def _redaction_values(self) -> tuple[str, ...]:
        return (self.settings.yookassa_secret_key, self.settings.bot_token)

    def _parse(self, data: dict[str, Any]) -> ProviderPayment:
        method = data.get("payment_method") or {}
        card = method.get("card") or {}
        return ProviderPayment(
            provider_payment_id=str(data["id"]),
            status=str(data["status"]),
            amount=Decimal(str(data["amount"]["value"])),
            currency=str(data["amount"]["currency"]),
            confirmation_url=(data.get("confirmation") or {}).get("confirmation_url"),
            paid=bool(data.get("paid")),
            payment_method_id=method.get("id"),
            payment_method_saved=bool(method.get("saved")),
            payment_method_title=card.get("last4") and f"Карта •••• {card['last4']}",
            failure_code=(data.get("cancellation_details") or {}).get("reason"),
            failure_message=(data.get("cancellation_details") or {}).get("party"),
            metadata=data.get("metadata") or {},
        )


def _safe_json(value: Any, *, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_secret_key(key_text) or key_text == "payment_method":
                safe[key_text] = "<redacted>"
            else:
                safe[key_text] = _safe_json(item, secrets=secrets)
        return safe
    if isinstance(value, list):
        return [_safe_json(item, secrets=secrets) for item in value]
    if isinstance(value, str):
        return _limit_text(_mask_email(_redact_text(value, secrets=secrets)))
    return value


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in ("secret", "token", "authorization"))


def _redact_text(text: str, *, secrets: tuple[str, ...] = ()) -> str:
    redacted = _mask_email(text)
    for secret in (*secrets, "YOOKASSA_SECRET_KEY", "BOT_TOKEN", "Authorization"):
        if secret:
            redacted = redacted.replace(secret, "<redacted>")
    return redacted


def _limit_text(text: str) -> str:
    if len(text) <= _SAFE_TEXT_LIMIT:
        return text
    return f"{text[:_SAFE_TEXT_LIMIT]}...<truncated>"


def new_idempotency_key() -> str:
    return str(uuid4())


def _mask_email(text: str) -> str:
    import re

    def repl(match: re.Match[str]) -> str:
        email = match.group(0)
        local, domain = email.split("@", 1)
        visible = local[:1] if local else ""
        return f"{visible}***@{domain}"

    return re.sub(
        r"[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", repl, text
    )
