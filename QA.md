# QA.md — 구현 전 Q&A (Jupiter → Cursor)

> 이 문서는 Cursor의 사전 질문에 대한 팀장(Jupiter)의 공식 답변이다.

---

## 1. Odoo 소스/브랜치

- **Odoo 19.0** Community Edition (`https://github.com/odoo/odoo.git`, `19.0` 브랜치)
- **소스 빌드 필수** — `FROM odoo:19` 같은 공식 이미지 래퍼 사용 금지
- PolyON-Odoo는 **Odoo 소스 clone + 커스텀 addon + entrypoint**로 구성
- git submodule/subtree 불필요 — Dockerfile에서 `git clone --depth 1 --branch 19.0`

---

## 2. 배포/실행 모델

- **K8s 전용** — docker-compose 없음
- PRC가 K8s Deployment/Service/Ingress를 자동 생성
- `odoo.conf`는 **entrypoint에서 PRC 환경변수를 읽어 동적 생성** — 볼륨 마운트 방식 아님
- REQUIREMENTS.md §5.2의 entrypoint.sh 패턴을 따를 것

---

## 3. PRC Claims / 환경변수

- **PRC Provider Reference의 credential key를 그대로 사용**
- `module.yaml`의 `spec.env`에서 Odoo가 필요한 환경변수명으로 매핑
- 추가 env는 `spec.env`에 정적값으로 선언 가능 (예: `ODOO_WORKERS: "2"`)
- **Phase 1 필수: database만** — LDAP/S3/SMTP/Redis는 env가 비어있으면 해당 기능 비활성화 상태로 Odoo 기동 허용
- 5개 claims 모두 `module.yaml`에 선언하되, entrypoint에서 빈 값이면 스킵하는 방어 코드 작성

---

## 4. Phase 1 성공 기준

- **`/web/health` HTTP 200** — Odoo 19 내장 헬스체크 엔드포인트
- `/web/login` 화면 렌더링은 사람이 브라우저로 확인
- K8s readiness/liveness probe는 `module.yaml`에 `/web/health:8069` 정의됨
- 별도 헬스체크 스크립트 불필요

---

## 5. Phase 2 구체도

### LDAP
- Samba AD DC — `sAMAccountName` 기준 인증
- Odoo 기본 `auth_ldap` 모듈의 기본값으로 시작
- LDAP filter: `(&(objectClass=user)(sAMAccountName=%s))`
- 추가 스키마 제약 없음

### S3
- **모든 attachment를 S3로** — filestore 전체를 RustFS로 보내는 전략
- 로컬 `/var/lib/odoo/filestore` 사용 금지

### SMTP
- PRC env: host, port, user, password 4개
- **STARTTLS** (port 587) 기본 — `smtp_ssl = True` 고정
- TLS 모드 env 제어 불필요

---

## 6. Phase 3 iframe

- **Console:** `https://console.cmars.com` → `/modules/odoo/` 경로로 iframe
- **Portal:** `https://portal.cmars.com` → 동일 패턴
- **Odoo 쪽에서 처리할 것:**
  - `X-Frame-Options` 제거 또는 `ALLOWALL`
  - CSP `frame-ancestors *`
  - odoo.conf 또는 커스텀 addon의 HTTP response header로 설정
- Console/Portal 쪽은 이미 iframe 허용 구조 (ModuleSector 컴포넌트)

---

## 요약

| 질문 | 답변 |
|------|------|
| 소스/브랜치 | Odoo 19.0, 소스 빌드 |
| 실행 모델 | K8s 전용, compose 없음 |
| odoo.conf | entrypoint에서 PRC env → 동적 생성 |
| env 래핑 | PRC key 그대로, module.yaml에서 매핑 |
| 필수 claim | Phase 1은 DB만, 나머지는 graceful skip |
| 성공 기준 | `/web/health` 200 OK |
| LDAP | sAMAccountName, auth_ldap 기본값 |
| S3 | 전체 attachment S3 전환 |
| SMTP | STARTTLS 587, 고정 |
| iframe | Odoo 측 X-Frame-Options 제거 |
