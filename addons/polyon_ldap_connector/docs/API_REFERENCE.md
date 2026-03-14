# PolyON LDAP Connector - REST API Reference

## Overview

LDAP Sync Wizard의 데이터 조회 및 제어를 위한 REST API입니다.
외부 시스템(CI/CD, 모니터링, 자동화 스크립트 등)에서 LDAP 동기화를 원격으로 관리할 수 있습니다.

**Base URL**: `http://<odoo-host>:8069/api/v1/ldap-sync`

---

## Authentication

모든 API 요청에 **Odoo API Key**가 필요합니다. 관리자(`Settings` 그룹) 권한을 가진 사용자의 API Key만 허용됩니다.

### API Key 발급 방법

1. Odoo 웹 UI 로그인
2. 우측 상단 사용자 아이콘 > **My Profile**
3. **Account Security** 탭 > **New API Key** 클릭
4. 설명 입력 후 생성된 키 복사 (한 번만 표시됨)

### 인증 헤더 (둘 중 하나 선택)

```
X-API-Key: <your-api-key>
```

```
Authorization: Bearer <your-api-key>
```

### 인증 오류 응답

| Status | 의미 |
|--------|------|
| `401` | API Key 누락 또는 유효하지 않음 |
| `403` | 관리자 권한 없음 (Settings 그룹 필요) |

---

## API Endpoints

### 1. Status (전체 현황)

#### `GET /api/v1/ldap-sync/status`

전체 LDAP 동기화 상태 요약을 반환합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/status \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "status": [
    {
      "id": 9,
      "ldap_server": "ldap.openshift.co.kr",
      "sync_enabled": true,
      "sync_interval": 1,
      "total_users": 7,
      "sync_targets": 2,
      "total_groups": 7,
      "selected_groups": 3,
      "last_sync_date": "2026-03-14 08:00:00",
      "last_sync_status": "Sync: 2 synced, 5 archived, 3 groups, 0 removed, 0 errors"
    }
  ]
}
```

---

### 2. Wizards (위자드 관리)

#### `GET /api/v1/ldap-sync/wizards`

모든 LDAP Sync 위자드 목록을 반환합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/wizards \
  -H "X-API-Key: YOUR_API_KEY"
```

#### `GET /api/v1/ldap-sync/wizards/{wizard_id}`

특정 위자드의 상세 정보를 반환합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/wizards/9 \
  -H "X-API-Key: YOUR_API_KEY"
```

---

### 3. Groups (AD 그룹 - Tab 1)

#### `GET /api/v1/ldap-sync/wizards/{wizard_id}/groups`

AD 그룹 목록과 선택 상태를 조회합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/wizards/9/groups \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "wizard_id": 9,
  "total": 7,
  "selected": 3,
  "groups": [
    {
      "id": 15,
      "selected": true,
      "sequence": 1,
      "name": "Design",
      "description": "TRIANGLES 디자인",
      "member_count": 2,
      "ldap_dn": "CN=Design,OU=Groups,DC=openshift,DC=co,DC=kr",
      "exists_in_odoo": true
    }
  ]
}
```

#### `PUT /api/v1/ldap-sync/wizards/{wizard_id}/groups`

그룹 선택 상태를 변경합니다.

**개별 그룹 변경:**
```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/groups \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "groups": [
      {"id": 15, "selected": true},
      {"id": 16, "selected": false}
    ]
  }'
```

**전체 선택:**
```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/groups \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"select_all": true}'
```

**전체 해제:**
```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/groups \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"deselect_all": true}'
```

---

### 4. Users (AD 사용자 - Tab 2)

#### `GET /api/v1/ldap-sync/wizards/{wizard_id}/users`

AD 사용자 목록과 동기화 정책을 조회합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/wizards/9/users \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "wizard_id": 9,
  "total": 7,
  "sync_targets": 2,
  "users": [
    {
      "id": 42,
      "sync_mode": "group",
      "is_sync_target": true,
      "screen_name": "woojin.choi",
      "email": "woojin.choi@teps.co.kr",
      "first_name": "Woojin",
      "last_name": "Choi",
      "job_title": "Developer",
      "group_count": 3,
      "ldap_dn": "CN=Woojin Choi,OU=Users,DC=openshift,DC=co,DC=kr",
      "exists_in_odoo": true
    }
  ]
}
```

#### `PUT /api/v1/ldap-sync/wizards/{wizard_id}/users`

사용자 동기화 정책을 변경합니다.

**sync_mode 값:**
| 값 | 설명 |
|----|------|
| `group` | Group Policy - 선택된 그룹의 멤버이면 자동 동기화 |
| `enable` | Include - 그룹과 무관하게 항상 동기화 |
| `disable` | Exclude - 항상 제외 (아카이브) |

**개별 사용자 변경:**
```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/users \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "users": [
      {"id": 42, "sync_mode": "enable"},
      {"id": 43, "sync_mode": "disable"}
    ]
  }'
