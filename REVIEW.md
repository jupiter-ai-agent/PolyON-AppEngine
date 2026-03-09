# REVIEW.md — 1차 코드 리뷰 (Jupiter → Cursor)

> 리뷰 대상: commit `d4cf25a` (구현 초기 스캐폴딩 및 PRC 연동 기본 구조)  
> 리뷰어: Jupiter (AI 팀장) | 2026-03-09

---

## 총평

구조와 방향은 맞다. PRC 환경변수 매핑, 소스 빌드, addon 4개 구조, LDAP 자동등록 — 핵심을 잘 이해했다.  
아래 3건 수정 후 Phase 1 빌드 테스트 진행.

---

## 🔴 수정 필요 (3건)

### 1. S3 Attachment — 설정 저장만 있고 실제 저장 로직 없음

**현재 상태:**  
`polyon_s3_attachment/models/ir_config_parameter.py`가 PRC 환경변수를 `ir.config_parameter`에 저장하지만,  
실제로 `ir.attachment`의 파일 저장/읽기를 S3로 바꾸는 코드가 없다.

**설정 저장 ≠ 실제 S3 저장.** 현재 코드로는 파일이 여전히 로컬 filestore에 저장된다.

**필요한 것:**  
`ir.attachment` 모델의 `_file_write`, `_file_read`, `_file_delete`를 override하여  
boto3로 RustFS(S3)에 저장/읽기/삭제하는 코드.

```python
# addons/polyon_s3_attachment/models/ir_attachment.py (신규 파일)

import boto3
from odoo import models, api

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def _get_s3_client(self):
        ICP = self.env['ir.config_parameter'].sudo()
        endpoint = ICP.get_param('polyon_s3_attachment.aws_host', '')
        access_key = ICP.get_param('polyon_s3_attachment.aws_access_key_id', '')
        secret_key = ICP.get_param('polyon_s3_attachment.aws_secret_access_key', '')
        if not all([endpoint, access_key, secret_key]):
            return None, None
        bucket = ICP.get_param('polyon_s3_attachment.aws_bucket_name', 'odoo')
        client = boto3.client('s3',
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name='us-east-1',
        )
        return client, bucket

    def _file_write(self, bin_value, checksum):
        client, bucket = self._get_s3_client()
        if client is None:
            # S3 미설정 → 기본 filestore fallback (Phase 1 graceful skip)
            return super()._file_write(bin_value, checksum)
        fname = checksum[:2] + '/' + checksum
        client.put_object(Bucket=bucket, Key=fname, Body=bin_value)
        return fname

    def _file_read(self, fname):
        client, bucket = self._get_s3_client()
        if client is None:
            return super()._file_read(fname)
        try:
            response = client.get_object(Bucket=bucket, Key=fname)
            return response['Body'].read()
        except Exception:
            return super()._file_read(fname)

    def _file_delete(self, fname):
        client, bucket = self._get_s3_client()
        if client is None:
            return super()._file_delete(fname)
        try:
            client.delete_object(Bucket=bucket, Key=fname)
        except Exception:
            pass
```

**우선순위:** Phase 2. 하지만 파일 구조(`models/__init__.py`에 import)는 지금 잡아두면 좋다.

---

### 2. `odoo.conf.template` — Redis/SMTP 빈 값 방어

**현재 문제:**  
```ini
session_redis_host = ${SESSION_REDIS_HOST}
```
Redis claim이 없거나 env가 비어있으면 → `session_redis_host = ` (빈 문자열)  
→ Odoo가 빈 호스트로 Redis 연결 시도 → 에러 또는 기동 지연

**SMTP도 동일:**  
`smtp_server = ${SMTP_HOST}` — SMTP claim 미구성 시 빈 값 → Odoo가 빈 SMTP 서버로 연결 시도

**해결 방법:**  
entrypoint.sh에서 **조건부로 conf 섹션을 생성**하거나, `envsubst` 후 빈 값 줄을 제거.

```bash
# entrypoint.sh에 추가 — 빈 값 라인 정리
# envsubst 후, 값이 비어있는 설정 라인 제거
sed -i '/= $/d' "$ODOO_CONF_PATH"
```

또는 더 정확하게:

```bash
# Redis 설정 — env 없으면 conf에서 제거
if [ -z "$SESSION_REDIS_HOST" ]; then
  sed -i '/session_redis/d' "$ODOO_CONF_PATH"
fi

# SMTP 설정 — env 없으면 기본값 사용
if [ -z "$SMTP_HOST" ]; then
  sed -i '/smtp_server/d' "$ODOO_CONF_PATH"
  sed -i '/smtp_port/d' "$ODOO_CONF_PATH"
  sed -i '/smtp_user/d' "$ODOO_CONF_PATH"
  sed -i '/smtp_password/d' "$ODOO_CONF_PATH"
  sed -i '/smtp_ssl/d' "$ODOO_CONF_PATH"
fi
```

**우선순위:** Phase 1 필수. DB만으로 기동할 때 Redis/SMTP 에러가 나면 안 된다.

---

### 3. `docker-compose.dev.yml` 위치

**현재:** 프로젝트 루트에 `docker-compose.dev.yml` 존재.

**문제:**  
PP는 K8s 전용. compose 파일이 루트에 있으면 "compose로 실행하는 거 아닌가?" 혼란 유발.

**해결:**  
`dev/` 디렉토리로 이동하고 README에 "로컬 개발 테스트 전용" 명시.

```
dev/
└── docker-compose.yml    # 로컬 개발 테스트 전용 (PP 배포와 무관)
```

**우선순위:** 낮음. 기능 영향 없으나 정리 차원.

---

## ✅ 잘 된 것 (참고)

| 항목 | 평가 |
|------|------|
| Dockerfile: 소스 빌드, `/polyon-module` COPY | ✅ 요구사항 정확 준수 |
| entrypoint: `envsubst` 기반 conf 생성 | ✅ 깔끔한 접근 |
| entrypoint: `pg_isready` DB 대기 | ✅ 안정적 |
| entrypoint: 초기화 시 addon 자동 설치 (`-i`) | ✅ |
| entrypoint: 비밀번호 로그 마스킹 (`sed`) | ✅ 보안 의식 |
| LDAP: `sAMAccountName` 필터 | ✅ 요구사항 정확 |
| LDAP: `create_user = True` | ✅ |
| LDAP: 기존 설정 있으면 스킵 (멱등성) | ✅ |
| iframe: monkeypatch로 X-Frame-Options 제거 | ✅ |
| Redis: URL 파싱 → host/port/dbindex 분리 | ✅ |
| `.dockerignore` 포함 | ✅ |

---

## 수정 후 다음 단계

1. 위 3건 수정
2. Docker 이미지 빌드 테스트 (`docker build -t jupitertriangles/polyon-odoo:v0.1.0 .`)
3. PRC install API로 설치 테스트 (Phase 1: DB만으로 `/web/health` 200 확인)
