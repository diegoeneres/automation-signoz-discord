# SigNoz → Discord e SMS

Serviço FastAPI que recebe alertas do SigNoz e publica cada alerta no Discord, com envio opcional de SMS para alertas críticos.

## Fluxo

1. O SigNoz envia um payload compatível com Alertmanager para `POST /webhooks/signoz`.
2. O serviço persiste o alerta no SQLite e publica um embed usando o webhook do Discord.

Quando um alerta ativo possui o label `severity=critical`, o serviço também envia um SMS pela Twilio. O estado do envio fica persistido no SQLite para impedir SMS duplicados em retries do SigNoz.

Alertas com status `resolved` continuam sendo publicados no Discord, sem envio de SMS.

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

### Imagem no GitHub Container Registry

Ao criar e enviar uma tag de versão como `v1.0.0` (ou `v.1.0.0`), a pipeline
`.github/workflows/docker-publish.yml` publica a imagem no GHCR com três tags:

- a própria tag de versão, como `v1.0.0`;
- `latest`, apontando para a publicação mais recente;
- `sha-<commit>`, identificando de forma imutável o commit usado no build.

Exemplo de publicação:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Para baixar a versão mais recente:

```bash
docker pull ghcr.io/diegoeneres/automation-signoz-discord:latest
```

Pacotes privados exigem autenticação prévia com `docker login ghcr.io`. A publicação
usa o `GITHUB_TOKEN` fornecido automaticamente pelo GitHub Actions, sem necessidade
de cadastrar outro token no repositório.

Em produção, publique o serviço por HTTPS e preserve o volume `service-data`.

## Configurar as integrações

### Discord

1. No canal desejado, abra **Editar canal → Integrações → Webhooks**.
2. Crie um webhook e copie sua URL.
3. Informe a URL em `DISCORD_WEBHOOK_URL` no `.env`.

Não é necessário criar uma aplicação ou bot no Discord.

### Twilio SMS

1. No console do Twilio, copie o **Account SID**.
2. Em **Settings → Account settings → API keys & auth tokens**, crie uma API Key
   Standard e guarde o **API Key SID** e o **API Key Secret**. O secret é exibido
   somente no momento da criação.
3. Adquira ou selecione um número Twilio habilitado para SMS.
4. Informe os números no formato E.164, incluindo `+`, DDI e DDD.
5. Configure no `.env`:

```env
TWILIO_ENABLED=true
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_API_KEY_SECRET=seu_api_key_secret
TWILIO_FROM_NUMBER=+15551234567
SMS_RECIPIENTS=+5511999999999,+5521999999999
TWILIO_SMS_TEMPLATE=sms_internal_alerts
```

Também é possível autenticar com `TWILIO_AUTH_TOKEN`; quando a API Key SID e o
API Key Secret estão preenchidos, eles têm prioridade sobre o Auth Token.

Contas trial recentes somente aceitam templates SMS predefinidos. Nesse caso,
informe em `TWILIO_SMS_TEMPLATE` o nome exato mostrado no console da Twilio,
como `sms_internal_alerts`. O template substitui a mensagem dinamica do alerta.
Ao fazer upgrade para acesso completo, remova ou deixe essa variavel vazia para
voltar a enviar criticidade, host, usuario, servico e horario no corpo do SMS.

O número em `TWILIO_FROM_NUMBER` precisa pertencer à mesma conta Twilio e estar
habilitado para SMS. Contas trial somente enviam para destinatários previamente
verificados. Para desabilitar o envio sem remover as credenciais, use
`TWILIO_ENABLED=false`.

Para testar as credenciais e o envio diretamente pela API do Twilio, sem passar
pelo webhook do SigNoz:

```bash
./scripts/test_twilio_sms.sh
```

Por padrão, o script carrega o `.env` e envia para o primeiro número definido em
`SMS_RECIPIENTS` (ou na variável legada `TWILIO_SMS_RECIPIENTS`). Outro arquivo pode ser informado como argumento:

```bash
./scripts/test_twilio_sms.sh /caminho/para/.env
```

