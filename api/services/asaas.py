"""Integração com o Asaas (cobrança recorrente — assinatura Billy Pro).
Doc: docs.asaas.com.

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

# BIL-129 — só produção usa api.asaas.com de verdade (dinheiro real).
# Qualquer outro APP_ENV (staging, development, ou não setado) cai em
# sandbox por padrão — nunca o contrário, o erro seguro aqui é sandbox
# de mais, não produção de menos.
ASAAS_BASE_URL = "https://api.asaas.com/v3" if settings.app_env == "production" else "https://api-sandbox.asaas.com/v3"

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
    *, customer_id: str, plan_id: str, cycle: str, establishment_id: str, success_url: str,
) -> dict[str, Any]:
    """billingType=UNDEFINED — o pagador escolhe boleto/Pix/cartão de
    crédito/débito na fatura hospedada (invoiceUrl) do Payment gerado.
    Confirmado na doc: só cartão de crédito vira recorrência automática de
    verdade (Asaas guarda o cartão do lado deles, cobra sozinho nos ciclos
    seguintes); boleto/Pix/débito geram fatura nova a cada ciclo que o
    pagador precisa pagar de novo.

    callback.successUrl (confirmado em docs.asaas.com/docs/
    redirecionamento-apos-o-pagamento) — sem isso o pagador fica preso na
    fatura do Asaas depois de pagar, sem link de volta. autoRedirect=True
    só funciona de fato pra cartão/Pix (confirmação instantânea); boleto
    sempre cai no botão manual "Ir para o site" independente disso.

    Testado empiricamente: sem nenhum domínio cadastrado na conta do Asaas
    (BIL-125, ação manual do Alexandre, ainda pendente), a API rejeita a
    criação da assinatura INTEIRA com 400 se `callback` estiver presente —
    não é "cria mas ignora o campo". Por isso tenta com callback primeiro
    e cai pra sem callback só nesse erro específico: assinar continua
    funcionando hoje, e o redirect passa a funcionar sozinho assim que o
    domínio for cadastrado, sem precisar de deploy novo."""
    price = PLAN_PRICES[plan_id][cycle]
    base_body: dict[str, Any] = {
        "customer": customer_id,
        "billingType": "UNDEFINED",
        "value": price,
        "nextDueDate": (date.today() + timedelta(days=1)).isoformat(),
        "cycle": _CYCLE_MAP[cycle],
        "externalReference": build_external_reference(establishment_id, plan_id, cycle),
    }
    body_with_callback = {**base_body, "callback": {"successUrl": success_url, "autoRedirect": True}}

    async with httpx.AsyncClient() as client:
        response = await client.post(f"{ASAAS_BASE_URL}/subscriptions", headers=_headers(), json=body_with_callback, timeout=15)
        if response.status_code == 400 and _is_domain_not_configured_error(response):
            _log.warning(
                "Asaas rejeitou callback.successUrl (domínio não cadastrado na conta — BIL-125 pendente); "
                "criando assinatura sem callback."
            )
            response = await client.post(f"{ASAAS_BASE_URL}/subscriptions", headers=_headers(), json=base_body, timeout=15)
        response.raise_for_status()
        return response.json()


def _is_domain_not_configured_error(response: httpx.Response) -> bool:
    try:
        body = response.json()
    except ValueError:
        return False
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(e, dict) and e.get("code") == "invalid_object" and "domínio configurado" in (e.get("description") or "")
        for e in errors
    )


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


def parse_error_message(response: httpx.Response) -> str | None:
    """Se o corpo do erro do Asaas tiver `errors: [{code, description}]`
    com algum invalid_object (ex: "CPF/CNPJ inválido"), devolve as
    descrições concatenadas — mensagem acionável pro usuário em vez do
    502 genérico. None se o corpo não tiver esse formato reconhecido
    (aí quem chama cai no fallback genérico)."""
    try:
        body = response.json()
    except ValueError:
        return None
    errors = body.get("errors")
    if not isinstance(errors, list) or not errors:
        return None
    descriptions = [
        e.get("description") for e in errors
        if isinstance(e, dict) and e.get("code") == "invalid_object" and e.get("description")
    ]
    if not descriptions:
        return None
    return " ".join(descriptions)


def verify_webhook_token(token_header: str) -> bool:
    if not settings.asaas_webhook_token:
        _log.warning("ASAAS_WEBHOOK_TOKEN não configurado — recusando verificação de webhook.")
        return False
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
