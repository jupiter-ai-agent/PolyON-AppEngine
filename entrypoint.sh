#!/bin/bash
set -e

# PRC 환경변수로부터 odoo.conf를 생성하고 Odoo를 기동하는 엔트리포인트

ODOO_CONF_PATH="/etc/odoo/odoo.conf"
ODOO_CONF_TEMPLATE_PATH="/etc/odoo/odoo.conf.template"

# odoo.conf 템플릿이 존재하는지 확인
if [ ! -f "$ODOO_CONF_TEMPLATE_PATH" ]; then
  echo "odoo.conf 템플릿이 존재하지 않습니다: $ODOO_CONF_TEMPLATE_PATH" >&2
  exit 1
fi

# REDIS_URL 이 존재하면 세션용 Redis 설정을 파싱해서 환경변수로 노출
if [ -n "$REDIS_URL" ]; then
  parsed_host=$(python3 - <<EOF
import os
from urllib.parse import urlparse

url = os.getenv("REDIS_URL", "")
if not url:
    raise SystemExit(0)
parsed = urlparse(url)
host = parsed.hostname or ""
port = parsed.port or 6379
dbindex = (parsed.path or "").lstrip("/") or "0"
print(f"{host} {port} {dbindex}")
EOF
)
  if [ -n "$parsed_host" ]; then
    SESSION_REDIS_HOST=$(echo "$parsed_host" | awk '{print $1}')
    SESSION_REDIS_PORT=$(echo "$parsed_host" | awk '{print $2}')
    SESSION_REDIS_DBINDEX=$(echo "$parsed_host" | awk '{print $3}')
    export SESSION_REDIS_HOST SESSION_REDIS_PORT SESSION_REDIS_DBINDEX
  fi
fi

# 환경변수를 사용하여 odoo.conf 생성
# 템플릿 안에서 ${VAR} 형식으로 치환됨
envsubst < "$ODOO_CONF_TEMPLATE_PATH" > "$ODOO_CONF_PATH"

# Redis 설정이 비어 있으면 해당 설정 라인을 제거한다
if [ -z "$SESSION_REDIS_HOST" ]; then
  sed -i '/session_redis_host/d' "$ODOO_CONF_PATH"
  sed -i '/session_redis_port/d' "$ODOO_CONF_PATH"
  sed -i '/session_redis_dbindex/d' "$ODOO_CONF_PATH"
fi

# SMTP 설정이 비어 있으면 SMTP 관련 설정 라인을 제거한다
if [ -z "$SMTP_HOST" ]; then
  sed -i '/^smtp_server/d' "$ODOO_CONF_PATH"
  sed -i '/^smtp_port/d' "$ODOO_CONF_PATH"
  sed -i '/^smtp_user/d' "$ODOO_CONF_PATH"
  sed -i '/^smtp_password/d' "$ODOO_CONF_PATH"
  sed -i '/^smtp_ssl/d' "$ODOO_CONF_PATH"
fi

# 값이 완전히 비어 있는 설정 라인을 마지막으로 한 번 더 정리한다
sed -i '/= $/d' "$ODOO_CONF_PATH"

echo "생성된 odoo.conf:"
sed -e 's/password = .*/password = ****/g' -e 's:aws_secret_access_key = .*:aws_secret_access_key = ****:g' "$ODOO_CONF_PATH" || true

# DB 준비 대기
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
  echo "PostgreSQL 접속 가능 여부를 확인합니다: ${DB_HOST}:${DB_PORT}"
  attempt_count=0
  max_attempt_count=30
  wait_seconds_between_attempts=2

  until pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "${DB_USER:-postgres}" >/dev/null 2>&1; do
    attempt_count=$((attempt_count + 1))
    if [ "$attempt_count" -ge "$max_attempt_count" ]; then
      echo "PostgreSQL 준비 대기 시간이 초과되었습니다." >&2
      exit 1
    fi
    echo "PostgreSQL 준비 중... (${attempt_count}/${max_attempt_count})"
    sleep "$wait_seconds_between_attempts"
  done
fi

ODOO_BIN="${ODOO_HOME}/odoo-bin"

echo "Odoo 초기화를 수행합니다..."
odoo_initial_modules="base,auth_ldap,polyon_ldap_auto,polyon_s3_attachment,polyon_redis_session"

python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" -i "$odoo_initial_modules" --stop-after-init || true

echo "Odoo를 기동합니다..."
exec python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH"