```

**전체 사용자 정책 일괄 변경:**
```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/users \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"set_all": "group"}'
```

---

### 5. Schedule (스케줄 설정 - Tab 3)

#### `GET /api/v1/ldap-sync/wizards/{wizard_id}/schedule`

스케줄 설정과 마지막 동기화 상태를 조회합니다.

```bash
curl -X GET http://localhost:8069/api/v1/ldap-sync/wizards/9/schedule \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "wizard_id": 9,
  "sync_enabled": true,
  "sync_interval": 5,
  "last_sync_date": "2026-03-14 08:00:00",
  "last_sync_status": "Sync: 2 synced, 5 archived, 3 groups, 0 removed, 0 errors",
  "last_sync_user_count": 2
}
```

#### `PUT /api/v1/ldap-sync/wizards/{wizard_id}/schedule`

스케줄 설정을 변경합니다.

```bash
curl -X PUT http://localhost:8069/api/v1/ldap-sync/wizards/9/schedule \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sync_enabled": true, "sync_interval": 5}'
```

---

### 6. Actions (실행)

#### `POST /api/v1/ldap-sync/wizards/{wizard_id}/refresh`

LDAP 서버에서 최신 사용자/그룹 데이터를 가져옵니다. 기존 정책(sync_mode, selected)은 유지됩니다.

```bash
curl -X POST http://localhost:8069/api/v1/ldap-sync/wizards/9/refresh \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "message": "Refresh completed",
  "user_count": 7,
  "group_count": 7
}
```

#### `POST /api/v1/ldap-sync/wizards/{wizard_id}/sync`

강력한 바인딩 정책으로 동기화를 실행합니다. UI의 **Sync Now** 버튼과 동일합니다.

동작:
1. 선택된 AD 그룹 → Odoo 그룹 동기화
2. 비선택 AD 그룹 → 멤버십 제거
3. 동기화 대상 사용자 → Odoo 계정 생성/업데이트 + `active=True`
4. 비대상 AD 사용자 → `active=False` (아카이브)

```bash
curl -X POST http://localhost:8069/api/v1/ldap-sync/wizards/9/sync \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "message": "Sync completed",
  "last_sync_date": "2026-03-14 08:30:00",
  "last_sync_status": "Sync: 2 synced, 5 archived, 3 groups, 0 removed, 0 errors",
  "last_sync_user_count": 2
}
```

#### `POST /api/v1/ldap-sync/wizards/{wizard_id}/refresh-and-sync`

Refresh + Sync를 순차적으로 실행합니다. Cron 자동 동기화와 동일한 동작입니다.

```bash
curl -X POST http://localhost:8069/api/v1/ldap-sync/wizards/9/refresh-and-sync \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "message": "Refresh and sync completed",
  "user_count": 7,
  "group_count": 7,
  "last_sync_date": "2026-03-14 08:30:00",
  "last_sync_status": "Sync: 2 synced, 5 archived, 3 groups, 0 removed, 0 errors",
  "last_sync_user_count": 2
}
```

---

## Error Responses

모든 에러는 동일한 형식으로 반환됩니다:

```json
{
  "error": "Error message description"
}
```

| HTTP Status | 의미 |
|-------------|------|
| `400` | 잘못된 요청 (유효하지 않은 JSON, 필수 파라미터 누락) |
| `401` | 인증 실패 (API Key 누락 또는 유효하지 않음) |
| `403` | 권한 부족 (관리자 그룹 필요) |
| `404` | 위자드를 찾을 수 없음 |
| `500` | 서버 오류 (LDAP 연결 실패 등) |

---

## Usage Examples

### Python

```python
import requests

BASE_URL = "http://localhost:8069/api/v1/ldap-sync"
HEADERS = {
    "X-API-Key": "YOUR_API_KEY",
    "Content-Type": "application/json",
}

# 전체 상태 확인
resp = requests.get(f"{BASE_URL}/status", headers=HEADERS)
print(resp.json())

# 그룹 선택 변경 후 동기화
requests.put(
    f"{BASE_URL}/wizards/9/groups",
    headers=HEADERS,
    json={"groups": [{"id": 15, "selected": True}, {"id": 16, "selected": False}]}
)

# Refresh + Sync 실행
resp = requests.post(f"{BASE_URL}/wizards/9/refresh-and-sync", headers=HEADERS)
print(resp.json())
```

### PowerShell

```powershell
$headers = @{
    "X-API-Key" = "YOUR_API_KEY"
    "Content-Type" = "application/json"
}

# 상태 조회
Invoke-RestMethod -Uri "http://localhost:8069/api/v1/ldap-sync/status" `
    -Headers $headers -Method GET

# 동기화 실행
Invoke-RestMethod -Uri "http://localhost:8069/api/v1/ldap-sync/wizards/9/sync" `
    -Headers $headers -Method POST
```

### CI/CD (GitHub Actions / Azure DevOps Pipeline)

```yaml
# Azure DevOps Pipeline example
steps:
  - script: |
      curl -X POST http://odoo-server:8069/api/v1/ldap-sync/wizards/9/refresh-and-sync \
        -H "X-API-Key: $(ODOO_API_KEY)"
    displayName: 'Trigger LDAP Sync'
```

---

## Security Notes

1. **API Key 보관**: 환경변수나 시크릿 매니저에 저장하세요. 소스코드에 하드코딩하지 마세요.
2. **HTTPS 권장**: 프로덕션 환경에서는 반드시 HTTPS (Nginx reverse proxy)를 사용하세요.
3. **관리자 전용**: `base.group_system` (Settings) 권한이 있는 사용자의 API Key만 허용됩니다.
4. **Rate Limiting**: 필요 시 Nginx에서 `limit_req_zone`으로 API 호출 빈도를 제한하세요.
5. **IP Whitelist**: 프로덕션에서는 Nginx `allow/deny`로 API 접근 IP를 제한하세요.
