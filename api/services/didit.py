"""Integração com o Didit (KYC — BIL-46). Doc: docs.didit.me."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from api.core.config import settings

_log = logging.getLogger(__name__)

DIDIT_SESSION_URL = "https://verification.didit.me/v3/session/"


async def create_kyc_session(vendor_data: str, callback: str) -> dict[str, Any]:
    """Cria uma sessão de verificação no Didit. vendor_data é o
    establishment_id — é o que volta no webhook pra correlacionar de volta.
    Chamar de novo com o mesmo vendor_data numa sessão ainda não terminada
    devolve a mesma sessão (idempotente do lado do Didit)."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            DIDIT_SESSION_URL,
            headers={"x-api-key": settings.didit_api_key},
            json={
                "workflow_id": settings.didit_workflow_id,
                "vendor_data": vendor_data,
                "callback": callback,
            },
            timeout=15,
        )
        response.raise_for_status()
        return response.json()


def _shorten_floats(value: Any) -> Any:
    """Normaliza floats de valor inteiro pra int — mesma normalização que o
    Didit aplica antes de assinar (ver doc do X-Signature-V2), senão a
    verificação nunca bate."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: _shorten_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten_floats(v) for v in value]
    return value


def verify_webhook_signature(body_json: Any, signature_header: str, timestamp_header: str) -> bool:
    """Algoritmo exato da doc do Didit (X-Signature-V2): JSON canônico
    (chaves ordenadas, separadores compactos, unicode preservado) assinado
    com HMAC-SHA256, comparação em tempo constante. Timestamp precisa estar
    dentro de 300s pra evitar replay."""
    try:
        if abs(int(time.time()) - int(timestamp_header)) > 300:
            return False
    except (TypeError, ValueError):
        return False

    canonical = json.dumps(
        _shorten_floats(body_json),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected = hmac.new(
        settings.didit_webhook_secret.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, expected)


# BIL-46 — mapeamento dos ~10 status do Didit pros 4 estados do produto
# (nao_iniciado/pendente/aprovado/reprovado). Expired/Abandoned viram
# nao_iniciado (ninguém decidiu nada, deixa tentar de novo do zero) em vez
# de reprovado — "reprovado" no produto significa "verificação recusada",
# o que seria falso pra quem só não terminou o fluxo.
DIDIT_STATUS_MAP: dict[str, str] = {
    "Approved": "aprovado",
    "Declined": "reprovado",
    "In Progress": "pendente",
    "In Review": "pendente",
    "Not Started": "pendente",
    "Awaiting User": "pendente",
    "Resubmitted": "pendente",
    "Expired": "nao_iniciado",
    "Abandoned": "nao_iniciado",
    "Kyc Expired": "nao_iniciado",
}
