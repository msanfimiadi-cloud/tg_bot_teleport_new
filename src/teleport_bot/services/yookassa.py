from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import uuid4

import aiohttp
from aiohttp import BasicAuth, ClientTimeout

from teleport_bot.config.settings import Settings


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


class YooKassaGatewayProtocol(Protocol):
    async def create_payment(
        self, *, idempotency_key: str, metadata: dict[str, Any]
    ) -> ProviderPayment: ...
    async def get_payment(self, provider_payment_id: str) -> ProviderPayment: ...


class YooKassaGateway:
    api_base = "https://api.yookassa.ru/v3"
    timeout = ClientTimeout(total=20)

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_payment(
        self, *, idempotency_key: str, metadata: dict[str, Any]
    ) -> ProviderPayment:
        payload: dict[str, Any] = {
            "amount": {
                "value": str(self.settings.subscription_price),
                "currency": self.settings.yookassa_currency,
            },
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": self.settings.yookassa_return_url},
            "description": self.settings.subscription_description,
            "metadata": metadata,
            "save_payment_method": self.settings.payment_save_method_enabled,
        }
        async with aiohttp.ClientSession(
            auth=BasicAuth(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key)
        ) as client:
            async with client.post(
                f"{self.api_base}/payments",
                json=payload,
                headers={"Idempotence-Key": idempotency_key},
                timeout=self.timeout,
            ) as resp:
                resp.raise_for_status()
                return self._parse(await resp.json())

    async def get_payment(self, provider_payment_id: str) -> ProviderPayment:
        async with aiohttp.ClientSession(
            auth=BasicAuth(self.settings.yookassa_shop_id, self.settings.yookassa_secret_key)
        ) as client:
            async with client.get(
                f"{self.api_base}/payments/{provider_payment_id}", timeout=self.timeout
            ) as resp:
                resp.raise_for_status()
                return self._parse(await resp.json())

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


def new_idempotency_key() -> str:
    return str(uuid4())
