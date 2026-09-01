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
  TWILIO_FROM_NUMBER
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Variável obrigatória ausente: $variable" >&2
    exit 1
  fi
done

if [[ -n "${TWILIO_API_KEY_SID:-}" && -n "${TWILIO_API_KEY_SECRET:-}" ]]; then
  auth_username="$TWILIO_API_KEY_SID"
  auth_password="$TWILIO_API_KEY_SECRET"
elif [[ -n "${TWILIO_AUTH_TOKEN:-}" ]]; then
  auth_username="$TWILIO_ACCOUNT_SID"
  auth_password="$TWILIO_AUTH_TOKEN"
else
  echo "Configure TWILIO_AUTH_TOKEN ou TWILIO_API_KEY_SID/TWILIO_API_KEY_SECRET" >&2
  exit 1
fi

recipients="${SMS_RECIPIENTS:-${TWILIO_SMS_RECIPIENTS:-}}"
recipient="${recipients%%,*}"
recipient="${recipient//[[:space:]]/}"
if [[ -z "$recipient" ]]; then
  echo "Configure SMS_RECIPIENTS ou TWILIO_SMS_RECIPIENTS" >&2
  exit 1
fi
api_base_url="${TWILIO_API_BASE_URL:-https://api.twilio.com/2010-04-01}"
message="${TWILIO_SMS_TEMPLATE:-Teste local Twilio - automation-signoz-discord - $(date -u +%Y-%m-%dT%H:%M:%SZ)}"
endpoint="${api_base_url%/}/Accounts/${TWILIO_ACCOUNT_SID}/Messages.json"

echo "Enviando SMS de teste de $TWILIO_FROM_NUMBER para $recipient..."

curl --silent --show-error --fail-with-body \
  --request POST "$endpoint" \
  --user "${auth_username}:${auth_password}" \
  --data-urlencode "From=${TWILIO_FROM_NUMBER}" \
  --data-urlencode "To=${recipient}" \
  --data-urlencode "Body=${message}"

echo
echo "A API do Twilio aceitou a mensagem. Consulte o status pelo SID retornado."
