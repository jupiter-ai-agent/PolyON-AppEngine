# REQUIREMENTS.md — PP Odoo 요구사항 정의서 v2

> 작성: Jupiter (AI 팀장) | 2026-03-09  
> 대상: Cursor (구현 담당)  
> **v2: PP 제1원칙(Keycloak SSO) 적용 — LDAP 직접 인증/Redis 세션 삭제**

---

## 1. 목적

Odoo 19 Community Edition을 **PolyON Platform(PP) 모듈**로 패키징하여,  
Console에서 "설치" 버튼 한 번으로 **PRC가 모든 인프라 자원을 자동 프로비저닝**하고  
Odoo가 **Keycloak SSO로 인증**되어 완전히 기동되는 것을 검증한다.

---

## 2. 필수 참조

구현 전 반드시 아래 문서를 읽을 것:

1. **[PRC Provider Reference](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/prc-provider-reference.md)** — 9개 Provider 명세 (**auth provider 신규 추가**)
2. **[Module Spec](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-spec.md)** — module.yaml 작성 규격
3. **[Module Lifecycle](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-lifecycle-spec.md)** — 설치/삭제 라이프사이클
4. **[PP Drive (참고 구현)](https://github.com/jupiter-ai-agent/PolyON-Drive)** — PRC 검증 완료된 샘플

---

## 3. PP 핵심 원칙 (반드시 준수)

### ⛔ 제1원칙: 모든 서비스는 Keycloak SSO

- **Odoo가 직접 LDAP 인증하는 것은 PP 원칙 위반**
- 사원은 Portal에서 Keycloak으로 한 번 로그인 → iframe Odoo에서 별도 로그인 없음
- Odoo 자체 로그인 화면을 사용자에게 보여주면 안 됨

### ⛔ 소스 빌드 원칙

- `FROM odoo:19` 래퍼 금지 → 소스 clone 후 커스텀 빌드
- OIDC, S3, iframe 등 소스 레벨 제어 필수

### ⛔ 환경변수 기반 설정

- 모든 설정은 PRC 환경변수에서 파생
- 이미지에 호스트명, 비밀번호 등 하드코딩 금지

---

## 4. PRC Claims (4개)

> **v1에서 5개 → v2에서 4개로 변경**  
> 삭제: `directory` (LDAP 직접 인증 = SSO 우회), `cache` (Redis 세션 = SSO와 무관)  
> 추가: `auth` (Keycloak OIDC 클라이언트 자동 등록)

### 4.1 database (PostgreSQL)

```yaml
- type: database
  config:
    name: odoo              # → polyon_odoo DB, mod_odoo 유저
```

| Credential Key | 환경변수 | 예시 |
|----------------|---------|------|
| `host` | `DB_HOST` | `polyon-db` |
| `port` | `DB_PORT` | `5432` |
| `database` | `DB_NAME` | `polyon_odoo` |
| `user` | `DB_USER` | `mod_odoo` |
| `password` | `DB_PASSWORD` | (자동 생성) |

### 4.2 objectStorage (RustFS/S3)

```yaml
- type: objectStorage
  config:
    bucket: odoo            # → odoo S3 버킷
```

| Credential Key | 환경변수 | 예시 |
|----------------|---------|------|
| `endpoint` | `AWS_HOST` | `http://polyon-rustfs:9000` |
| `bucket` | `AWS_BUCKET_NAME` | `odoo` |
| `accessKey` | `AWS_ACCESS_KEY_ID` | (자동 생성) |
| `secretKey` | `AWS_SECRET_ACCESS_KEY` | (자동 생성) |

### 4.3 smtp (Stalwart Mail)

```yaml
- type: smtp
  config:
    domain: odoo            # → SMTP 발송 계정
```

| Credential Key | 환경변수 | 예시 |
|----------------|---------|------|
| `host` | `SMTP_HOST` | `polyon-mail` |
| `port` | `SMTP_PORT` | `587` |
| `user` | `SMTP_USER` | `odoo@cmars.com` |
| `password` | `SMTP_PASSWORD` | (자동 생성) |

### 4.4 auth (Keycloak OIDC) — 신규

```yaml
- type: auth
  config:
    clientId: odoo
    accessType: public       # PKCE SPA
    redirectUris:
      - "https://odoo.{{ baseDomain }}/*"
      - "https://console.{{ baseDomain }}/modules/odoo/*"
      - "https://portal.{{ baseDomain }}/modules/odoo/*"
```

| Credential Key | 환경변수 | 예시 |
|----------------|---------|------|
| `issuer` | `OIDC_ISSUER` | `https://auth.cmars.com/realms/polyon` |
| `clientId` | `OIDC_CLIENT_ID` | `odoo` |
| `authEndpoint` | `OIDC_AUTH_ENDPOINT` | `.../protocol/openid-connect/auth` |
| `tokenEndpoint` | `OIDC_TOKEN_ENDPOINT` | `.../protocol/openid-connect/token` |
| `jwksUri` | `OIDC_JWKS_URI` | `.../protocol/openid-connect/certs` |

---

## 5. module.yaml 전문

```yaml
apiVersion: polyon.io/v1
kind: Module

metadata:
  id: odoo
  name: PP Odoo
  version: "0.2.0"
  category: engine
  description: "ERP/HR/비즈니스 관리 플랫폼"
  icon: Enterprise
  vendor: "Triangle.s"
  license: LGPL-3.0

spec:
  engine: odoo

  requires:
    - id: postgresql
    - id: rustfs

  resources:
    image: jupitertriangles/polyon-odoo:v0.2.0
    replicas: 1
    ports:
      - name: http
        containerPort: 8069
    health:
      path: /web/health
      port: 8069
      initialDelay: 60
      period: 15
    resources:
      requests: { cpu: 200m, memory: 512Mi }
      limits:   { cpu: "2", memory: 2Gi }

  claims:
    - type: database
      config:
        name: odoo
    - type: objectStorage
      config:
        bucket: odoo
    - type: smtp
      config:
        domain: odoo
    - type: auth
      config:
        clientId: odoo
        accessType: public
        redirectUris:
          - "https://odoo.{{ baseDomain }}/*"
          - "https://console.{{ baseDomain }}/modules/odoo/*"
          - "https://portal.{{ baseDomain }}/modules/odoo/*"

  env:
    # Database
    DB_HOST: "{{ claims.database.host }}"
    DB_PORT: "{{ claims.database.port }}"
    DB_NAME: "{{ claims.database.database }}"
    DB_USER: "{{ claims.database.user }}"
    DB_PASSWORD: "{{ claims.database.password }}"
    # S3 Attachment
    AWS_HOST: "{{ claims.objectStorage.endpoint }}"
    AWS_BUCKET_NAME: "{{ claims.objectStorage.bucket }}"
    AWS_ACCESS_KEY_ID: "{{ claims.objectStorage.accessKey }}"
    AWS_SECRET_ACCESS_KEY: "{{ claims.objectStorage.secretKey }}"
    # SMTP
    SMTP_HOST: "{{ claims.smtp.host }}"
    SMTP_PORT: "{{ claims.smtp.port }}"
    SMTP_USER: "{{ claims.smtp.user }}"
    SMTP_PASSWORD: "{{ claims.smtp.password }}"
    # Keycloak OIDC SSO (PP 제1원칙)
    OIDC_ISSUER: "{{ claims.auth.issuer }}"
    OIDC_CLIENT_ID: "{{ claims.auth.clientId }}"
    OIDC_AUTH_ENDPOINT: "{{ claims.auth.authEndpoint }}"
    OIDC_TOKEN_ENDPOINT: "{{ claims.auth.tokenEndpoint }}"
    OIDC_JWKS_URI: "{{ claims.auth.jwksUri }}"
    # Odoo 정적 설정
    ODOO_ADMIN_PASSWORD: "admin"
    ODOO_DB_FILTER: "^polyon_odoo$"
    ODOO_LIST_DB: "false"
    ODOO_PROXY_MODE: "true"
    ODOO_WORKERS: "2"

  ingress:
    subdomain: odoo
    port: 8069

  console:
    menuGroup: services
    adminPath: /web
    pages:
      - id: backend
        title: "Odoo 관리"
        icon: Enterprise
        path: ""
        default: true

  portal:
    menuGroup: apps
    userPath: /web
    pages:
      - id: main
        title: "비즈니스"
        icon: Enterprise
        path: ""
        default: true
```

---

## 6. 프로젝트 구조

```
PolyON-Odoo/
├── polyon-module/
│   └── module.yaml              # PP 모듈 매니페스트 (위 §5)
├── addons/
│   ├── polyon_s3_attachment/     # ir.attachment → RustFS S3 저장
│   │   ├── __init__.py
│   │   ├── __manifest__.py
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── ir_attachment.py       # S3 저장/읽기/삭제 override
│   │       └── ir_config_parameter.py # PRC env → ir.config_parameter
│   ├── polyon_oidc/             # ★ Keycloak OIDC SSO (PP 제1원칙)
│   │   ├── __init__.py
│   │   ├── __manifest__.py
│   │   ├── controllers/
│   │   │   ├── __init__.py
│   │   │   └── oidc.py              # OIDC 인증 엔드포인트
│   │   └── models/
│   │       ├── __init__.py
│   │       └── res_users.py          # JWT → Odoo 사용자 매칭/자동생성
│   └── polyon_iframe/           # X-Frame-Options 제거, SameSite 쿠키
│       ├── __init__.py
│       ├── __manifest__.py
│       └── monkeypatch.py
├── config/
│   └── odoo.conf.template       # 환경변수 치환용 템플릿
├── scripts/
│   └── healthcheck.sh
├── entrypoint.sh                # PRC env → odoo.conf + addon 자동 설치
├── Dockerfile                   # Ubuntu Noble + Odoo 19.0 소스 빌드
├── .dockerignore
├── REVIEW.md
└── README.md
```

---

## 7. Dockerfile 요구사항

### 7.1 빌드 규칙

| 항목 | 값 |
|------|---|
| 베이스 이미지 | `ubuntu:noble` (python:3.12-slim은 wkhtmltopdf 비호환) |
| Odoo 소스 | `git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git` |
| 추가 pip | `boto3`, `PyJWT`, `cryptography` (S3 + JWT 검증) |
| 실행 파일 | `python3 /opt/odoo/odoo-bin` (⚠️ `odoo` 명령어 없음!) |
| entrypoint | `COPY --chmod=755 entrypoint.sh /entrypoint.sh` (권한 필수) |
| PP 매니페스트 | `COPY polyon-module/ /polyon-module/` |
| Addons | `COPY addons/ /opt/odoo/addons-custom/` |
| 유저 | `odoo` (uid 101) |

### 7.2 Dockerfile 참고

```dockerfile
FROM ubuntu:noble
ENV ODOO_HOME=/opt/odoo DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-xo", "pipefail", "-c"]

# 시스템 의존성 + wkhtmltopdf
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential python3 python3-pip python3-dev \
    postgresql-client libpq-dev libxml2-dev libxslt1-dev \
    libldap2-dev libsasl2-dev libssl-dev libffi-dev libjpeg-dev zlib1g-dev \
    fonts-noto-cjk node-less npm gettext-base ca-certificates curl \
    xfonts-75dpi xfonts-base && rm -rf /var/lib/apt/lists/*

ARG TARGETARCH
RUN curl -o /tmp/wk.deb -sSL \
    https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.jammy_${TARGETARCH:-amd64}.deb \
    && apt-get update && apt-get install -y --no-install-recommends /tmp/wk.deb \
    && rm /tmp/wk.deb && rm -rf /var/lib/apt/lists/*

RUN npm install -g rtlcss

# Odoo 19.0 소스
RUN git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git ${ODOO_HOME}
WORKDIR ${ODOO_HOME}
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && pip3 install --no-cache-dir --break-system-packages boto3 PyJWT cryptography

# Addons + Config + Manifest
COPY addons/ ${ODOO_HOME}/addons-custom/
COPY config/ /etc/odoo/
COPY polyon-module/ /polyon-module/
COPY --chmod=755 entrypoint.sh /entrypoint.sh

RUN mkdir -p /var/lib/odoo /etc/odoo \
    && useradd -u 101 -d /var/lib/odoo -M -r -s /usr/sbin/nologin odoo \
    && chown -R odoo:odoo ${ODOO_HOME} /var/lib/odoo /etc/odoo

USER odoo
EXPOSE 8069 8072
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python3", "/opt/odoo/odoo-bin", "--config=/etc/odoo/odoo.conf"]
```

---

## 8. entrypoint.sh 요구사항

```bash
#!/bin/bash
set -e

ODOO_CONF_PATH="/etc/odoo/odoo.conf"
ODOO_CONF_TEMPLATE_PATH="/etc/odoo/odoo.conf.template"

# 1. PRC 환경변수 → odoo.conf 생성
envsubst < "$ODOO_CONF_TEMPLATE_PATH" > "$ODOO_CONF_PATH"

# 2. Graceful Skip — 빈 값 서비스 라인 제거
if [ -z "$SMTP_HOST" ]; then
  sed -i '/^smtp_/d' "$ODOO_CONF_PATH"
fi
sed -i '/= $/d' "$ODOO_CONF_PATH"   # 빈 값 라인 전체 정리

# 3. 비밀번호 마스킹 로그
echo "Generated odoo.conf:"
sed -e 's/password = .*/password = ****/g' \
    -e 's/aws_secret_access_key = .*/aws_secret_access_key = ****/g' \
    "$ODOO_CONF_PATH" || true

# 4. DB 준비 대기
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
  echo "Waiting for PostgreSQL: ${DB_HOST}:${DB_PORT}"
  for i in $(seq 1 30); do
    pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "${DB_USER:-postgres}" >/dev/null 2>&1 && break
    echo "  waiting... ($i/30)"
    sleep 2
  done
fi

# 5. Odoo 초기화 (첫 기동 시 addon 설치)
ODOO_BIN="/opt/odoo/odoo-bin"
INIT_MODULES="base,polyon_s3_attachment,polyon_oidc,polyon_iframe"

python3 "$ODOO_BIN" --config="$ODOO_CONF_PATH" -i "$INIT_MODULES" --stop-after-init || true

# 6. Odoo 기동
echo "Starting Odoo..."
exec "$@"
```

**핵심:** `auth_ldap` 제거, `polyon_redis_session` 제거. INIT_MODULES에 `polyon_oidc` 추가.

---

## 9. odoo.conf.template

```ini
[options]
; Database
db_host = ${DB_HOST}
db_port = ${DB_PORT}
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
db_name = ${DB_NAME}
dbfilter = ${ODOO_DB_FILTER}
list_db = ${ODOO_LIST_DB}

; Security
admin_passwd = ${ODOO_ADMIN_PASSWORD}
proxy_mode = ${ODOO_PROXY_MODE}

; Workers
workers = ${ODOO_WORKERS}

; SMTP (빈 값이면 entrypoint가 제거)
smtp_server = ${SMTP_HOST}
smtp_port = ${SMTP_PORT}
smtp_user = ${SMTP_USER}
smtp_password = ${SMTP_PASSWORD}
smtp_ssl = True

; Addons
addons_path = /opt/odoo/addons,/opt/odoo/addons-custom

; HTTP
http_interface = 0.0.0.0
```

> ⚠️ `session_redis_*` 라인 없음 — Redis 세션 삭제됨

---

## 10. 커스텀 Addon 상세

### 10.1 `polyon_oidc` — Keycloak OIDC SSO ★핵심★

**이것이 PP 제1원칙을 구현하는 핵심 addon이다.**

#### 동작 흐름

```
Portal/Console (Keycloak JWT 보유)
  └→ iframe으로 Odoo 로드
    └→ URL에 JWT 전달: /modules/odoo/web?token={JWT}
      └→ polyon_oidc 컨트롤러가 JWT 검증
        └→ JWT의 preferred_username으로 Odoo 사용자 매칭
          └→ 사용자 없으면 자동 생성
            └→ Odoo 세션 생성 (로그인 화면 스킵)
              └→ /web으로 리다이렉트
```

#### 10.1.1 `__manifest__.py`

```python
{
    "name": "PolyON OIDC SSO",
    "version": "19.0.1.0.0",
    "category": "Authentication",
    "summary": "Keycloak OIDC SSO for PolyON Platform",
    "depends": ["base", "web"],
    "data": [],
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}
```

#### 10.1.2 `controllers/oidc.py` — JWT 인증 엔드포인트

```python
import json
import logging
import os

import jwt                    # PyJWT
import requests
from jwt.algorithms import RSAAlgorithm

from odoo import http
from odoo.http import request

logger = logging.getLogger(__name__)

# JWKS 캐시 (서버 수명 동안 유지)
_jwks_cache = {}


def _get_jwks(jwks_uri):
    """Keycloak JWKS 엔드포인트에서 공개키를 가져온다."""
    if jwks_uri in _jwks_cache:
        return _jwks_cache[jwks_uri]
    resp = requests.get(jwks_uri, timeout=10)
    resp.raise_for_status()
    keys = resp.json().get("keys", [])
    _jwks_cache[jwks_uri] = keys
    return keys


def _verify_jwt(token):
    """JWT를 Keycloak 공개키로 검증하고 payload를 반환한다."""
    issuer = os.getenv("OIDC_ISSUER", "")
    client_id = os.getenv("OIDC_CLIENT_ID", "")
    jwks_uri = os.getenv("OIDC_JWKS_URI", "")

    if not all([issuer, client_id, jwks_uri]):
        raise ValueError("OIDC 환경변수 미설정")

    # JWT 헤더에서 kid 추출
    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")

    # JWKS에서 매칭되는 키 찾기
    keys = _get_jwks(jwks_uri)
    key_data = next((k for k in keys if k.get("kid") == kid), None)
    if not key_data:
        raise ValueError(f"JWKS에서 kid={kid} 키를 찾을 수 없음")

    public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))

    # JWT 검증 (서명 + 만료 + issuer + audience)
    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=issuer,
        audience=client_id,
    )
    return payload


class OIDCController(http.Controller):

    @http.route("/polyon/oidc/login", type="http", auth="none", csrf=False)
    def oidc_login(self, token=None, redirect="/web", **kwargs):
        """JWT 토큰을 검증하고 Odoo 세션을 생성한다.

        Portal/Console에서 iframe 로드 시 이 엔드포인트를 호출:
        /polyon/oidc/login?token={JWT}&redirect=/web
        """
        if not token:
            return request.redirect("/web/login")  # fallback

        try:
            payload = _verify_jwt(token)
        except Exception as e:
            logger.warning("OIDC JWT 검증 실패: %s", e)
            return request.redirect("/web/login")

        # JWT에서 사용자 정보 추출
        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            logger.warning("JWT에 preferred_username 없음")
            return request.redirect("/web/login")

        # Odoo 사용자 매칭 또는 자동 생성
        User = request.env["res.users"].sudo()
        user = User.search([("login", "=", username)], limit=1)

        if not user:
            # 자동 생성 — PP SSO 사용자
            user = User.create({
                "login": username,
                "name": name,
                "email": email,
                "groups_id": [(6, 0, [request.env.ref("base.group_user").id])],
                # password 없음 — SSO 전용 사용자
            })
            logger.info("OIDC 사용자 자동 생성: %s", username)

        # Odoo 세션 생성 (로그인 처리)
        request.session.authenticate(request.db, username, {"type": "token"})

        return request.redirect(redirect)
```

#### 10.1.3 `models/res_users.py` — 토큰 인증 허용

```python
from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    @classmethod
    def _login(cls, db, login, password, user_agent_env=None):
        """토큰 기반 인증을 허용한다."""
        if isinstance(password, dict) and password.get("type") == "token":
            # SSO 토큰 인증 — 비밀번호 검증 스킵
            user = cls.search([("login", "=", login)], limit=1)
            if user:
                return user.id
        return super()._login(db, login, password, user_agent_env=user_agent_env)
```

> ⚠️ 위 코드는 **구조 참고용**이다. Odoo 19의 정확한 인증 API(`_login`, `authenticate` 등)는
> 실제 소스를 확인하여 맞춰야 한다. 핵심은 **JWT 검증 → 사용자 매칭 → 세션 생성** 흐름이다.

### 10.2 `polyon_s3_attachment` — S3 파일 저장

**이미 구현 완료 (commit `a2d6910`).** 변경 없음.

- `ir.attachment._file_write/read/delete` override
- S3 미설정 시 기본 filestore fallback
- `ir.config_parameter`에 PRC env 자동 저장

### 10.3 `polyon_iframe` — iframe 임베딩

**이미 구현 완료 (commits `d4cf25a`, `bc4c8ea`).** 변경 없음.

- `X-Frame-Options` 헤더 제거
- `session_id` 쿠키에 `SameSite=None; Secure` 추가

---

## 11. 삭제 대상 (v1 → v2)

| 파일/모듈 | 이유 |
|----------|------|
| `addons/polyon_ldap_auto/` | LDAP 직접 인증 = Keycloak 우회 (PP 제1원칙 위반) |
| `addons/polyon_redis_session/` | SSO 기반이므로 Odoo 자체 세션 관리 불필요 |
| entrypoint의 `auth_ldap` 설치 | LDAP 인증 모듈 불필요 |
| `odoo.conf.template`의 `session_redis_*` | Redis 세션 불필요 |
| module.yaml의 `directory` claim | LDAP claim 삭제 |
| module.yaml의 `cache` claim | Redis claim 삭제 |
| module.yaml의 `LDAP_*` env | LDAP 환경변수 삭제 |
| module.yaml의 `REDIS_URL` env | Redis 환경변수 삭제 |

---

## 12. Console/Portal iframe 통합

### 12.1 iframe 로딩 흐름

```
Console/Portal (Keycloak JWT 보유)
  └→ ModuleSector 컴포넌트
    └→ iframe src="/modules/odoo/polyon/oidc/login?token={JWT}&redirect=/web"
      └→ polyon_oidc가 JWT 검증 + Odoo 세션 생성
        └→ /web 리다이렉트 → Odoo UI 표시
```

### 12.2 Console nginx 프록시 (이미 구현 완료)

```nginx
location /modules/odoo/ {
    set $upstream_odoo http://polyon-odoo.polyon.svc.cluster.local:8069;
    rewrite ^/modules/odoo/(.*)$ /$1 break;
    proxy_pass $upstream_odoo;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_http_version 1.1;
}
```

### 12.3 ModuleSector에서 JWT 전달

Console/Portal의 `ModuleSector` 컴포넌트가 iframe src를 구성할 때,  
Keycloak JWT를 query parameter로 전달:

```typescript
// Console/Portal 측 (참고 — 이 코드는 Jupiter가 구현)
const iframeSrc = `/modules/odoo/polyon/oidc/login?token=${keycloakToken}&redirect=/web`;
```

---

## 13. Graceful Skip 규칙

Phase 1에서는 DB만으로 Odoo가 정상 기동되어야 한다.

| 서비스 | env 비어있을 때 | 처리 |
|--------|----------------|------|
| **SMTP** | `SMTP_HOST` 빈 값 | `odoo.conf`에서 `smtp_*` 라인 제거 |
| **S3** | `AWS_HOST` 빈 값 | 기본 filestore fallback |
| **OIDC** | `OIDC_ISSUER` 빈 값 | Odoo 기본 로그인 fallback |

---

## 14. 검증 기준 (Definition of Done)

### Phase 1: PRC 자동 설치 + 기동 (필수) ✅ 완료

- [x] Docker 이미지 빌드 성공
- [x] `/polyon-module/module.yaml` 이미지 내 존재
- [x] PRC install → DB/S3/SMTP 자동 프로비저닝
- [x] Odoo Pod 정상 기동 (`/web/health` 200 OK)

### Phase 2: SSO + 서비스 연동 (현재 목표)

- [ ] **`polyon_oidc` addon 구현** — JWT 검증 + 사용자 자동생성 + 세션 생성
- [ ] **`polyon_ldap_auto` 삭제**, **`polyon_redis_session` 삭제**
- [ ] OIDC env 빈 값 시 graceful fallback
- [ ] S3 Attachment 검증: 파일 업로드 → RustFS 저장
- [ ] Console/Portal iframe에서 Odoo 자동 로그인

### Phase 3: 완성도 (선택)

- [ ] PP 테마 커스텀 (로고, 색상)
- [ ] ERP/HR/재고 서브메뉴 분리

---

## 15. 절대 하지 말 것

1. **LDAP 직접 인증 금지** — PP 제1원칙 위반. Keycloak SSO만 사용
2. **Odoo 자체 로그인 화면 노출 금지** — 사용자는 Portal SSO로만 접근
3. **환경변수 하드코딩 금지** — 모든 설정은 PRC env에서 파생
4. **PRC 환경변수명 임의 변경 금지** — Provider Reference 키 그대로
5. **`/polyon-module/module.yaml` 누락 금지** — PRC 인식의 핵심
6. **호스트 포트 직접 노출 금지** — Ingress/nginx 경유만
7. **DB 직접 생성 금지** — PRC가 자동 생성
8. **Redis 세션 코드 재도입 금지** — SSO가 세션 관리

---

## 부록 A: v1 → v2 변경 이력

| 항목 | v1 | v2 |
|------|----|----|
| PRC claims | 5개 (DB, S3, LDAP, SMTP, Redis) | **4개** (DB, S3, SMTP, **Auth**) |
| 인증 | `auth_ldap` (LDAP 직접) | **Keycloak OIDC SSO** |
| 세션 | Redis (`polyon_redis_session`) | **Keycloak SSO 세션** |
| Addons | 4개 | **3개** (s3, oidc, iframe) |
| module.yaml version | 0.1.0 | **0.2.0** |

## 부록 B: PP Drive 참고 포인트

[PolyON-Drive](https://github.com/jupiter-ai-agent/PolyON-Drive)에서 참고할 파일:

| 파일 | 참고 내용 |
|------|----------|
| `polyon-module/module.yaml` | PRC claims + env 템플릿 작성법 |
| `src/config.rs` | PRC 환경변수 읽기 패턴 |
| `Dockerfile` | `/polyon-module` COPY 패턴 |
