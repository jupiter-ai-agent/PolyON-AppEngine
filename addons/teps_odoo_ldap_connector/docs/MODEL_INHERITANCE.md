# Odoo 모델 상속 및 데이터 저장 방식

## 1. Odoo 모델 상속 유형

Odoo는 3가지 모델 상속 방식을 제공합니다.

### 1.1 Classical Inheritance (`_inherit` only)

```python
class ResCompanyLdap(models.Model):
    _inherit = 'res.company.ldap'  # 기존 모델 확장

    # 새 필드 추가
    sync_groups = fields.Boolean()
```

**저장 방식:**
- **동일한 테이블**에 새 컬럼 추가
- 기존 `res_company_ldap` 테이블에 `sync_groups` 컬럼이 추가됨
- 모든 기존 레코드에 새 필드가 적용됨

**데이터베이스 변화:**
```sql
-- 기존 테이블
ALTER TABLE res_company_ldap ADD COLUMN sync_groups BOOLEAN;
ALTER TABLE res_company_ldap ADD COLUMN groups_dn VARCHAR;
-- ... 추가된 필드들
```

### 1.2 Prototype Inheritance (`_name` + `_inherit`)

```python
class CustomLdap(models.Model):
    _name = 'custom.ldap'           # 새로운 모델명
    _inherit = 'res.company.ldap'   # 기존 모델 복제
```

**저장 방식:**
- **새로운 테이블** 생성 (`custom_ldap`)
- 원본 모델의 모든 필드를 복사
- 원본 테이블과 완전히 독립적

### 1.3 Delegation Inheritance (`_inherits`)

```python
class Employee(models.Model):
    _name = 'hr.employee'
    _inherits = {'res.partner': 'partner_id'}

    partner_id = fields.Many2one('res.partner', required=True, ondelete='cascade')
```

**저장 방식:**
- **별도 테이블** + **Foreign Key** 연결
- 부모 모델 데이터는 부모 테이블에 저장
- 자식 모델 고유 데이터만 자식 테이블에 저장

---

## 2. 현재 모듈 (`teps_odoo_ldap_connector`) 분석

### 2.1 사용된 상속 방식

| 모델 | 상속 방식 | 대상 테이블 |
|------|----------|------------|
| `res.company.ldap` | Classical (`_inherit`) | `res_company_ldap` |
| `res.users` | Classical (`_inherit`) | `res_users` |

### 2.2 데이터베이스 구조

#### `res_company_ldap` 테이블 (확장됨)

```
기존 필드 (auth_ldap 모듈):
├── id
├── company_id
├── ldap_server
├── ldap_server_port
├── ldap_binddn
├── ldap_password
├── ldap_base
├── ldap_filter
├── ldap_tls
├── create_user
└── ...

추가된 필드 (teps_odoo_ldap_connector):
├── users_dn              -- Users Base DN
├── auth_search_filter    -- 인증용 검색 필터
├── user_search_filter    -- 사용자 검색 필터
├── ldap_attr_login       -- Screen Name 매핑
├── ldap_attr_lastname    -- Last Name 매핑
├── ldap_attr_email       -- Email 매핑
├── ldap_attr_fullname    -- Full Name 매핑
├── ldap_attr_firstname   -- First Name 매핑
├── ldap_attr_jobtitle    -- Job Title 매핑
├── ldap_attr_middlename  -- Middle Name 매핑
├── ldap_attr_photo       -- Portrait 매핑
├── groups_dn             -- Groups Base DN
├── sync_groups           -- AD 그룹 동기화 활성화
├── create_role_per_group -- 그룹별 역할 자동 생성
├── group_attribute       -- 그룹 속성명 (memberOf)
└── group_filter          -- 그룹 검색 필터
```

#### `res_users` 테이블

- 필드 추가 없음 (메서드만 확장)
- `_sync_ad_groups_for_user()` 등 헬퍼 메서드 추가

#### `res_groups` 테이블 (기존 활용)

- 필드 추가 없음
- AD에서 동기화된 그룹이 여기에 저장됨
- `category_id`로 "AD Groups" 카테고리 연결

