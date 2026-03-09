# PolyON-Odoo (PP Odoo)

PolyON Platform용 Odoo 19 모듈 — PRC(Platform Resource Claim) 기반 완전 자동 프로비저닝.

## 개요

Odoo 19 Community Edition을 PolyON Platform 모듈로 패키징.  
Console에서 설치 버튼 한 번으로 DB, S3, LDAP, SMTP, Redis가 자동 프로비저닝되고 Odoo가 기동된다.

## PRC Claims (5개)

| Claim | Foundation | 용도 |
|-------|-----------|------|
| database | PostgreSQL | Odoo 핵심 DB |
| objectStorage | RustFS (S3) | ir.attachment 파일 저장 |
| directory | Samba AD DC | 사원 LDAP 인증 |
| smtp | Stalwart Mail | 이메일 발송 |
| cache | Redis | 세션 스토어 |

## 문서

| 문서 | 설명 |
|------|------|
| [REQUIREMENTS.md](./REQUIREMENTS.md) | **요구사항 정의서** (12개 섹션) — 구현의 기준 |
| [QA.md](./QA.md) | 구현 전 Q&A 답변 |
| [polyon-module/module.yaml](./polyon-module/module.yaml) | PP 모듈 매니페스트 (PRC claims 포함) |

## 참조

| 문서 | 위치 |
|------|------|
| PP 플랫폼 규격 | [PolyON-platform](https://github.com/jupiter-ai-agent/PolyON-platform) |
| PRC Provider Reference | [prc-provider-reference.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/prc-provider-reference.md) |
| Module Spec | [module-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-spec.md) |
| Module Lifecycle | [module-lifecycle-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-lifecycle-spec.md) |
| Module UI Spec | [module-ui-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-ui-spec.md) |
| 참고 구현 (PP Drive) | [PolyON-Drive](https://github.com/jupiter-ai-agent/PolyON-Drive) |

## 프로젝트 구조 (완성 시)

```
PolyON-Odoo/
├── polyon-module/
│   └── module.yaml              # PP 모듈 매니페스트 (PRC 5 claims)
├── addons/
│   ├── polyon_s3_attachment/    # ir.attachment → RustFS S3 저장
│   ├── polyon_ldap_auto/       # PRC env → LDAP provider 자동 등록
│   ├── polyon_redis_session/   # Redis 세션 스토어
│   └── polyon_iframe/          # X-Frame-Options 제거, CSP 조정
├── config/
│   └── odoo.conf.template      # 환경변수 치환용 템플릿
├── entrypoint.sh               # PRC env → odoo.conf + addon 자동 설치
├── Dockerfile                  # Odoo 19.0 소스 빌드 (⛔ 공식 이미지 사용 금지)
├── .dockerignore
├── REQUIREMENTS.md             # 요구사항 정의서
├── QA.md                       # Q&A 답변
└── README.md
```

## 빌드 규칙

- **⛔ 공식 이미지 pull 금지** — 소스 빌드 원칙
- 소스: `https://github.com/odoo/odoo.git` (19.0 브랜치)
- 플랫폼: `linux/amd64` + `linux/arm64`
- 이미지: `jupitertriangles/polyon-odoo:v{semver}`

## 검증 Phase

| Phase | 목표 | 상태 |
|-------|------|------|
| Phase 1 | PRC 자동 설치 → `/web/health` 200 OK | 미착수 |
| Phase 2 | LDAP + S3 + SMTP + Redis 연동 | 미착수 |
| Phase 3 | Console/Portal iframe 통합 | 미착수 |
