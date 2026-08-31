#!/usr/bin/env bash

set -euo pipefail

env_file="${1:-.env}"

if [[ ! -f "$env_file" ]]; then
  echo "Arquivo de ambiente não encontrado: $env_file" >&2
  echo "Uso: $0 [caminho-do-.env]" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

required_variables=(
  TWILIO_ACCOUNT_SID
  TWILIO_API_KEY_SID
  TWILIO_API_KEY_SECRET
  TWILIO_FROM_NUMBER
  TWILIO_SMS_RECIPIENTS
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Variável obrigatória ausente: $variable" >&2
    exit 1
  fi
done

recipient="${TWILIO_SMS_RECIPIENTS%%,*}"
recipient="${recipient//[[:space:]]/}"
api_base_url="${TWILIO_API_BASE_URL:-https://api.twilio.com/2010-04-01}"
message="Teste local Twilio - automation-signoz-discord - $(date -u +%Y-%m-%dT%H:%M:%SZ)"
endpoint="${api_base_url%/}/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json"

echo "Enviando SMS de teste de $TWILIO_FROM_NUMBER para $recipient..."

curl --silent --show-error --fail-with-body \
  --request POST "$endpoint" \
  --user "${TWILIO_API_KEY_SID}:${TWILIO_API_KEY_SECRET}" \
  --data-urlencode "From=${TWILIO_FROM_NUMBER}" \
  --data-urlencode "To=${recipient}" \
  --data-urlencode "Body=${message}"

echo
echo "A API do Twilio aceitou a mensagem. Consulte o status pelo SID retornado."
