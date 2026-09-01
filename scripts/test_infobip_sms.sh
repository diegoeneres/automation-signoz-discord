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
  INFOBIP_BASE_URL
  INFOBIP_API_KEY
  INFOBIP_SENDER
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "Variável obrigatória ausente: $variable" >&2
    exit 1
  fi
done

recipients="${SMS_RECIPIENTS:-${TWILIO_SMS_RECIPIENTS:-}}"
recipient="${recipients%%,*}"
recipient="${recipient//[[:space:]]/}"
if [[ -z "$recipient" ]]; then
  echo "Configure SMS_RECIPIENTS" >&2
  exit 1
fi

endpoint="${INFOBIP_BASE_URL%/}/sms/3/messages"
message="Teste local Infobip - automation-signoz-discord - $(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "Enviando SMS de teste via Infobip para $recipient..."

curl --silent --show-error --fail-with-body \
  --request POST "$endpoint" \
  --header "Authorization: App ${INFOBIP_API_KEY}" \
  --header "Content-Type: application/json" \
  --header "Accept: application/json" \
  --data "{\"messages\":[{\"sender\":\"${INFOBIP_SENDER}\",\"destinations\":[{\"to\":\"${recipient}\"}],\"content\":{\"text\":\"${message}\"}}]}"

echo
echo "A API da Infobip aceitou a requisição. Consulte o status pelo messageId retornado."
