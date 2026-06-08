# Modal Cost Safety — Billy App

## O Incidente (Junho 2026)

**Custo:** $95.93 em um mês ($93.82 somente de T4 GPU)

**Causa raiz:**

O backend tinha um loop em `api/main.py` (`_keep_modal_warm`) que acordava a cada
4 minutos e chamava `GET /biometry/warmup` → Modal `extract_embedding_warmup` →
`PetReIDModelFast().embed.remote(dummy)` → **GPU T4 ativa**.

Combinado com `scaledown_window=300` (5 minutos de idle), a GPU **nunca desligou**:

```
[Loop backend]  a cada 4min  →  [Modal warmup]  →  [GPU T4 sobe]
                                                     ↓ 5min idle
[Loop backend]  a cada 4min  →  [Modal warmup]  →  [GPU T4 permanece viva]
                                                     (nunca chegou a 5min idle)
```

284 chamadas de warmup × GPU quase contínua = ~$93/mês de T4 em background.

---

## Arquitetura Atual (scale-to-zero)

```
Usuário abre scanner
        ↓
Flutter → GET /api/v1/biometry/warmup   ← no-op, retorna {"status":"ok"} imediatamente
                                          (nenhuma GPU é iniciada aqui)

Usuário tira foto e confirma
        ↓
Flutter → POST /api/v1/biometry/register ou /identify
        ↓
Backend → POST modal_endpoint_url (extract_embedding_fast)
        ↓
Modal sobe container GPU T4 sob demanda (cold start 30–60s)
        ↓
Embedding retornado
        ↓
Após 20s sem novas chamadas → GPU desliga automaticamente
```

**Custo estimado MVP (baixo volume):** $0–5/mês

---

## Configuração Obrigatória para GPU no MVP

```python
@app.cls(
    gpu="T4",
    container_idle_timeout=20,   # desliga após 20s idle
    timeout=180,                 # max por chamada
    min_containers=0,            # NUNCA colocar 1 aqui
    secrets=[aws_secret],
)
```

---

## Checklist antes de `modal deploy`

- [ ] Nenhuma função/classe GPU com `min_containers=1`
- [ ] Nenhum warmup automático (loop, cron, schedule) chamando GPU
- [ ] Nenhum `scaledown_window` alto (>60s) em funções GPU
- [ ] `container_idle_timeout` baixo (máx 30s para MVP)
- [ ] Nenhum `keep_warm` ou `buffer_containers` em GPU
- [ ] Budget configurado no dashboard Modal (Settings → Spending Limits)
- [ ] Após o deploy, verificar Live Containers no dashboard → deve estar 0

---

## Configurações Proibidas no MVP

| Configuração | Por quê é perigosa |
|---|---|
| `min_containers=1` em GPU | T4 fica viva 24/7 → ~$70/mês mínimo |
| `scaledown_window=300` | 5min de GPU idle após cada call |
| Loop/cron chamando GPU | Mantém GPU quente perpetuamente |
| `buffer_containers=1` | Reserva GPU permanente |
| `keep_warm=1` | Alias para min_containers=1 |

---

## Comandos úteis

### Verificar containers ativos agora
```bash
modal app list
modal container list
```

### Parar o app imediatamente (para toda GPU)
```bash
modal app stop billy-reid
```

### Reiniciar o app (sem GPU idle)
```bash
modal deploy modal_reid.py
```

### Testar uma chamada manualmente (sobe GPU sob demanda)
```bash
modal run modal_reid.py
```

### Ver custo do período atual
Acesse: https://modal.com/settings/billing

---

## Como verificar se containers estão vivos

1. Acesse https://modal.com/apps/billy-reid
2. Clique em "Functions"
3. Coluna "Live Containers" deve mostrar **0** quando não há requisições
4. Se mostrar 1+ sem requisições ativas → algo está fazendo warmup

---

## Variáveis de ambiente no Railway

| Variável | Função |
|---|---|
| `MODAL_ENDPOINT_URL` | URL do `extract_embedding_fast` (endpoint principal) |
| `MODAL_WARMUP_URL` | **Não mais usada** — pode ser removida do Railway |

---

## O que NÃO fazer nunca

```python
# ❌ PROIBIDO — mantém GPU viva 24/7
@app.cls(gpu="T4", min_containers=1)

# ❌ PROIBIDO — warmup automático
@app.function(schedule=modal.Period(minutes=4))
def warmup(): PetReIDModelFast().embed.remote(dummy)

# ❌ PROIBIDO — loop no backend
async def _keep_modal_warm():
    while True:
        await asyncio.sleep(240)
        await warmup()
```
