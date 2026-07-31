"""Integração com o Asaas (cobrança recorrente — assinatura Billy Pro).
Doc: docs.asaas.com. Sandbox por enquanto — não trocar ASAAS_BASE_URL pra
produção sem decisão explícita.

Desenho final (BIL-112): sem checkout hospedado, sem formulário de cartão
próprio (as duas ideias anteriores esbarraram em limitações reais da API —
Pix não é aceito em cobrança RECURRENT via Checkout, e não existe
tokenização client-side de cartão). billingType=UNDEFINED na assinatura +
redirect pro invoiceUrl (fatura hospedada do Asaas) — o pagador escolhe
boleto/Pix/cartão lá, o backend do Billy nunca toca em dado de cartão."""

from __future__ import annotations

import hmac
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from api.core.config import settings

_log = logging.getLogger(__name__)

ASAAS_BASE_URL = "https://api-sandbox.asaas.com/v3"

# Espelha src/data/plans.ts (Billy Pro) — preço nunca vem do cliente, é
# sempre resolvido aqui a partir do plan_id antes de criar a cobrança no
# Asaas (evita adulteração de valor pelo frontend). Só planos pagos —
# latido/coleira (free) nunca passam por assinatura Asaas.
PLAN_PRICES: dict[str, dict[str, float]] = {
    "corrida": {"mensal": 19, "anual": 190},
    "matilha": {"mensal": 39, "anual": 390},
    "guia": {"mensal": 89, "anual": 890},
    "alcateia": {"mensal": 189, "anual": 1890},
    "territorio": {"mensal": 329, "anual": 3290},
}

_CYCLE_MAP = {"mensal": "MONTHLY", "anual": "YEARLY"}


def _headers() -> dict[str, str]:
    return {
        "access_token": settings.asaas_api_key,
        "User-Agent": "BillyPro/1.0 (suporte@appbilly.com.br)",
        "Content-Type": "application/json",
    }


async def create_customer(*, name: str, cpf_cnpj: str, email: str | None) -> dict[str, Any]:
    """cpfCnpj não é exigido pelo Asaas na criação do customer em si —
    confirmado empiricamente — mas é exigido na hora de gerar a cobrança
    (BOLETO/PIX/CREDIT_CARD todos rejeitam sem isso). Por isso o gate de
    CPF/CNPJ roda antes, no router: cpf_cnpj sempre chega preenchido aqui."""
    body: dict[str, Any] = {"name": name, "cpfCnpj": cpf_cnpj}
    if email:
        body["email"] = email
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{ASAAS_BASE_URL}/customers", headers=_headers(), json=body, timeout=15)
        response.raise_for_status()
        return response.json()


def build_external_reference(establishment_id: str, plan_id: str, cycle: str) -> str:
    return f"{establishment_id}:{plan_id}:{cycle}"


def parse_external_reference(value: str) -> tuple[str, str, str] | None:
    parts = value.split(":")
    if len(parts) != 3:
        return None
    return parts[0], parts[1], parts[2]


async def create_subscription(
    *, customer_id: str, plan_id: str, cycle: str, establishment_id: str,
) -> dict[str, Any]:
    """billingType=UNDEFINED — o pagador escolhe boleto/Pix/cartão de
    crédito/débito na fatura hospedada (invoiceUrl) do Payment gerado.
    Confirmado na doc: só cartão de crédito vira recorrência automática de
    verdade (Asaas guarda o cartão do lado deles, cobra sozinho nos ciclos
    seguintes); boleto/Pix/débito geram fatura nova a cada ciclo que o
    pagador precisa pagar de novo."""
    price = PLAN_PRICES[plan_id][cycle]
    body = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": price,
        "nextDueDate": (date.today() + timedelta(days=1)).isoformat(),
        "cycle": _CYCLE_MAP[cycle],
        "externalReference": build_external_reference(establishment_id, plan_id, cycle),
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{ASAAS_BASE_URL}/subscriptions", headers=_headers(), json=body, timeout=15)
        response.raise_for_status()
        return response.json()


async def get_current_invoice_url(subscription_id: str) -> str | None:
    """Fatura em aberto mais recente (PENDING/OVERDUE) da assinatura — pra
    onde o frontend redireciona quando o pagador precisa agir de novo (ex:
    pagou o ciclo passado no boleto, precisa de fatura nova agora)."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{ASAAS_BASE_URL}/subscriptions/{subscription_id}/payments",
            headers=_headers(), params={"limit": 10}, timeout=15,
        )
        response.raise_for_status()
        payments = response.json().get("data", [])
    open_payments = [p for p in payments if p.get("status") in ("PENDING", "OVERDUE")]
    if not open_payments:
        return None
    open_payments.sort(key=lambda p: p.get("dueDate") or "", reverse=True)
    return open_payments[0].get("invoiceUrl")


async def register_webhook(url: str, auth_token: str) -> dict[str, Any]:
    """Setup manual, uma vez só (mesmo espírito do destino de webhook do
    Didit) — não roda por sessão de usuário."""
    body = {
        "name": "Billy Pro — cobrança",
        "url": url,
        "email": "suporte@appbilly.com.br",
        "enabled": True,
        "interrupted": False,
        "authToken": auth_token,
        "sendType": "SEQUENTIALLY",
        "events": ["PAYMENT_CONFIRMED", "PAYMENT_RECEIVED", "PAYMENT_OVERDUE"],
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{ASAAS_BASE_URL}/webhooks", headers=_headers(), json=body, timeout=15)
        response.raise_for_status()
        return response.json()


def verify_webhook_token(token_header: str) -> bool:
    return hmac.compare_digest(token_header or "", settings.asaas_webhook_token)


async def sandbox_confirm_payment(payment_id: str) -> dict[str, Any]:
    """Só funciona no ambiente sandbox — confirma o pagamento de uma
    cobrança sem completar o fluxo real. Usado nos testes, nunca chamado a
    partir de um endpoint do produto."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ASAAS_BASE_URL}/sandbox/payment/{payment_id}/confirm",
            headers=_headers(), json={}, timeout=15,
        )
        response.raise_for_status()
        return response.json()


async def sandbox_force_overdue(payment_id: str) -> dict[str, Any]:
    """Só sandbox — força o vencimento de uma cobrança, pra testar o
    caminho PAYMENT_OVERDUE sem esperar a data real."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{ASAAS_BASE_URL}/sandbox/payment/{payment_id}/overdue",
            headers=_headers(), json={}, timeout=15,
        )
        response.raise_for_status()
        return response.json()
