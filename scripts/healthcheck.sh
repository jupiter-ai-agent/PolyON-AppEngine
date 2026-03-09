#!/bin/bash
set -e

# Odoo /web/health 엔드포인트를 체크하는 간단한 스크립트

HEALTH_URL="${1:-http://localhost:8069/web/health}"

echo "헬스 체크 URL: ${HEALTH_URL}"

http_code=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}")

if [ "$http_code" = "200" ]; then
  echo "Odoo 헬스 체크 성공 (HTTP 200)"
  exit 0
else
  echo "Odoo 헬스 체크 실패 (HTTP ${http_code})" >&2
  exit 1
fi

