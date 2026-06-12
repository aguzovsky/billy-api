from datetime import datetime, timedelta, timezone
from uuid import UUID

from anthropic import AsyncAnthropic
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.core.config import settings
from api.models.alert import Alert
from api.models.biometry import Biometric
from api.models.pet import Pet
from api.models.reminder import HealthLog, Reminder

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def build_context(user_id: str, db: AsyncSession) -> str:
    pets_result = await db.execute(select(Pet).where(Pet.owner_id == UUID(user_id)))
    pets = pets_result.scalars().all()
    pet_ids = [p.id for p in pets]
    pets_map = {p.id: p for p in pets}

    bio_result = await db.execute(
        select(Biometric.pet_id).where(Biometric.pet_id.in_(pet_ids))
    )
    pets_with_bio = {row[0] for row in bio_result.all()}

    now = datetime.now(timezone.utc)
    in_30_days = now + timedelta(days=30)
    reminders_result = await db.execute(
        select(Reminder).where(
            and_(
                Reminder.user_id == UUID(user_id),
                Reminder.due_date <= in_30_days,
                Reminder.completed_at.is_(None),
            )
        ).order_by(Reminder.due_date)
    )
    reminders = reminders_result.scalars().all()

    logs_result = await db.execute(
        select(HealthLog)
        .where(HealthLog.user_id == UUID(user_id))
        .order_by(HealthLog.created_at.desc())
        .limit(10)
    )
    health_logs = logs_result.scalars().all()

    if pet_ids:
        alerts_result = await db.execute(
            select(Alert).where(
                and_(Alert.pet_id.in_(pet_ids), Alert.status == "active")
            )
        )
        alerts = alerts_result.scalars().all()
    else:
        alerts = []

    ctx_parts: list[str] = []

    status_labels = {"home": "em casa", "lost": "PERDIDO ⚠️", "found": "encontrado"}
    if pets:
        pet_lines = []
        for p in pets:
            bio_label = "✓ biometria cadastrada" if p.id in pets_with_bio else "sem biometria"
            status_label = status_labels.get(p.status, p.status)
            pet_lines.append(
                f"- {p.name} ({p.species}, {p.breed or 'raça não informada'}, "
                f"{p.gender or 'gênero não informado'}) — {status_label}, {bio_label}"
            )
        ctx_parts.append("PETS DO TUTOR:\n" + "\n".join(pet_lines))
    else:
        ctx_parts.append("PETS DO TUTOR: nenhum pet cadastrado ainda.")

    if reminders:
        r_lines = []
        for r in reminders:
            pet = pets_map.get(r.pet_id)
            pet_name = pet.name if pet else "pet"
            days_until = (r.due_date - now).days
            urgency = "⚠️ VENCIDO" if days_until < 0 else f"em {days_until} dia(s)"
            r_lines.append(f"- [{r.type.upper()}] {r.title} — {pet_name} — {urgency}")
        ctx_parts.append("LEMBRETES PRÓXIMOS (30 dias):\n" + "\n".join(r_lines))
    else:
        ctx_parts.append("LEMBRETES PRÓXIMOS: nenhum lembrete nos próximos 30 dias.")

    if health_logs:
        log_lines = []
        for log in health_logs:
            pet = pets_map.get(log.pet_id)
            pet_name = pet.name if pet else "pet"
            date_str = log.created_at.strftime("%d/%m/%Y")
            excerpt = log.content[:200] + ("..." if len(log.content) > 200 else "")
            log_lines.append(f"- [{date_str}] {pet_name}: {excerpt}")
        ctx_parts.append("DIÁRIO DE SAÚDE (últimas entradas):\n" + "\n".join(log_lines))
    else:
        ctx_parts.append("DIÁRIO DE SAÚDE: nenhuma entrada registrada ainda.")

    if alerts:
        a_lines = []
        for a in alerts:
            pet = pets_map.get(a.pet_id)
            pet_name = pet.name if pet else "pet"
            a_lines.append(
                f"- {pet_name} — alerta: {a.alert_type}"
                f" (desde {a.created_at.strftime('%d/%m/%Y')})"
            )
        ctx_parts.append("ALERTAS ATIVOS:\n" + "\n".join(a_lines))
    else:
        ctx_parts.append("ALERTAS ATIVOS: nenhum alerta ativo.")

    return "\n\n".join(ctx_parts)


async def chat(user_id: str, messages: list[dict], db: AsyncSession) -> str:
    context = await build_context(user_id, db)

    system_prompt = (
        "Você é o Billy, assistente virtual especializado em cuidados de pets. "
        "Você é amigável, empático e direto. Responda sempre em português brasileiro.\n\n"
        "Ao responder perguntas de saúde animal, dê orientações práticas mas sempre recomende "
        "consultar um veterinário para diagnósticos e prescrições. "
        "Para lembretes de vacinas e medicamentos, reforce a importância de manter o calendário em dia.\n\n"
        "LIMITAÇÕES IMPORTANTES:\n"
        "Você não tem acesso à localização do usuário nem à internet.\n"
        "Para perguntas sobre estabelecimentos próximos (pet shops, clínicas, "
        "veterinários, hospitais veterinários, banho e tosa, etc.), NÃO tente "
        "responder com endereços ou nomes específicos.\n"
        "Em vez disso, oriente o usuário a usar a aba \"Serviços\" do Billy, "
        "onde ele pode buscar estabelecimentos próximos com mapa e filtros.\n"
        "Exemplo de resposta: \"Para encontrar clínicas veterinárias perto de "
        "você, use a aba Serviços do Billy — lá você busca por localização "
        "com mapa e avaliações.\"\n\n"
        f"CONTEXTO ATUAL DO TUTOR:\n{context}\n\n"
        "Use este contexto para personalizar suas respostas. "
        "Chame os pets pelo nome quando relevante. "
        "Se um pet estiver marcado como PERDIDO, demonstre empatia e ofereça orientações práticas."
    )

    response = await _get_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=system_prompt,
        messages=messages,
    )

    return response.content[0].text