O SMS contém criticidade, `userid`, `host.name`, resumo do alerta, serviço e horário de início. A mensagem é normalizada para caracteres ASCII e limitada a 160 caracteres para permanecer em um único segmento SMS.

Modelo da mensagem enviada:

```text
CRITICAL SigNoz; userid: <userid>; host.name: <host>; alerta: <resumo>; servico: <servico>; inicio: <data e hora>
```

Exemplo:

```text
CRITICAL SigNoz; userid: usuario-123; host.name: checkout-01; alerta: CPU alta; servico: checkout; inicio: 2026-08-18T10:00:00Z
```

O resumo vem de `annotations.summary` ou, quando ausente, de `labels.alertname`.
O serviço vem de `labels.service` ou, como alternativa, de `labels.job`. O host e o
usuário são obtidos diretamente de `labels["host.name"]` e `labels.userid`, conforme
a estrutura do alerta no SigNoz. Campos sem valor são preenchidos com `n/a`, e o
conteúdo excedente é truncado no limite de 160 caracteres.

A regra considera crítico um alerta ainda não resolvido cujo payload contenha:

```json
{"labels": {"severity": "critical"}}
```

O envio usa `POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json`,
com autenticação HTTP Basic pelo API Key SID e API Key Secret. O Account SID
continua sendo usado para identificar a conta na URL.

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

## Observabilidade da aplicação no SigNoz

A aplicação envia traces das requisições FastAPI, integrações externas e operações
SQLite, logs correlacionados aos traces e métricas via OTLP/HTTP. Configure no `.env`:

```env
OTEL_SERVICE_NAME=signoz-discord-jira
OTEL_EXPORTER_OTLP_ENDPOINT=https://ingest.<region>.signoz.cloud:443
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS=signoz-ingestion-key=SEU_TOKEN
OTEL_EXPORTER_OTLP_COMPRESSION=gzip
OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE=delta
OTEL_METRIC_EXPORT_INTERVAL=60000
OTEL_LOG_LEVEL=INFO
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=production,service.version=0.4.0
```

Copie o endpoint regional e a ingestion key em **Settings → Ingestion Settings**
no SigNoz Cloud. Não acrescente `/v1/traces`, `/v1/metrics` ou `/v1/logs` ao
endpoint: o exporter OTLP/HTTP adiciona esses caminhos automaticamente. A chave
de ingestão deve permanecer apenas no `.env`, que não é incluído na imagem.

Sem `OTEL_EXPORTER_OTLP_ENDPOINT` (ou com `OTEL_SDK_DISABLED=true`), a instrumentação
fica desativada. As métricas de negócio são `app.alerts.received`,
`app.notifications.sent` e `app.notifications.failures`.
Também são exportadas métricas HTTP do FastAPI e métricas de processo e runtime,
como uso de CPU, memória e garbage collection. Logs emitidos pelos módulos `app.*`
são enviados com `trace_id` e `span_id`, permitindo navegar do log para o trace.
Os logs de processamento incluem os atributos estruturados `event.name`, `event.outcome`,
`alert.id`, `alert.name`, `alert.severity`, `client.id` e `notification.channel`. O cliente
é obtido do primeiro label disponível entre `client`, `cliente`, `customer`,
`customer_id`, `host.name` e `userid`.

Os traces possuem spans específicos para cada destino externo:

- `notification.discord.send` — envio do alerta ao Discord;
- `notification.sms.send` — operação completa de envio de SMS;
- `notification.sms.provider.send` — tentativa de envio pela Twilio;
- `external.twilio.http` — chamada HTTP à Twilio.

Use `external.system`, `server.address`, `notification.channel`, `event.outcome`,
`alert.name`, `alert.severity` e `client.id` para filtrar os spans. URLs completas de
webhooks, credenciais e números de telefone não são adicionados aos spans customizados.

## Endpoints

- `GET /health` — health check.
- `POST /webhooks/signoz` — recebe alertas; exige Bearer token.
- `GET /docs` — documentação OpenAPI do FastAPI.
