#!/bin/bash
set -e

# PRC 환경변수로부터 odoo.conf를 생성하고 Odoo를 기동하는 엔트리포인트
# v0.5.11: DB 최초 초기화 여부를 감지하여 모듈 설치/설정 주입을 자기 초기화 구조로 전환

ODOO_CONF_PATH="/etc/odoo/odoo.conf"
ODOO_CONF_TEMPLATE_PATH="/etc/odoo/odoo.conf.template"

# 1. odoo.conf 템플릿이 존재하는지 확인
if [ ! -f "$ODOO_CONF_TEMPLATE_PATH" ]; then
  echo "odoo.conf 템플릿이 존재하지 않습니다: $ODOO_CONF_TEMPLATE_PATH" >&2
  exit 1
fi

# 환경변수를 사용하여 odoo.conf 생성
# 템플릿 안에서 ${VAR} 형식으로 치환됨
envsubst < "$ODOO_CONF_TEMPLATE_PATH" > "$ODOO_CONF_PATH"

# 2. OIDC 환경변수가 없으면 Odoo 기동을 차단한다
if [ -z "$OIDC_ISSUER" ] || [ -z "$OIDC_CLIENT_ID" ] || [ -z "$OIDC_AUTH_ENDPOINT" ] || [ -z "$OIDC_TOKEN_ENDPOINT" ] || [ -z "$OIDC_JWKS_URI" ]; then
  echo "OIDC 환경변수가 설정되지 않았습니다. PP 제1원칙에 따라 Odoo 기동을 중단합니다." >&2
  exit 1
fi

# 3. SMTP 설정이 비어 있으면 SMTP 관련 설정 라인을 제거한다
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

# 4. DB 준비 대기
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

# 5. DB 최초 초기화 여부 확인 (res_users 테이블 존재 여부)
# 핵심: 재시작 시 중복 실행을 방지하기 위해 DB 초기화 상태를 감지
DB_INITIALIZED=false
if PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
   -c "SELECT 1 FROM res_users LIMIT 1" >/dev/null 2>&1; then
  DB_INITIALIZED=true
  echo "[PolyON] DB 이미 초기화됨 — 모듈 설치 건너뜀"
else
  echo "[PolyON] DB 최초 초기화 시작..."
fi

# 6. 최초 초기화: 모듈 설치 및 설정 주입
if [ "$DB_INITIALIZED" = "false" ]; then
  odoo_modules="base,auth_ldap,auth_oauth,polyon_s3_attachment,polyon_oidc,polyon_iframe,polyon_ldap_connector"
  echo "[PolyON] 모듈 설치: $odoo_modules"
  python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" \
    -d "${DB_NAME}" \
    -i "$odoo_modules" \
    --no-http --stop-after-init
  echo "[PolyON] 모듈 설치 완료"

  # admin 비밀번호를 ODOO_ADMIN_PASSWORD로 설정 (passlib pbkdf2_sha512)
  if [ -n "$ODOO_ADMIN_PASSWORD" ]; then
    echo "[PolyON] admin 비밀번호 설정..."
    python3 -c "
import passlib.context, os, subprocess
ctx = passlib.context.CryptContext(schemes=['pbkdf2_sha512'], deprecated='auto')
h = ctx.hash(os.getenv('ODOO_ADMIN_PASSWORD', 'admin'))
result = subprocess.run(
  ['psql', '-h', os.getenv('DB_HOST',''), '-U', os.getenv('DB_USER',''),
   '-d', os.getenv('DB_NAME',''),
   '-c', f\"UPDATE res_users SET password='{h}' WHERE login='admin';\"],
  env={**os.environ, 'PGPASSWORD': os.getenv('DB_PASSWORD','')},
  capture_output=True, text=True
)
if result.returncode == 0:
    print('[PolyON] admin 비밀번호 설정 완료')
else:
    print('[PolyON] admin 비밀번호 설정 실패:', result.stderr, flush=True)
" 2>/dev/null || echo "[PolyON] admin 비밀번호 설정 실패 (비치명적)"
  fi

  # LDAP 설정 자동 주입 (res_company_ldap)
  # Odoo가 --stop-after-init으로 종료된 후 직접 psql로 삽입
  if [ -n "$LDAP_HOST" ] && [ -n "$LDAP_BASE_DN" ]; then
    echo "[PolyON] LDAP 설정 주입..."
    python3 -c "
import os, subprocess

ldap_host     = os.getenv('LDAP_HOST', 'polyon-dc')
base_dn       = os.getenv('LDAP_BASE_DN', 'DC=cmars,DC=com')
bind_password = os.getenv('LDAP_BIND_PASSWORD', '')

sql = '''
INSERT INTO res_company_ldap (
  company, sequence,
  ldap_server, ldap_server_port, ldap_tls,
  ldap_binddn, ldap_password,
  ldap_base, ldap_filter,
  create_user,
  users_dn, auth_search_filter, user_search_filter,
  ldap_attr_login, ldap_attr_email,
  ldap_attr_firstname, ldap_attr_lastname, ldap_attr_fullname,
  ldap_attr_jobtitle, ldap_attr_photo,
  groups_dn, group_filter, group_attribute,
  sync_groups, create_role_per_group
)
SELECT
  1, 10,
  '{ldap_host}', 389, false,
  'CN=Administrator,CN=Users,{base_dn}', '{bind_password}',
  '{base_dn}',
  '(&(objectClass=user)(!(objectClass=computer))(!(userAccountControl:1.2.840.113556.1.4.803:=2)))',
  true,
  'CN=Users,{base_dn}',
  '(&(objectClass=person)(userPrincipalName=%(user)s))',
  '(&(objectClass=person)(!(isCriticalSystemObject=TRUE))(!(userAccountControl:1.2.840.113556.1.4.803:=2)))',
  'sAMAccountName', 'userPrincipalName',
  'givenName', 'sn', 'displayName',
  'title', 'thumbnailPhoto',
  'CN=Users,{base_dn}',
  '(&(objectClass=group)(!(isCriticalSystemObject=TRUE))(!(CN=Dns*)))',
  'memberOf',
  true, true
WHERE NOT EXISTS (SELECT 1 FROM res_company_ldap WHERE ldap_server = '{ldap_host}');
'''.format(
  ldap_host=ldap_host,
  base_dn=base_dn,
  bind_password=bind_password,
)

result = subprocess.run(
  ['psql', '-h', os.getenv('DB_HOST',''), '-U', os.getenv('DB_USER',''),
   '-d', os.getenv('DB_NAME',''), '-c', sql],
  env={**os.environ, 'PGPASSWORD': os.getenv('DB_PASSWORD','')},
  capture_output=True, text=True
)
if result.returncode == 0:
    print('[PolyON] LDAP 설정 주입 완료')
else:
    print('[PolyON] LDAP 설정 주입 실패:', result.stderr, flush=True)
" 2>/dev/null || echo "[PolyON] LDAP 설정 주입 실패 (비치명적)"
  fi
fi

# 7. Odoo 기동
echo "[PolyON] Odoo 기동..."
exec python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" -d "${DB_NAME:-polyon_odoo}"
