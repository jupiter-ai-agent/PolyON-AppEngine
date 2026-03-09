# REQUIREMENTS.md — PP Odoo 요구사항 정의서

> 작성: Jupiter (AI 팀장) | 2026-03-09  
> 대상: Cursor (구현 담당)

---

## 1. 목적

Odoo 19 Community Edition을 **PolyON Platform(PP) 모듈**로 패키징하여,  
Console에서 "설치" 버튼 한 번으로 **PRC가 모든 인프라 자원을 자동 프로비저닝**하고  
Odoo가 완전히 기동되는 것을 검증한다.

---

## 2. 필수 참조

구현 전 반드시 아래 문서를 읽을 것:

1. **[PRC Provider Reference](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/prc-provider-reference.md)** — 8개 Provider의 Config/Credential 명세
2. **[Module Spec](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-spec.md)** — module.yaml 작성 규격
3. **[Module Lifecycle](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-lifecycle-spec.md)** — 설치/삭제 라이프사이클
4. **[PP Drive (참고 구현)](https://github.com/jupiter-ai-agent/PolyON-Drive)** — PRC 검증 완료된 샘플

특히 **PP Drive의 `polyon-module/module.yaml`**을 참고하면 claims + env 템플릿 작성법을 바로 파악할 수 있다.

---

## 3. PRC Claims (5개)

Odoo는 5개의 Foundation 자원을 사용한다.  
`module.yaml`의 `spec.claims`에 아래와 같이 선언하면 PRC가 자동 프로비저닝한다.

### 3.1 database (PostgreSQL)

| 항목 | 값 |
|------|---|
| config.name | `odoo` |
| 결과 DB | `polyon_odoo` |
| 결과 유저 | `mod_odoo` |
| 환경변수 | `DATABASE_URL`, 또는 개별 host/port/database/user/password |

**Odoo는 개별 파라미터 방식이 필요하다:**
```yaml
env:
  DB_HOST: "{{ claims.database.host }}"
  DB_PORT: "{{ claims.database.port }}"
  DB_NAME: "{{ claims.database.database }}"
  DB_USER: "{{ claims.database.user }}"
  DB_PASSWORD: "{{ claims.database.password }}"
```

### 3.2 objectStorage (RustFS/S3)

| 항목 | 값 |
|------|---|
| config.bucket | `odoo` |
| 용도 | ir.attachment S3 스토리지 |

```yaml
env:
  AWS_HOST: "{{ claims.objectStorage.endpoint }}"
  AWS_BUCKET_NAME: "{{ claims.objectStorage.bucket }}"
  AWS_ACCESS_KEY_ID: "{{ claims.objectStorage.accessKey }}"
  AWS_SECRET_ACCESS_KEY: "{{ claims.objectStorage.secretKey }}"
```

### 3.3 ~~directory (Samba AD DC / LDAP)~~ → **삭제**

> ⛔ **PP 제1원칙: 모든 서비스는 Keycloak SSO를 통해 인증한다.**  
> Odoo가 직접 LDAP 인증하면 Keycloak을 우회하게 된다.  
> 사원 인증은 **Keycloak OIDC**를 통해 처리한다.  
> directory claim은 삭제.

### 3.4 smtp (Stalwart Mail)

| 항목 | 값 |
|------|---|
| config.domain | `odoo` |
| 용도 | Odoo 이메일 발송 (견적서, 알림 등) |

```yaml
env:
  SMTP_HOST: "{{ claims.smtp.host }}"
  SMTP_PORT: "{{ claims.smtp.port }}"
  SMTP_USER: "{{ claims.smtp.user }}"
  SMTP_PASSWORD: "{{ claims.smtp.password }}"
```

### 3.5 ~~cache (Redis)~~ → **삭제**

> ⛔ **PP에서 세션 관리는 Keycloak SSO가 담당한다.**  
> Odoo 자체 세션을 Redis로 관리할 필요 없다.  
> SSO 토큰 기반 인증이므로 Odoo 세션 쿠키 의존도 최소화.  
> cache claim은 삭제.

---

## 4. module.yaml 요구사항

`/polyon-module/module.yaml`로 이미지 내에 포함.

### 필수 필드

```yaml
apiVersion: polyon.io/v1
kind: Module

metadata:
  id: odoo                    # 모듈 ID (Core 등록용)
  name: PP Odoo               # 표시 이름
  version: "0.1.0"            # 시맨틱 버전
  category: engine            # engine (비즈니스 엔진)
  description: "ERP/HR/비즈니스 관리 플랫폼"
  icon: Enterprise            # @carbon/icons-react 아이콘 이름
  vendor: "Triangle.s"

spec:
  engine: odoo

  requires:                   # Foundation 의존성
    - id: postgresql
    - id: rustfs

  resources:
    image: jupitertriangles/polyon-odoo:v0.1.0
    replicas: 1
    ports:
      - name: http
        containerPort: 8069
    health:
      path: /web/health       # Odoo 19 health endpoint
      port: 8069
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
    # ⛔ directory, cache 삭제 — PP 제1원칙: 인증은 Keycloak SSO

  env:
    # Database (PRC 자동 주입)
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
    # Keycloak SSO (PP 제1원칙)
    OIDC_ISSUER: "https://auth.{{ baseDomain }}/realms/polyon"
    OIDC_CLIENT_ID: "odoo"
    # Odoo 설정 (정적)
    ODOO_ADMIN_PASSWORD: "admin"   # 마스터 비밀번호 (DB 관리용)
    ODOO_DB_FILTER: "^polyon_odoo$"
    ODOO_LIST_DB: "false"
    ODOO_PROXY_MODE: "true"
    ODOO_WORKERS: "2"

  ingress:
    subdomain: odoo           # https://odoo.cmars.com
    port: 8069
```

---

## 5. Dockerfile 요구사항

### 5.1 빌드 규칙

| 항목 | 요구사항 |
|------|---------|
| **소스** | `https://github.com/odoo/odoo.git` (19.0 브랜치) — 소스 clone 후 커스텀 빌드 |
| 플랫폼 | `linux/amd64` + `linux/arm64` |
| 매니페스트 | `/polyon-module/module.yaml` COPY 필수 |
| 이미지 태그 | `jupitertriangles/polyon-odoo:v{semver}` |

> **⛔ 공식 이미지 pull 금지** — PP 원칙: 커스터마이징 필요한 엔진은 소스 빌드 원칙.  
> Odoo는 S3 attachment, LDAP 자동설정, Redis 세션, iframe 허용 등  
> 소스 레벨 제어가 필수이므로 반드시 소스에서 빌드한다.

### 5.1.1 소스 빌드가 필요한 이유

| 커스텀 항목 | 이유 |
|------------|------|
| S3 Attachment | `ir.attachment` 저장 로직을 RustFS(S3)로 변경 — 커스텀 addon |
| Keycloak OIDC SSO | PP 제1원칙: 자체 로그인 화면 제거, JWT 기반 자동 인증 — 커스텀 addon |
| X-Frame-Options 제거 | Console/Portal iframe 임베딩 — 커스텀 addon |
| X-Frame-Options | iframe 임베딩을 위해 보안 헤더 제거/조정 — 소스 패치 |
| PRC 환경변수 자동 적용 | 기동 시 환경변수 → DB 설정 자동 주입 — 커스텀 addon |

### 5.1.2 프로젝트 구조

```
PolyON-Odoo/
├── polyon-module/
│   └── module.yaml              # PP 모듈 매니페스트
├── addons/
│   ├── polyon_s3_attachment/     # ir.attachment → RustFS S3 저장
│   ├── polyon_oidc/             # Keycloak OIDC SSO 인증 (PP 제1원칙)
│   └── polyon_iframe/           # X-Frame-Options 제거, SameSite 쿠키
├── config/
│   └── odoo.conf.template       # 환경변수 치환용 템플릿
├── entrypoint.sh                # PRC env → odoo.conf + 커스텀 addon 자동 설치
├── Dockerfile                   # Odoo 19.0 소스 빌드
├── .dockerignore
└── README.md
```

### 5.1.3 Dockerfile 구조 (소스 빌드)

```dockerfile
# Stage 1: Odoo 소스
FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    git postgresql-client libpq-dev libxml2-dev libxslt1-dev \
    libldap2-dev libsasl2-dev node-less npm wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/*

# Odoo 19.0 소스 clone
RUN git clone --depth 1 --branch 19.0 https://github.com/odoo/odoo.git /opt/odoo

# Python 의존성
RUN pip install --no-cache-dir -r /opt/odoo/requirements.txt \
    && pip install --no-cache-dir boto3 redis

# 커스텀 addons 복사
COPY addons/ /opt/odoo/addons-custom/

# PP 모듈 매니페스트
COPY polyon-module/ /polyon-module/

# entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8069 8072
ENTRYPOINT ["/entrypoint.sh"]
CMD ["odoo"]
```

### 5.2 entrypoint.sh 핵심 로직

PRC가 주입하는 환경변수를 Odoo가 인식하는 형태로 변환해야 한다.

```bash
#!/bin/bash
set -e

# PRC 환경변수 → odoo.conf 생성
cat > /etc/odoo/odoo.conf << EOF
[options]
; Database
db_host = ${DB_HOST}
db_port = ${DB_PORT}
db_user = ${DB_USER}
db_password = ${DB_PASSWORD}
db_name = ${DB_NAME}
dbfilter = ${ODOO_DB_FILTER:-^%d$}
list_db = ${ODOO_LIST_DB:-False}

; Security
admin_passwd = ${ODOO_ADMIN_PASSWORD:-admin}
proxy_mode = ${ODOO_PROXY_MODE:-True}

; Workers
workers = ${ODOO_WORKERS:-2}

; S3 Attachment (ir_attachment_s3 모듈 사용 시)
; aws_host = ${AWS_HOST}
; aws_bucket_name = ${AWS_BUCKET_NAME}
; aws_access_key_id = ${AWS_ACCESS_KEY_ID}
; aws_secret_access_key = ${AWS_SECRET_ACCESS_KEY}

; SMTP
smtp_server = ${SMTP_HOST:-localhost}
smtp_port = ${SMTP_PORT:-587}
smtp_user = ${SMTP_USER:-}
smtp_password = ${SMTP_PASSWORD:-}
smtp_ssl = True

; Addons
addons_path = /mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons
EOF

# DB 대기 (PRC가 DB를 생성했으므로 연결 가능할 때까지 대기)
python3 /usr/local/bin/wait-for-psql.py \
  --db_host "$DB_HOST" --db_port "$DB_PORT" \
  --db_user "$DB_USER" --db_password "$DB_PASSWORD" \
  --timeout 60

# Odoo 최초 기동 시 DB 초기화 (테이블 없으면 -i base)
# 이미 초기화된 DB면 정상 기동
exec odoo --config=/etc/odoo/odoo.conf "$@"
```

**핵심 포인트:**
- PRC 환경변수 → `odoo.conf` 동적 생성 (이미지에 하드코딩 금지)
- DB 연결 대기 후 기동
- 재설치 시에도 멱등하게 동작 (기존 DB면 초기화 스킵)

---

## 6. 인증: Keycloak OIDC SSO (PP 제1원칙)

> ⛔ **Odoo가 직접 LDAP 인증하는 것은 PP 원칙 위반이다.**  
> PP의 모든 서비스는 Keycloak을 통해 SSO로 인증한다.

### 6.1 PP 인증 아키텍처

```
사용자 → Portal (Keycloak OIDC 로그인, polyon realm)
  └→ Portal이 JWT 토큰 보유
    └→ iframe으로 Odoo 표시
      └→ Odoo는 Keycloak JWT를 검증하여 사용자 식별
```

**Odoo 자체 로그인 화면을 사용자에게 보여주면 안 된다.**  
Portal에서 이미 Keycloak으로 로그인한 상태에서 iframe에 Odoo가 표시된다.

### 6.2 구현 방식: `polyon_oidc` 커스텀 addon

`auth_ldap` 모듈 대신 **`polyon_oidc`** 커스텀 addon을 만든다.

**동작 흐름:**
1. Portal/Console이 iframe에 Odoo를 로드할 때, JWT 토큰을 전달 (postMessage 또는 query param 또는 header)
2. `polyon_oidc` addon이 JWT를 검증
3. JWT의 `preferred_username` (= AD sAMAccountName)으로 Odoo 사용자 매칭/자동 생성
4. Odoo 세션 생성 (로그인 화면 스킵)

**환경변수:**
```yaml
env:
  OIDC_ISSUER: "https://auth.cmars.com/realms/polyon"
  OIDC_CLIENT_ID: "odoo"    # Keycloak에 등록할 클라이언트
```

### 6.3 Keycloak 클라이언트 설정

Keycloak `polyon` realm에 `odoo` 클라이언트 등록 필요:

| 항목 | 값 |
|------|---|
| Client ID | `odoo` |
| Client Protocol | openid-connect |
| Access Type | public (PKCE) |
| Valid Redirect URIs | `https://odoo.cmars.com/*` |
| Web Origins | `https://console.cmars.com`, `https://portal.cmars.com` |

### 6.4 삭제할 것

- **`polyon_ldap_auto` addon** → 삭제 (LDAP 직접 인증 = Keycloak 우회)
- **`polyon_redis_session` addon** → 삭제 (SSO 기반이므로 Odoo 자체 세션 관리 불필요)
- **`auth_ldap` 모듈 의존성** → 제거 (entrypoint의 `-i auth_ldap` 제거)
- **directory claim** → module.yaml에서 삭제
- **cache claim** → module.yaml에서 삭제
- **LDAP_* 환경변수** → module.yaml env에서 삭제
- **REDIS_URL 환경변수** → module.yaml env에서 삭제

---

## 7. S3 Attachment 연동

Odoo의 기본 파일 저장은 로컬 `/var/lib/odoo/filestore`.  
PP 환경에서는 **RustFS(S3)에 저장**해야 한다.

### 방법 (택 1)

**A. ir_attachment_s3 모듈 (추천)**
- `odoo-s3` 또는 `base_attachment_object_storage` OCA 모듈 사용
- `addons/` 디렉토리에 포함
- odoo.conf에 S3 설정 추가

**B. 환경변수 기반 커스텀**
- entrypoint에서 `ir.config_parameter`에 S3 설정 주입
- XML 데이터 파일로 설정

### S3 환경변수 매핑

| 환경변수 | 용도 |
|----------|------|
| `AWS_HOST` | S3 엔드포인트 (예: `http://polyon-rustfs:9000`) |
| `AWS_BUCKET_NAME` | 버킷 이름 (`odoo`) |
| `AWS_ACCESS_KEY_ID` | 접근 키 |
| `AWS_SECRET_ACCESS_KEY` | 비밀 키 |

---

## 8. ~~Redis 세션 스토어~~ → 삭제

> ⛔ **PP에서 세션 관리는 Keycloak SSO가 담당한다.**  
> Odoo 자체 세션을 Redis로 관리하는 구조는 PP 아키텍처와 맞지 않는다.  
> 이 섹션은 삭제. `polyon_redis_session` addon도 삭제 대상.

---

## 9. Console/Portal UI 선언

### Console (관리자 페이지)

Odoo 자체 Admin UI 사용 — iframe으로 Console에 표시.

```yaml
console:
  menuGroup: services
  adminPath: /web              # Odoo 백엔드 UI
  pages:
    - id: backend
      title: "Odoo 관리"
      icon: Enterprise
      path: ""
      default: true
```

### Portal (사원 페이지)

Odoo의 사원용 UI — 필요 시 커스텀 가능.

```yaml
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

## 10. 검증 기준 (Definition of Done)

### Phase 1: PRC 자동 설치 + 기동 (필수)

- [ ] `module.yaml`이 PRC Provider Reference 규격에 맞게 작성됨
- [ ] Docker 이미지 빌드 성공
- [ ] `/polyon-module/module.yaml` 이미지 내 존재
- [ ] Console에서 "PP Odoo" 설치 버튼 → PRC 3개 claim 자동 프로비저닝
  - [ ] PostgreSQL: `polyon_odoo` DB + `mod_odoo` 유저 생성
  - [ ] RustFS: `odoo` 버킷 생성
  - [ ] Stalwart: SMTP 계정 생성
- [ ] Odoo Pod 정상 기동 (`/web/health` 200 OK)
- [ ] 삭제 → 재설치 시 동일하게 자동 동작 (멱등성)

### Phase 2: SSO + 서비스 연동 (필수)

- [ ] **Keycloak OIDC SSO**: Portal 로그인 → iframe Odoo 자동 인증 (로그인 화면 없음)
- [ ] S3 Attachment: 파일 업로드 시 RustFS 버킷에 저장
- [ ] SMTP: Odoo에서 이메일 발송 동작
- [ ] Console/Portal iframe 정상 표시

### Phase 3: 완성도 (선택)

- [ ] PP 테마 커스텀 (로고, 색상)
- [ ] ERP/HR/재고 등 서브메뉴 분리

---

## 11. 기술 제약사항

| 항목 | 제약 |
|------|------|
| Odoo 버전 | 19.0 Community Edition |
| Python | 3.12+ (Ubuntu Noble 기반) |
| DB | PostgreSQL 17 (PRC 프로비저닝) |
| 이미지 크기 | 1GB 이하 권장 (Odoo 특성상 50MB 불가) |
| 포트 | 8069 (HTTP), 8072 (Longpolling/WebSocket) |
| 유저 | `odoo` (uid 101) |
| 환경변수만 | 설정 파일 하드코딩 금지. 모든 설정은 PRC 환경변수에서 파생 |

---

## 12. Graceful Skip 규칙 (Phase 1 필수)

PRC는 5개 claim을 모두 프로비저닝하지만, **개별 서비스 연동은 env가 비어있으면 스킵**해야 한다.  
Phase 1에서는 DB만으로 Odoo가 정상 기동되어야 한다.

### 원칙
- **env가 비어있으면 해당 기능 비활성화** — 에러 발생 금지
- `odoo.conf`에 빈 값 라인이 남으면 Odoo가 빈 호스트로 연결 시도 → 에러

### 구체적 처리

| 서비스 | env 비어있을 때 | 처리 방법 |
|--------|----------------|----------|
| **SMTP** | `SMTP_HOST` 비어있음 | `odoo.conf`에서 `smtp_*` 라인 **제거** |
| **S3** | `AWS_HOST` 비어있음 | `ir.attachment` override에서 **기본 filestore fallback** |
| **OIDC** | `OIDC_ISSUER` 비어있음 | SSO 비활성화, Odoo 기본 로그인 fallback |

### entrypoint.sh에서 처리 예시

```bash
# envsubst로 conf 생성 후, 빈 값 서비스 라인 제거
envsubst < "$ODOO_CONF_TEMPLATE_PATH" > "$ODOO_CONF_PATH"

# SMTP 미설정 → conf에서 제거
if [ -z "$SMTP_HOST" ]; then
  sed -i '/smtp_/d' "$ODOO_CONF_PATH"
fi
```

### addon에서 처리 예시

```python
# S3 미설정 → filestore fallback
def _file_write(self, bin_value, checksum):
    client, bucket = self._get_s3_client()
    if client is None:
        return super()._file_write(bin_value, checksum)  # 기본 동작
    # S3 저장 로직...
```

---

## 13. PP 환경 통합 주의사항

### 13.1 Console/Portal iframe 프록시

PP에서 모듈 UI는 Console/Portal nginx를 경유하여 iframe으로 표시된다:

```
Console (https://console.cmars.com)
  └→ nginx: /modules/odoo/ → proxy_pass http://polyon-odoo:8069
    └→ <iframe src="/modules/odoo/web">
```

**현재 Console nginx에 Odoo 프록시가 없다** — 이건 PP Core/Console 측 작업이지만,  
Odoo 측에서 확인해야 할 것:

- Odoo가 `/web` 경로 앞에 prefix(`/modules/odoo/`)가 붙어도 정상 동작하는지
- 필요 시 `--proxy-mode=True` + `X-Forwarded-*` 헤더로 경로 인식
- Odoo 정적 파일(JS/CSS)의 경로가 prefix 환경에서 깨지지 않는지

### 13.2 iframe 세션 쿠키 (SameSite)

Console(`console.cmars.com`)에서 Odoo(`odoo.cmars.com`)를 iframe으로 표시할 때,  
**크로스 도메인 쿠키 문제**가 발생한다.

**필요한 처리:**
- Odoo 세션 쿠키에 `SameSite=None; Secure` 속성 추가
- `polyon_iframe` addon에서 response header 또는 Odoo의 `session_cookie` 설정 수정

```python
# polyon_iframe addon에 추가 필요
# Odoo의 session cookie SameSite 설정
from odoo.http import Response

# werkzeug의 session cookie 옵션 override
# session_cookie_samesite = 'None'
# session_cookie_secure = True
```

> ⚠️ 이것 없이는 iframe 내 Odoo 로그인이 동작하지 않는다.

### 13.3 Console/Portal 페이지 선언 전략

Odoo는 자체 메뉴 시스템이 있으므로, PP Console에서 세부 메뉴를 나눌 필요는 적다.  
현재 단일 페이지 선언(`Odoo 관리`, `비즈니스`)은 **Phase 1에서 적절하다.**

Phase 3에서 필요 시 ERP/HR/재고 등 주요 모듈별 진입점을 추가할 수 있다:

```yaml
# Phase 3 예시 (선택)
console:
  pages:
    - id: backend
      title: "Odoo 관리"
      icon: Enterprise
      default: true
    - id: hr
      title: "인사관리"
      icon: UserMultiple
      path: "odoo/hr"
    - id: inventory
      title: "재고"
      icon: Inventory
      path: "odoo/inventory"
```

---

## 14. 절대 하지 말 것

1. **환경변수 하드코딩 금지** — DB 호스트, 비밀번호 등을 이미지에 박지 말 것
2. **PRC 환경변수명 임의 변경 금지** — Provider Reference에 정의된 credential key 그대로 사용
3. **`/polyon-module/module.yaml` 누락 금지** — PRC 인식의 핵심
4. **호스트 포트 직접 노출 금지** — Ingress(Traefik) 경유만 허용
5. **DB 직접 생성 금지** — PRC가 자동 생성. entrypoint에서 `CREATE DATABASE` 시도 금지

---

## 부록 A: PP Drive 참고 포인트

[PolyON-Drive](https://github.com/jupiter-ai-agent/PolyON-Drive)에서 참고할 파일:

| 파일 | 참고 내용 |
|------|----------|
| `polyon-module/module.yaml` | PRC claims + env 템플릿 작성법 |
| `src/config.rs` | PRC 환경변수 읽기 패턴 (우선순위 fallback) |
| `Dockerfile` | `/polyon-module` COPY, 멀티스테이지 빌드 |
| `src/main.rs` | Health endpoint (`/health`) 구현 |

### PP Drive module.yaml의 PRC 부분 (발췌)

```yaml
spec:
  claims:
    - type: database
      config:
        name: drive           # → polyon_drive DB 자동 생성
    - type: objectStorage
      config:
        bucket: drive         # → drive 버킷 자동 생성
    - type: directory
      config:
        ou: drive             # → OU=drive 서비스 계정 자동 생성

  env:
    DATABASE_URL: "{{ claims.database.url }}"
    S3_ENDPOINT: "{{ claims.objectStorage.endpoint }}"
    S3_BUCKET: "{{ claims.objectStorage.bucket }}"
    S3_ACCESS_KEY: "{{ claims.objectStorage.accessKey }}"
    S3_SECRET_KEY: "{{ claims.objectStorage.secretKey }}"
    LDAP_URL: "{{ claims.directory.url }}"
    LDAP_BIND_DN: "{{ claims.directory.bindDN }}"
    LDAP_BIND_PASSWORD: "{{ claims.directory.bindPassword }}"
    LDAP_BASE_DN: "{{ claims.directory.baseDN }}"
```

Odoo도 동일한 패턴으로 5개 claim을 선언하면 된다.  
차이점은 Odoo가 개별 파라미터(host, port, user, password)를 필요로 한다는 것뿐.
