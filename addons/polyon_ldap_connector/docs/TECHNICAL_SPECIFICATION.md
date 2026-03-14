# PolyON LDAP Connector - Technical Specification

**Module:** `polyon_ldap_connector`
**Version:** 19.0.1.0.0
**Platform:** Odoo 19.0 (Python 3.10+, PostgreSQL 13+)
**License:** LGPL-3
**Author:** PolyON (https://www.polyon.co.kr)
**Depends:** `auth_ldap`
**External Dependencies:** `python-ldap`

---

## 1. Module Overview

Active Directory(AD) 사용자와 그룹을 Odoo와 동기화하는 모듈.
**강력한 바인딩 정책(Strong Binding Policy)** 을 적용하여 Sync Wizard에서 설정한 정책에 따라
사용자 활성화/아카이브, 그룹 멤버십 부여/제거를 자동으로 수행한다.

### 1.1 핵심 기능

| 기능 | 설명 |
|------|------|
| LDAP 로그인 시 자동 그룹 동기화 | `memberOf` 속성 기반 AD 그룹 → Odoo 그룹 매핑 |
| 3-State 사용자 정책 | Group Policy / Include / Exclude |
| 그룹 선택 기반 동기화 | 선택된 그룹의 멤버만 자동 Sync 대상 |
| 강력한 바인딩 정책 | 비대상 사용자 아카이브, 비선택 그룹 멤버십 제거 |
| 스케줄 동기화 | Cron을 통한 주기적 Refresh + Sync |
| 정책 영구 보존 | 위자드 데이터가 영구 저장, Refresh 시 기존 정책 유지 |

---

## 2. File Structure

```
polyon_ldap_connector/
├── __manifest__.py                              # 모듈 메타데이터
├── __init__.py                                  # Python imports + post_init_hook
├── models/
│   ├── __init__.py
│   ├── res_company_ldap.py                      # LDAP 서버 설정 확장
│   └── res_users.py                             # 사용자 모델 확장 (AD 그룹 동기화)
├── wizard/
│   ├── __init__.py
│   ├── ldap_sync_wizard.py                      # Sync Wizard (핵심 동기화 로직)
│   ├── ldap_sync_wizard_views.xml               # Sync Wizard UI (3탭)
│   ├── ldap_test_users_wizard.py                # LDAP 사용자 테스트 모달
│   ├── ldap_test_users_wizard_views.xml
│   ├── ldap_test_groups_wizard.py               # LDAP 그룹 테스트 모달
│   └── ldap_test_groups_wizard_views.xml
├── views/
│   ├── res_company_ldap_views.xml               # LDAP 설정 폼 확장
│   ├── res_users_views.xml                      # AD Users 전용 뷰
│   └── res_groups_views.xml                     # AD Groups 전용 뷰
├── security/
│   └── ir.model.access.csv                      # 접근 권한 정의
├── data/
│   ├── ldap_cron.xml                            # Cron Job 정의
│   └── ldap_group_category.xml                  # AD Groups 카테고리
├── static/src/css/
│   └── ldap_form.css                            # 폼 스타일링
└── docs/
    └── TECHNICAL_SPECIFICATION.md               # 본 문서
```

---

## 3. Data Models

### 3.1 `res.company.ldap` (Extension via `_inherit`)

**File:** `models/res_company_ldap.py`
기존 `auth_ldap` 모듈의 LDAP 서버 설정을 확장한다.

#### 3.1.1 추가 필드

**Users - Base DN & Search Filters:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `users_dn` | Char | - | 사용자 검색 Base DN (예: `OU=Users,DC=company,DC=com`) |
| `auth_search_filter` | Char | `(&(objectClass=person)(userPrincipalName=%(user)s))` | 인증 시 사용할 LDAP 필터 |
| `user_search_filter` | Char | `(&(objectClass=person)(!(isCriticalSystemObject=TRUE))(!(userPrincipalName=*sys@*)))` | 대량 사용자 동기화 필터 |

**Users - Attribute Mapping (LDAP Attribute → Odoo Field):**

| Field | Type | Default | Maps To |
|-------|------|---------|---------|
| `ldap_attr_login` | Char | `sAMAccountName` | `res.users.login` |
| `ldap_attr_email` | Char | `userPrincipalName` | `res.users.email` |
| `ldap_attr_fullname` | Char | `displayName` | `res.users.name` |
| `ldap_attr_firstname` | Char | `givenName` | (위자드 표시용) |
| `ldap_attr_lastname` | Char | `sn` | (위자드 표시용) |
| `ldap_attr_jobtitle` | Char | `title` | (위자드 표시용) |
| `ldap_attr_middlename` | Char | `middleName` | (위자드 표시용) |
| `ldap_attr_photo` | Char | `thumbnailPhoto` | (향후 확장용) |

**Groups - Synchronization Settings:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `groups_dn` | Char | - | 그룹 검색 Base DN |
| `sync_groups` | Boolean | `True` | AD 그룹 동기화 활성화 |
| `create_role_per_group` | Boolean | `True` | AD 그룹당 Odoo 그룹 자동 생성 |
| `group_attribute` | Char | `memberOf` | 그룹 멤버십 LDAP 속성 |
| `group_filter` | Char | `(objectClass=group)` | 그룹 검색 LDAP 필터 |

**Sync Status (Read-only, Sync Wizard에 의해 업데이트):**

| Field | Type | Description |
|-------|------|-------------|
| `last_sync_date` | Datetime | 마지막 동기화 시각 |
| `last_sync_status` | Char | 마지막 동기화 결과 메시지 |
| `last_sync_user_count` | Integer | 마지막 동기화된 사용자 수 |

#### 3.1.2 주요 메서드

| Method | Description |
|--------|-------------|
| `_get_or_create_user(conf, login, ldap_entry)` | 사용자 생성/조회 후 AD 그룹 동기화 (Override) |
| `_map_ldap_attributes(conf, login, ldap_entry)` | LDAP 속성 → Odoo 필드 매핑 (Override) |
| `_query_ldap_users_and_groups()` | LDAP 서버에서 사용자/그룹 데이터 조회 (Shared Helper) |
| `action_open_sync_wizard()` | Sync Wizard 열기 (기존 위자드 재사용 또는 신규 생성) |
| `action_test_ldap_users()` | LDAP 사용자 테스트 모달 |
| `action_test_ldap_groups()` | LDAP 그룹 테스트 모달 |

---

### 3.2 `res.users` (Extension via `_inherit`)

**File:** `models/res_users.py`
사용자 모델에 LDAP 소스 추적 및 AD 그룹 동기화 기능을 추가한다.

#### 3.2.1 추가 필드

| Field | Type | Stored | Description |
|-------|------|--------|-------------|
| `ldap_id` | Many2one(`res.company.ldap`) | Yes | LDAP 서버 소스 (readonly) |
| `ldap_dn` | Char | Yes | LDAP Distinguished Name (readonly) |
| `is_ldap_user` | Boolean | Yes (computed) | LDAP 사용자 여부 |
| `ad_group_ids` | Many2many (computed) | No | AD에서 동기화된 그룹만 필터링 |

#### 3.2.2 주요 메서드

| Method | Description |
|--------|-------------|
| `_sync_ad_groups_for_user(ldap_config, ldap_entry)` | 단일 사용자의 AD 그룹 동기화 |
| `_extract_cn_from_dn(dn)` | DN에서 CN 값 추출 (예: `CN=Sales,OU=Groups,...` → `Sales`) |
| `_get_or_create_odoo_group(group_name, source_dn, category_id, auto_create)` | Odoo 그룹 검색 또는 생성 |
| `_update_user_ad_groups(new_group_ids, ad_category)` | 사용자의 AD 그룹 관계 업데이트 (Command API 사용) |

**AD 그룹 식별 방법:** `res.groups.comment` 필드에 `[AD Group]` 문자열 포함 여부로 판별.

---

### 3.3 `ldap.sync.wizard` (Persistent Model)

**File:** `wizard/ldap_sync_wizard.py`
Sync Wizard의 핵심 모델. `models.Model` 기반으로 영구 저장되며, LDAP 서버당 1개만 존재한다.

#### 3.3.1 필드

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ldap_id` | Many2one | (required) | LDAP 서버 참조 |
| `ldap_server_name` | Char (related) | - | 서버 호스트명 (표시용) |
| `user_line_ids` | One2many | - | 사용자 라인 목록 |
| `group_line_ids` | One2many | - | 그룹 라인 목록 |
| `user_count` | Integer (computed) | - | 전체 사용자 수 |
| `group_count` | Integer (computed) | - | 전체 그룹 수 |
| `sync_user_count` | Integer (computed) | - | Sync 대상 사용자 수 |
| `selected_group_count` | Integer (computed) | - | 선택된 그룹 수 |
| `sync_enabled` | Boolean | `False` | 스케줄 동기화 활성화 |
| `sync_interval` | Integer | `60` | 동기화 간격 (분) |
| `last_sync_date` | Datetime (readonly) | - | 마지막 동기화 시각 |
| `last_sync_status` | Char (readonly) | - | 마지막 동기화 결과 |
| `last_sync_user_count` | Integer (readonly) | - | 마지막 동기화된 사용자 수 |

#### 3.3.2 DB 제약 조건

```
UNIQUE(ldap_id) — LDAP 서버당 위자드 1개만 허용
```

#### 3.3.3 주요 메서드

| Method | Return | Description |
|--------|--------|-------------|
| `write(vals)` | bool | `sync_enabled`/`sync_interval` 변경 시 cron 간격 자동 동기화 |
| `_update_cron_interval()` | None | 활성 위자드 중 최소 interval을 cron에 반영 |
| `action_refresh_from_ldap()` | action | LDAP에서 최신 데이터 갱신, 기존 정책 보존 |
| `action_sync_selected()` | action | 강력한 바인딩 정책 동기화 실행 |
| `_cron_sync_ldap()` | None | Cron entry point: `sync_enabled=True`인 위자드에 대해 refresh → sync |
| `action_set_all_users_enable()` | False | 전체 사용자 Include |
| `action_set_all_users_disable()` | False | 전체 사용자 Exclude |
| `action_set_all_users_group()` | False | 전체 사용자 Group Policy |
| `action_select_all_groups()` | False | 전체 그룹 선택 |
| `action_deselect_all_groups()` | False | 전체 그룹 해제 |
| `_get_selected_group_dns()` | set | 선택된 그룹의 DN 집합 반환 |

---

### 3.4 `ldap.sync.wizard.user.line` (Persistent Model)

사용자별 동기화 정책 및 LDAP 속성을 저장하는 라인 모델.

#### 3.4.1 필드

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `wizard_id` | Many2one (cascade) | (required) | 부모 위자드 |
| `sync_mode` | Selection | `'group'` | `group` / `enable` / `disable` |
| `is_sync_target` | Boolean (computed, stored) | - | 동기화 대상 여부 |
| `screen_name` | Char | - | LDAP 로그인명 |
| `email` | Char | - | 이메일 |
| `first_name` | Char | - | 이름 |
| `last_name` | Char | - | 성 |
| `job_title` | Char | - | 직함 |
| `group_count` | Integer | - | 소속 AD 그룹 수 |
| `member_group_dns` | Text | - | 소속 그룹 DN 목록 (JSON Array) |
| `ldap_dn` | Char (required) | - | LDAP Distinguished Name |
| `ldap_entry_data` | Text | - | 전체 LDAP 엔트리 (JSON Object) |
| `exists_in_odoo` | Boolean (computed) | - | Odoo에 해당 사용자 존재 여부 |

#### 3.4.2 DB 제약 조건

```
UNIQUE(wizard_id, ldap_dn) — 위자드 내 사용자 중복 방지
```

#### 3.4.3 Sync Target 판정 로직

```python
def _is_sync_target(self, selected_group_dns=None):
    if self.sync_mode == 'enable':
        return True                                    # 무조건 동기화
    if self.sync_mode == 'disable':
        return False                                   # 무조건 제외
    # sync_mode == 'group':
    if not selected_group_dns:
        return False
    user_groups = set(json.loads(self.member_group_dns or '[]'))
    return bool(user_groups & selected_group_dns)      # 교집합 존재 시 동기화
```

**Dependencies (stored compute):**
- `sync_mode` — 자신의 정책 변경
- `member_group_dns` — LDAP 그룹 멤버십 변경
- `wizard_id.group_line_ids.selected` — 그룹 선택 상태 변경

---

### 3.5 `ldap.sync.wizard.group.line` (Persistent Model)

그룹별 선택 상태 및 LDAP 속성을 저장하는 라인 모델.

#### 3.5.1 필드

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `wizard_id` | Many2one (cascade) | (required) | 부모 위자드 |
| `selected` | Boolean | `True` | 동기화 대상 선택 여부 |
| `sequence` | Integer | - | 표시 순서 |
| `name` | Char | - | 그룹명 (CN) |
| `description` | Char | - | 그룹 설명 |
| `member_count` | Integer | - | 멤버 수 |
| `ldap_dn` | Char (required) | - | LDAP Distinguished Name |
| `exists_in_odoo` | Boolean (computed) | - | Odoo에 해당 그룹 존재 여부 |

#### 3.5.2 DB 제약 조건

```
UNIQUE(wizard_id, ldap_dn) — 위자드 내 그룹 중복 방지
```

---

### 3.6 Test Wizard Models (Transient)

| Model | Type | Purpose |
|-------|------|---------|
| `ldap.test.users.wizard` | TransientModel | LDAP 사용자 조회 테스트 (최대 50명) |
| `ldap.test.users.wizard.line` | TransientModel | 테스트 사용자 라인 |
| `ldap.test.groups.wizard` | TransientModel | LDAP 그룹 조회 테스트 (최대 50개) |
| `ldap.test.groups.wizard.line` | TransientModel | 테스트 그룹 라인 |

---

## 4. Core Algorithms

### 4.1 강력한 바인딩 정책 (Strong Binding Policy)

`action_sync_selected()` 실행 시 적용되는 4단계 동기화:

```
Step 1: 선택된 그룹 → Odoo에 생성/확인
   ├── res.users._get_or_create_odoo_group() 호출
   └── comment에 '[AD Group]' 태그 부착

Step 2: 비선택 그룹 → AD 사용자에서 멤버십 제거
   ├── comment에 '[AD Group]'이 있는 res.groups 검색
   ├── 해당 그룹에 속한 ldap_id 일치 사용자 검색
   └── group_ids: [(3, group_id)] 로 멤버십 제거

Step 3: Sync 대상 사용자 → 동기화 + active=True
   ├── active_test=False로 아카이브된 사용자도 검색
   ├── 기존 사용자: _map_ldap_attributes()로 업데이트
   │   └── active=False였으면 active=True로 재활성화
   ├── 신규 사용자: _get_or_create_user()로 생성
   └── sync_groups 활성 시 _sync_ad_groups_for_user() 호출

Step 4: 비대상 AD 사용자 → active=False (아카이브)
   ├── ldap_id가 현재 서버인 사용자만 대상
   └── active=True인 사용자를 active=False로 변경
```

### 4.2 LDAP 데이터 갱신 (Refresh from LDAP)

`action_refresh_from_ldap()` — 기존 정책을 유지하면서 LDAP 데이터를 최신으로 갱신:

```
Step 1: LDAP 서버 조회
   └── _query_ldap_users_and_groups() 호출

Step 2: 사용자 라인 갱신
   ├── 기존 DN → 속성만 업데이트 (sync_mode 유지)
   ├── 새 DN → sync_mode='group'(기본값)으로 추가
   └── LDAP에서 삭제된 DN → 위자드 라인 제거

Step 3: 그룹 라인 갱신
   ├── 기존 DN → 속성만 업데이트 (selected 유지)
   ├── 새 DN → selected=True(기본값)으로 추가
   └── LDAP에서 삭제된 DN → 위자드 라인 제거
```

### 4.3 Cron 스케줄 동기화

```
_cron_sync_ldap() [5분마다 실행]
   │
   ├── sync_enabled=True인 위자드 조회
   │
   └── 각 위자드에 대해:
       ├── action_refresh_from_ldap()  ← LDAP 최신 데이터 가져오기
       └── action_sync_selected()      ← 강력한 바인딩 정책 적용
```

**Cron 간격 자동 동기화:**
- `sync_enabled` 또는 `sync_interval` 변경 시 `write()` Override에서 `_update_cron_interval()` 호출
- 활성 위자드 중 최소 interval이 cron에 반영됨
- 활성 위자드가 없으면 cron 비활성화

### 4.4 LDAP 로그인 시 그룹 동기화

```
사용자 LDAP 로그인
   │
   └── res.company.ldap._get_or_create_user() [Override]
       ├── super()._get_or_create_user() 호출
       ├── ldap_id, ldap_dn 설정
       └── sync_groups=True이면:
           └── res.users._sync_ad_groups_for_user()
               ├── memberOf 속성에서 그룹 DN 목록 추출
               ├── 각 DN에서 CN 추출
               ├── _get_or_create_odoo_group()으로 Odoo 그룹 매핑
               └── _update_user_ad_groups()로 그룹 관계 업데이트
                   ├── Command (3, id) — 기존 AD 그룹 중 새 목록에 없는 것 제거
                   └── Command (4, id) — 새 그룹 중 현재 없는 것 추가
```

---

## 5. User Interface

### 5.1 Menu Structure

```
Settings
└── Users & Companies
    └── LDAP
        ├── LDAP Servers          (auth_ldap 기본 목록)
        ├── AD Users              (LDAP 사용자 전용 목록)
        └── AD Groups             (LDAP 그룹 전용 목록)
```

### 5.2 LDAP Server Form (확장)

기존 `auth_ldap` 폼에 다음 섹션 추가:

```
[Header]
  Back to List | Test Connection | Test LDAP Users | Test LDAP Groups | Sync Users & Groups

[Sheet]
  (기본 LDAP 설정)

  ──── Users & Groups ────

  ── USERS ──
  Users DN

  ── SEARCH ──
  Authentication Search Filter
  User Search Filter

  ── USER MAPPING ──
  Screen Name    | Last Name
  Email Address  | Full Name
  First Name     | Job Title
  Middle Name    | Group (memberOf)

  ── GROUPS ──
  Groups DN
  Group Filter
  Sync AD Groups
  Create Role Per Group

  ── SYNC STATUS ──
  Last Sync Date     | Last Sync User Count
  Last Sync Status   |
```

### 5.3 Sync Wizard Form (3 Tabs)

```
[Header]
  Refresh from LDAP | Sync Now

[Tab 1: Groups]
  (정보 배너: 그룹 선택 → 멤버 자동 동기화)
  [N/M selected]  [Select All] [Deselect All]
  ┌─────────┬───┬──────────────┬─────────┬───────┬────────┐
  │ Select  │ # │ Name         │ Desc    │ Members│ In Odoo│
  ├─────────┼───┼──────────────┼─────────┼───────┼────────┤
  │ [toggle]│ 1 │ Design       │ ...     │ 3     │ ✓      │
  │ [toggle]│ 2 │ DevOps       │ ...     │ 1     │ ✓      │
  └─────────┴───┴──────────────┴─────────┴───────┴────────┘

[Tab 2: Users]
  (정보 배너: Group Policy/Include/Exclude 설명)
  [N/M will sync]  [All Group Policy] [All Include] [All Exclude]
  ┌──────────┬──────┬────────┬──────────┬──────┬──────┬────────┐
  │ Policy   │ Sync │ Name   │ Email    │ First│ Last │ In Odoo│
  ├──────────┼──────┼────────┼──────────┼──────┼──────┼────────┤
  │ [dropdown]│ ✓   │ cmars  │ c@...    │ Mars │ Choi │ ✓      │
  │ Exclude  │      │ geea   │ g@...    │ Jia  │ Choi │ ✓      │
  └──────────┴──────┴────────┴──────────┴──────┴──────┴────────┘
  (decoration-success: sync 대상, decoration-muted: 비대상)

[Tab 3: Schedule]
  ┌── Scheduled Sync ──┬── Last Sync Status ──┐
  │ Enable Scheduled   │ Last Sync Date       │
  │ Interval (minutes) │ Last Sync Users      │
  │                    │ Last Sync Status     │
  └────────────────────┴──────────────────────┘
  (정보 배너: cron 동작 설명)
```

---

## 6. Security

### 6.1 Access Control (ir.model.access.csv)

| Model | Group | Read | Write | Create | Delete |
|-------|-------|------|-------|--------|--------|
| `res.company.ldap` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.sync.wizard` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.sync.wizard.user.line` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.sync.wizard.group.line` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.test.users.wizard` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.test.users.wizard.line` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.test.groups.wizard` | `base.group_system` | 1 | 1 | 1 | 1 |
| `ldap.test.groups.wizard.line` | `base.group_system` | 1 | 1 | 1 | 1 |

**접근 제한:** 모든 모델은 `base.group_system` (시스템 관리자)만 접근 가능.

---

## 7. Data (noupdate)

### 7.1 Cron Job

```xml
<record id="ir_cron_ldap_user_import" model="ir.cron">
    <field name="name">LDAP: Sync Users &amp; Groups</field>
    <field name="model_id" ref="model_ldap_sync_wizard"/>
    <field name="code">model._cron_sync_ldap()</field>
    <field name="interval_number">5</field>
    <field name="interval_type">minutes</field>
    <field name="active" eval="True"/>
</record>
```

- 기본 5분 간격, 위자드에서 `sync_interval` 설정 시 자동 변경
- `sync_enabled=True`인 위자드가 없으면 자동 비활성화

### 7.2 AD Groups Category

```xml
<record id="module_category_ad_groups" model="ir.module.category">
    <field name="name">AD Groups</field>
    <field name="sequence">100</field>
</record>
```

### 7.3 Post-Init Hook

기존 DB에서 cron의 `model_id`를 `res.company.ldap` → `ldap.sync.wizard`로 마이그레이션:

```python
def _post_init_update_cron(env):
    cron = env.ref('polyon_ldap_connector.ir_cron_ldap_user_import')
    if cron:
        model = env['ir.model'].search([('model', '=', 'ldap.sync.wizard')])
        if model and cron.ir_actions_server_id:
            cron.ir_actions_server_id.write({
                'model_id': model.id,
                'code': 'model._cron_sync_ldap()',
            })
```

---

## 8. Database Constraints

| Model | Constraint | SQL | Purpose |
|-------|-----------|-----|---------|
| `ldap.sync.wizard` | `_ldap_id_unique` | `UNIQUE(ldap_id)` | LDAP 서버당 위자드 1개 |
| `ldap.sync.wizard.user.line` | `_wizard_dn_unique` | `UNIQUE(wizard_id, ldap_dn)` | 사용자 중복 방지 |
| `ldap.sync.wizard.group.line` | `_wizard_dn_unique` | `UNIQUE(wizard_id, ldap_dn)` | 그룹 중복 방지 |

---

## 9. LDAP Queries

### 9.1 User Query

```
Base DN : users_dn || ldap_base
Scope   : SUBTREE
Filter  : user_search_filter || ldap_filter || (objectClass=person)
Timeout : 30 seconds
```

**추출 속성:**
- `sAMAccountName` → screen_name
- `userPrincipalName` → email
- `givenName` → first_name
- `sn` → last_name
- `title` → job_title
- `displayName` → name (Odoo)
- `memberOf` → member_group_dns (JSON Array)
- 전체 entry → ldap_entry_data (JSON Object)

### 9.2 Group Query

```
Base DN : groups_dn || ldap_base
Scope   : SUBTREE
Filter  : group_filter || (objectClass=group)
Timeout : 30 seconds
```

**추출 속성:**
- `cn` / `name` → group name
- `description` → description
- `member` → member_count (count only)

---

## 10. AD Group Identification

AD에서 동기화된 그룹은 `res.groups.comment` 필드에 다음 형식으로 태깅:

```
[AD Group] Auto-created from Active Directory.
Source DN: CN=GroupName,CN=Users,DC=openshift,DC=co,DC=kr
```

**식별 조건:** `comment LIKE '%[AD Group]%'`

이 태그는 다음 용도로 사용:
1. AD 그룹 필터링 (`ad_group_ids` computed field)
2. 비선택 그룹 멤버십 제거 시 AD 그룹만 대상
3. AD Users/Groups 전용 뷰에서 필터링

---

## 11. 3-State Sync Policy

### 11.1 사용자 정책 (sync_mode)

| 값 | 라벨 | 동작 |
|----|------|------|
| `group` | Group Policy | 선택된 그룹의 멤버이면 Sync, 아니면 Archive |
| `enable` | Include | 그룹 소속과 무관하게 항상 Sync |
| `disable` | Exclude | 항상 Archive |

### 11.2 판정 우선순위

```
1. sync_mode == 'enable'  → 무조건 Sync (최우선)
2. sync_mode == 'disable' → 무조건 Archive
3. sync_mode == 'group'   → 선택된 그룹과 memberOf 교집합으로 판정
```

### 11.3 Sync 결과 동작

| 판정 | 기존 Odoo 사용자 | 신규 사용자 |
|------|-----------------|------------|
| **Sync 대상** | 속성 업데이트 + `active=True` 보장 + 그룹 동기화 | `_get_or_create_user()`로 생성 |
| **비대상** | `active=False` (아카이브) | 생성하지 않음 |

---

## 12. View XML IDs

| XML ID | Model | Type | Description |
|--------|-------|------|-------------|
| `view_ldap_installer_form_inherit` | `res.company.ldap` | form (inherit) | LDAP 설정 폼 확장 |
| `view_ldap_installer_tree_inherit` | `res.company.ldap` | tree (inherit) | LDAP 목록 확장 |
| `view_ldap_sync_wizard_form` | `ldap.sync.wizard` | form | Sync Wizard 폼 |
| `view_ad_users_tree` | `res.users` | tree | AD Users 목록 |
| `view_ad_users_form` | `res.users` | form | AD Users 상세 |
| `action_ad_users` | - | action | AD Users 액션 |
| `menu_ad_users` | - | menu | AD Users 메뉴 |
| `view_ad_groups_tree` | `res.groups` | tree | AD Groups 목록 |
| `view_ad_groups_form` | `res.groups` | form | AD Groups 상세 |
| `action_ad_groups` | - | action | AD Groups 액션 |
| `menu_ad_groups` | - | menu | AD Groups 메뉴 |
| `ldap_test_users_wizard_form` | `ldap.test.users.wizard` | form | 사용자 테스트 모달 |
| `ldap_test_groups_wizard_form` | `ldap.test.groups.wizard` | form | 그룹 테스트 모달 |

---

## 13. Dependencies & Requirements

### 13.1 Odoo Modules

| Module | Purpose |
|--------|---------|
| `auth_ldap` | 기본 LDAP 인증 프레임워크 (`res.company.ldap` 모델 제공) |

### 13.2 Python Packages

| Package | Purpose |
|---------|---------|
| `python-ldap` | LDAP 프로토콜 통신 (`ldap.SCOPE_SUBTREE`, `search_st()`, `simple_bind_s()`) |

### 13.3 Infrastructure

| Component | Requirement |
|-----------|-------------|
| LDAP/AD Server | Active Directory 또는 LDAP v3 호환 서버 |
| Network | Odoo 서버 → LDAP 서버 (TCP 389 또는 636/LDAPS) |
| PostgreSQL | 13+ |
| Python | 3.10 ~ 3.13 |

---

## 14. CSS Styling

**File:** `static/src/css/ldap_form.css`

```css
/* Input 배경색: 연한 회색 */
.o_form_view .o_field_widget input[type="text"],
.o_form_view .o_field_widget textarea {
    background-color: #f5f5f5;
}

/* Focus 시 흰색 */
.o_form_view .o_field_widget input[type="text"]:focus,
.o_form_view .o_field_widget textarea:focus {
    background-color: #ffffff;
}
```

---

## 15. Revision History

| Date | Version | Description |
|------|---------|-------------|
| 2026-03-14 | 19.0.1.0.0 | Auto Import와 Sync Wizard 통합, 강력한 바인딩 정책 구현, 스케줄 동기화 추가 |