#### `ir_module_category` 테이블 (데이터 추가)

```xml
<record id="module_category_ad_groups" model="ir.module.category">
    <field name="name">AD Groups</field>
</record>
```

### 2.3 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────┐
│                        LDAP 로그인 시                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  res.company.ldap._get_or_create_user()                         │
│  - 사용자 생성/조회                                               │
│  - sync_groups=True 면 그룹 동기화 트리거                         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  res.users._sync_ad_groups_for_user()                           │
│  - LDAP 엔트리에서 memberOf 추출                                  │
│  - DN에서 CN 파싱                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  res.users._get_or_create_odoo_group()                          │
│  - res_groups 테이블에서 그룹 검색                                │
│  - 없으면 새 그룹 생성 (create_role_per_group=True)              │
│  - category_id = "AD Groups"                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  res.users._update_user_ad_groups()                             │
│  - res_groups_users_rel 테이블 업데이트 (M2M 관계)               │
│  - AD 카테고리 그룹만 관리 (다른 그룹은 유지)                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 모듈 제거 시 처리

### 3.1 자동 처리 (Odoo 기본)

모듈 제거 시 Odoo가 자동으로 처리하는 항목:

| 항목 | 처리 방식 |
|------|----------|
| 추가된 필드 | 테이블에서 컬럼 삭제 |
| XML 데이터 (`noupdate="0"`) | 레코드 삭제 |
| 뷰 상속 | 뷰에서 제거 |
| 메뉴/액션 | 삭제 |

### 3.2 수동 처리 필요 항목

| 항목 | 이유 | 처리 방법 |
|------|------|----------|
| `ir_module_category` (AD Groups) | `noupdate="1"` | 직접 삭제 또는 유지 |
| 동기화된 `res_groups` | 사용자 생성 데이터 | 직접 삭제 또는 유지 |
| 사용자-그룹 관계 | 런타임 데이터 | 자동 정리 (그룹 삭제 시) |

### 3.3 안전한 제거 절차

```bash
# 1. AD 그룹 카테고리에 속한 그룹 확인
SELECT id, name FROM res_groups WHERE category_id = (
    SELECT id FROM ir_module_category WHERE name = 'AD Groups'
);

# 2. 필요시 그룹 삭제 (사용자-그룹 관계도 함께 삭제됨)
DELETE FROM res_groups WHERE category_id = (
    SELECT id FROM ir_module_category WHERE name = 'AD Groups'
);

# 3. 카테고리 삭제
DELETE FROM ir_module_category WHERE name = 'AD Groups';

# 4. 모듈 제거
./odoo-bin -d <db> -u base --stop-after-init
# 또는 UI에서 Apps > TEPS LDAP Connector > Uninstall
```

---

## 4. 권장 사항

### 4.1 현재 모듈 유지 관리

1. **버전 관리**: Git으로 `custom_addons/teps_odoo_ldap_connector` 관리
2. **백업**: 모듈 업데이트 전 DB 백업 권장
3. **테스트**: 개발 DB에서 먼저 테스트 후 운영 적용

### 4.2 추후 확장 시 고려사항

| 기능 | 권장 상속 방식 |
|------|--------------|
| 기존 모델에 필드 추가 | Classical (`_inherit`) |
| 완전히 새로운 엔티티 | 새 모델 (`_name`) |
| 기존 데이터 재사용 | Delegation (`_inherits`) |

---

## 5. 현재 모듈 테이블 스키마 확인

```sql
-- 추가된 필드 확인
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'res_company_ldap'
  AND column_name IN (
    'users_dn', 'auth_search_filter', 'user_search_filter',
    'ldap_attr_login', 'ldap_attr_lastname', 'ldap_attr_email',
    'ldap_attr_fullname', 'ldap_attr_firstname', 'ldap_attr_jobtitle',
    'ldap_attr_middlename', 'ldap_attr_photo',
    'groups_dn', 'sync_groups', 'create_role_per_group',
    'group_attribute', 'group_filter'
  )
ORDER BY column_name;
```

---

**문서 작성일**: 2026-01-08
**모듈 버전**: 19.0.1.0.0
**작성자**: Claude Code
