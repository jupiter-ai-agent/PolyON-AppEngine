# PolyON-Odoo (PP Odoo)

PolyON Platform용 Odoo 19 모듈 — PRC(Platform Resource Claim) 기반 완전 자동 프로비저닝.

## 개요

Odoo 19 Community Edition을 PolyON Platform 모듈로 패키징.  
설치 버튼 한 번으로 DB, S3, LDAP, SMTP, Redis가 자동 프로비저닝되고 Odoo가 기동된다.

## 참조 문서

| 문서 | 위치 | 설명 |
|------|------|------|
| **PP 플랫폼 규격** | [PolyON-platform](https://github.com/jupiter-ai-agent/PolyON-platform) | 전체 플랫폼 규약 |
| **PRC Provider Reference** | [prc-provider-reference.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/prc-provider-reference.md) | 8개 Provider 상세 명세 |
| **Module Spec** | [module-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-spec.md) | module.yaml 작성 규격 |
| **Module UI Spec** | [module-ui-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-ui-spec.md) | Console/Portal UI 통합 |
| **Module Lifecycle** | [module-lifecycle-spec.md](https://github.com/jupiter-ai-agent/PolyON-platform/blob/main/docs/module-lifecycle-spec.md) | 설치/삭제 라이프사이클 |
| **참고 구현 (PP Drive)** | [PolyON-Drive](https://github.com/jupiter-ai-agent/PolyON-Drive) | PRC 검증 완료된 샘플 모듈 |

## 요구사항

[REQUIREMENTS.md](./REQUIREMENTS.md) 참조.

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
├── Dockerfile                  # Odoo 19.0 소스 빌드 (공식 이미지 사용 금지)
├── .dockerignore
└── README.md
```
