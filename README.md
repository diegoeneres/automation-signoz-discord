# SigNoz → Discord → Jira

Serviço FastAPI que recebe alertas do SigNoz, publica cada alerta por um webhook do Discord e adiciona o botão **Criar ticket no Jira**. O clique cria uma issue no Jira Cloud e abre o ticket no navegador.

## Fluxo

1. O SigNoz envia um payload compatível com Alertmanager para `POST /webhooks/signoz`.
2. O serviço persiste o alerta no SQLite e publica um embed usando o webhook do Discord.
3. O botão contém um link assinado para o FastAPI.
4. O usuário clica no botão, o serviço cria a issue e redireciona o navegador para o Jira.
5. Cliques posteriores no mesmo alerta retornam o ticket existente.

Quando um alerta ativo possui o label `severity=critical`, o serviço também envia um SMS pelo Twilio. O estado do envio fica persistido no SQLite para impedir SMS duplicados em retries do SigNoz.

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

### Imagem no GitHub Container Registry

Todo push na branch `main`, incluindo merges de pull requests, executa a pipeline
`.github/workflows/docker-publish.yml`. Ela publica a imagem no GHCR com duas tags:

- `latest`, apontando para a publicação mais recente;
- `sha-<commit>`, identificando de forma imutável o commit usado no build.

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
4. Configure `PUBLIC_BASE_URL` com a URL HTTPS pública deste serviço.
5. Gere um valor longo e aleatório para `TICKET_SIGNING_SECRET`.

Não é necessário criar uma aplicação ou bot no Discord. O serviço envia o parâmetro `with_components=true`, necessário para o webhook respeitar o botão-link. Somente links assinados pelo serviço conseguem acionar a criação de tickets.

### Jira Cloud

1. Gere um token em [Atlassian API tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. Informe a URL do site, e-mail, token, chave do projeto e tipo da issue no `.env`.
3. Garanta que o usuário do token tenha as permissões **Browse Projects** e **Create Issues** nesse projeto.

O campo `description` é enviado em Atlassian Document Format, exigido pela API v3.

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
TWILIO_AUTH_TOKEN=seu_auth_token
TWILIO_FROM_NUMBER=+15551234567
TWILIO_SMS_RECIPIENTS=+5511999999999,+5521999999999
```

Essa configuracao com `Account SID` e `Auth Token` corresponde ao exemplo de
teste exibido no console da Twilio. Em producao, voce tambem pode usar uma API
Key definindo `TWILIO_API_KEY_SID` e `TWILIO_API_KEY_SECRET`; quando os dois
estiverem preenchidos, eles tem prioridade sobre `TWILIO_AUTH_TOKEN`.

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
`TWILIO_SMS_RECIPIENTS`. Outro arquivo pode ser informado como argumento:

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

## Endpoints

- `GET /health` — health check.
- `POST /webhooks/signoz` — recebe alertas; exige Bearer token.
- `GET /tickets/{id}/create` — cria ou abre o ticket; exige assinatura válida no link.
- `GET /docs` — documentação OpenAPI do FastAPI.
