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

# 환경변수를 사용하여 odoo.conf 생성
# 템플릿 안에서 ${VAR} 형식으로 치환됨
envsubst < "$ODOO_CONF_TEMPLATE_PATH" > "$ODOO_CONF_PATH"

# OIDC 환경변수가 없으면 Odoo 기동을 차단한다
if [ -z "$OIDC_ISSUER" ] || [ -z "$OIDC_CLIENT_ID" ] || [ -z "$OIDC_AUTH_ENDPOINT" ] || [ -z "$OIDC_TOKEN_ENDPOINT" ] || [ -z "$OIDC_JWKS_URI" ]; then
  echo "OIDC 환경변수가 설정되지 않았습니다. PP 제1원칙에 따라 Odoo 기동을 중단합니다." >&2
  exit 1
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
odoo_initial_modules="base,auth_ldap,auth_oauth,polyon_s3_attachment,polyon_oidc,polyon_iframe,polyon_ldap"

python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" -i "$odoo_initial_modules" --stop-after-init || true

echo "Odoo를 기동합니다..."
exec python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" -d "${DB_NAME:-polyon_odoo}"

