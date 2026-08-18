# SigNoz → Discord → Jira

Serviço FastAPI que recebe alertas do SigNoz, publica cada alerta por um webhook do Discord e adiciona o botão **Criar ticket no Jira**. O clique cria uma issue no Jira Cloud e abre o ticket no navegador.

## Fluxo

1. O SigNoz envia um payload compatível com Alertmanager para `POST /webhooks/signoz`.
2. O serviço persiste o alerta no SQLite e publica um embed usando o webhook do Discord.
3. O botão contém um link assinado para o FastAPI.
4. O usuário clica no botão, o serviço cria a issue e redireciona o navegador para o Jira.
5. Cliques posteriores no mesmo alerta retornam o ticket existente.

Quando um alerta ativo possui o label `severity=critical`, o serviço também envia um SMS pela Zenvia. O estado do envio fica persistido no SQLite para impedir SMS duplicados em retries do SigNoz.

Alertas com status `resolved` são enviados sem o botão de criação.

## Executar com Docker

```bash
cp .env.example .env
# Preencha todos os valores em .env
docker compose up --build
```

Teste a saúde:

```bash
curl http://localhost/health
```

Em produção, publique o serviço por HTTPS e preserve o volume `service-data`.

## Configurar as integrações

### Discord

1. No canal desejado, abra **Editar canal → Integrações → Webhooks**.
2. Crie um webhook e copie sua URL.
3. Informe a URL em `DISCORD_WEBHOOK_URL` no `.env`.
4. Configure `PUBLIC_BASE_URL` com a URL HTTPS pública deste serviço.
5. Gere um valor longo e aleatório para `TICKET_SIGNING_SECRET`.

Não é necessário criar uma aplicação ou bot no Discord. O serviço envia o parâmetro `with_components=true`, necessário para o webhook respeitar o botão-link. Somente links assinados pelo serviço conseguem acionar a criação de tickets.

### Jira Cloud

1. Gere um token em [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. Informe a URL do site, e-mail, token, chave do projeto e tipo da issue no `.env`.
3. Garanta que o usuário do token tenha as permissões **Browse Projects** e **Create Issues** nesse projeto.

O campo `description` é enviado em Atlassian Document Format, exigido pela API v3.

### Zenvia SMS

1. Ative o canal SMS e crie um token no console da Zenvia.
2. Identifique o alias da conta SMS configurada na plataforma.
3. Configure no `.env`:

```env
ZENVIA_ENABLED=true
ZENVIA_API_TOKEN=seu_token
ZENVIA_SMS_FROM=seu_alias_sms
ZENVIA_SMS_RECIPIENTS=5511999999999,5521999999999
```

Os destinatários devem conter o número completo, incluindo DDI, somente com dígitos. Para desabilitar o envio sem remover as credenciais, use `ZENVIA_ENABLED=false`.

O SMS contém apenas criticidade, resumo do alerta, serviço e horário de início. A mensagem é normalizada para caracteres ASCII e limitada a 160 caracteres para permanecer em um único segmento SMS.

A regra considera crítico um alerta ainda não resolvido cujo payload contenha:

```json
{"labels": {"severity": "critical"}}
```

O envio usa `POST https://api.zenvia.com/v2/channels/sms/messages` e autenticação pelo header `X-API-TOKEN`.

### SigNoz

1. Abra **Settings → Account Settings → Notification Channels → New Channel → Webhook**.
2. Use `https://alertas.dnrxconsultoria.com/webhooks/signoz` como URL.
3. No campo de senha/token do webhook, configure o valor de `SIGNOZ_WEBHOOK_TOKEN` como Bearer token. O header recebido deve ser:

   `Authorization: Bearer SEU_SEGREDO`

Se sua versão/configuração do SigNoz só oferecer Basic Auth e não enviar Bearer diretamente, coloque um proxy reverso na frente do serviço para converter a credencial em `Authorization: Bearer ...`.

Teste manualmente:

```bash
curl -X POST https://alertas.dnrxconsultoria.com/webhooks/signoz \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer SEU_SEGREDO' \
  -d '{
    "status": "firing",
    "alerts": [{
      "status": "firing",
      "labels": {"alertname": "HighCPU", "severity": "critical", "service": "checkout"},
      "annotations": {"summary": "CPU alta", "description": "CPU acima de 90% por 5 minutos"},
      "startsAt": "2026-08-05T12:00:00Z",
      "generatorURL": "https://signoz.example.com/alerts/123",
      "fingerprint": "highcpu-checkout-20260805"
    }]
  }'
```

## Desenvolvimento local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
pytest
uvicorn app.main:app --reload
```

Para o Discord e o SigNoz alcançarem sua máquina, exponha a porta 80 por HTTPS com o túnel de sua preferência.

## Endpoints

- `GET /health` — health check.
- `POST /webhooks/signoz` — recebe alertas; exige Bearer token.
- `GET /tickets/{id}/create` — cria ou abre o ticket; exige assinatura válida no link.
- `GET /docs` — documentação OpenAPI do FastAPI.
