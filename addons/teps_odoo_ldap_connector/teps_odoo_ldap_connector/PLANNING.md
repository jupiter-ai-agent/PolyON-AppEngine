# TEPS-odoo-LDAP-Connector 모듈 개발 계획서

**문서 버전**: 1.0
**작성일**: 2026-01-08
**프로젝트**: 현대프로젝트 Odoo 19 LDAP 그룹 동기화

---

## 1. 프로젝트 개요

### 1.1 배경
- Odoo 19 기본 `auth_ldap` 모듈은 LDAP 인증만 제공하고 그룹 동기화를 지원하지 않음
- OCA의 `users_ldap_groups` 모듈은 Odoo 17.0까지만 포팅됨 (19.0 미지원)
- Active Directory의 그룹 구조를 Odoo에 그대로 반영해야 하는 요구사항 존재

### 1.2 목표
Active Directory 그룹을 **매핑 테이블 없이** Odoo 그룹으로 직접 동기화하여, Odoo UI에서 해당 그룹에 세부 권한을 설정할 수 있도록 함

### 1.3 핵심 요구사항

| 요구사항 | 설명 |
|---------|------|
| AD 그룹 직접 가져오기 | memberOf 속성에서 CN 추출 → Odoo res.groups에 동일 이름으로 생성/연결 |
| 매핑 테이블 제거 | AD그룹 ↔ Odoo그룹 간 별도 매핑 구조 없음 |
| 자동 그룹 생성 | Odoo에 없는 AD 그룹은 자동 생성 |
| Odoo UI 권한 설정 | 생성된 그룹에 표준 Odoo UI로 ir.model.access, ir.rule 설정 |

---

## 2. 기술 환경

### 2.1 인프라 정보

| 구성 요소 | 정보 |
|----------|------|
| Odoo | 19.0 Community Edition |
| PostgreSQL | 18 (StackGres HA) |
| LDAP Server | ldap.openshift.co.kr (10.10.1.4:389) |
| Bind DN | Admin.sys@openshift.co.kr |
| Base DN | CN=Users,DC=openshift,DC=co,DC=kr |
| 플랫폼 | K3s 클러스터 (openshift-odoo 네임스페이스) |

### 2.2 관련 Odoo 테이블

| 테이블 | 용도 |
|--------|------|
| `res_company_ldap` | LDAP 서버 설정 |
| `res_users` | 사용자 정보 |
| `res_groups` | 보안 그룹 (name은 jsonb 타입) |
| `res_groups_users_rel` | 사용자-그룹 관계 |
| `ir_model_access` | 모델 CRUD 권한 |
| `ir_rule` | 레코드 수준 접근 규칙 |

---

## 3. 모듈 설계

### 3.1 모듈 구조

```
teps_odoo_ldap_connector/
├── __manifest__.py          # 모듈 메타데이터
├── __init__.py              # Python imports
├── models/
│   ├── __init__.py
│   ├── res_company_ldap.py  # LDAP 설정 확장
│   └── res_users.py         # 그룹 동기화 로직
├── views/
│   └── res_company_ldap_views.xml  # 설정 UI 확장
├── security/
│   └── ir.model.access.csv  # 접근 권한
├── data/
│   └── ldap_group_category.xml  # AD 그룹용 카테고리
└── README.md
```

### 3.2 핵심 로직 흐름

```
[사용자 LDAP 로그인]
        ↓
[memberOf 속성 조회]
        ↓
[각 DN에서 CN 추출]
   예: "CN=Sales,OU=Groups,DC=openshift,DC=co,DC=kr" → "Sales"
        ↓
[Odoo res.groups 검색]
   - 존재: 해당 그룹 ID 반환
   - 미존재: 새 그룹 생성 (category: "AD Groups")
        ↓
[사용자 groups_id 업데이트]
   - 기존 AD 그룹 제거
   - 새로운 AD 그룹 할당
        ↓
[Odoo UI에서 권한 설정 가능]
```

### 3.3 핵심 코드 설계

#### models/res_company_ldap.py
```python
from odoo import fields, models

class ResCompanyLdap(models.Model):
    _inherit = 'res.company.ldap'

    # AD 그룹 동기화 설정
    sync_groups = fields.Boolean(
        string='Sync AD Groups',
        default=True,
        help='Enable automatic AD group synchronization'
    )
    group_filter = fields.Char(
        string='Group Filter',
        default='(objectClass=group)',
        help='LDAP filter for group search'
    )
    group_prefix = fields.Char(
        string='Group Prefix',
        help='Only sync groups starting with this prefix (e.g., "ODOO_")'
    )
    auto_create_groups = fields.Boolean(
        string='Auto Create Groups',
        default=True,
        help='Automatically create Odoo groups for AD groups'
    )
```

#### models/res_users.py
```python
from odoo import api, models
import ldap

class ResUsers(models.Model):
    _inherit = 'res.users'

    def _sync_ad_groups(self, ldap_config, login):
        """AD memberOf 속성에서 그룹을 동기화"""
        if not ldap_config.sync_groups:
            return

        # 1. memberOf 조회
        member_of_list = self._ldap_get_member_of(ldap_config, login)

        # 2. AD 그룹 카테고리 조회/생성
        ad_category = self.env.ref(
            'teps_odoo_ldap_connector.module_category_ad_groups',
            raise_if_not_found=False
        )

        # 3. 각 DN에서 CN 추출 및 그룹 처리
        group_ids = []
        for dn in member_of_list:
            cn = self._extract_cn_from_dn(dn)

            # 접두사 필터 적용
            if ldap_config.group_prefix:
                if not cn.startswith(ldap_config.group_prefix):
                    continue

            # Odoo 그룹 검색
            odoo_group = self.env['res.groups'].sudo().search([
                ('name', 'ilike', cn)
            ], limit=1)

            if odoo_group:
                group_ids.append(odoo_group.id)
            elif ldap_config.auto_create_groups:
                # 새 그룹 생성
                new_group = self.env['res.groups'].sudo().create({
                    'name': cn,
                    'category_id': ad_category.id if ad_category else False,
                    'comment': f'Auto-created from AD group: {dn}'
                })
                group_ids.append(new_group.id)

        # 4. 기존 AD 그룹 제거 후 새 그룹 할당
        if ad_category:
            current_ad_groups = self.groups_id.filtered(
                lambda g: g.category_id == ad_category
            )
            self.write({
                'groups_id': [(3, g.id) for g in current_ad_groups] +
                             [(4, gid) for gid in group_ids]
            })
        else:
            self.write({'groups_id': [(4, gid) for gid in group_ids]})

    def _ldap_get_member_of(self, ldap_config, login):
        """LDAP에서 사용자의 memberOf 속성 조회"""
        conn = self._get_ldap_connection(ldap_config)
        try:
            # 사용자 DN 검색
            base = ldap_config.ldap_base
            filter_str = ldap_config.ldap_filter % login
            result = conn.search_s(base, ldap.SCOPE_SUBTREE, filter_str, ['memberOf'])

            if result:
                _, attrs = result[0]
                return [m.decode('utf-8') for m in attrs.get('memberOf', [])]
            return []
        finally:
            conn.unbind()

    def _extract_cn_from_dn(self, dn):
        """DN에서 CN 값 추출
        예: 'CN=Sales,OU=Groups,DC=openshift,DC=co,DC=kr' → 'Sales'
        """
        for part in dn.split(','):
            if part.upper().startswith('CN='):
                return part[3:]
        return dn
```

---

## 4. 구현 단계

### Phase 1: 기반 구조 (1단계)
- [ ] 모듈 scaffolding (__manifest__.py, __init__.py)
- [ ] res.company.ldap 확장 (설정 필드 추가)
- [ ] 설정 UI 뷰 생성

### Phase 2: 핵심 기능 (2단계)
- [ ] memberOf 조회 로직 구현
- [ ] CN 추출 함수 구현
- [ ] res.groups 검색/생성 로직
- [ ] 사용자 그룹 업데이트 로직

### Phase 3: 인증 연동 (3단계)
- [ ] auth_ldap의 _authenticate 메서드 확장
- [ ] 로그인 시 자동 그룹 동기화 트리거
- [ ] 에러 처리 및 로깅

### Phase 4: 관리 기능 (4단계)
- [ ] 수동 동기화 버튼 추가
- [ ] 그룹 동기화 로그 테이블
- [ ] 일괄 동기화 기능

### Phase 5: 테스트 및 배포 (5단계)
- [ ] 단위 테스트 작성
- [ ] 통합 테스트 (실제 AD 연동)
- [ ] 문서화
- [ ] Docker 이미지 빌드

---

## 5. 주요 고려사항

### 5.1 그룹 이름 충돌 방지
- AD 그룹과 기존 Odoo 그룹 이름이 같을 경우 기존 그룹에 연결
- 별도 카테고리("AD Groups")로 분류하여 관리

### 5.2 그룹 삭제 정책
- AD에서 제거된 그룹: Odoo에서 사용자만 제거, 그룹은 유지
- 수동 삭제 옵션 제공

### 5.3 성능 최적화
- 대량 사용자 동기화 시 배치 처리
- LDAP 연결 풀링 고려

### 5.4 보안
- LDAP 바인드 자격 증명 암호화 저장
- 동기화 작업 감사 로그

---

## 6. UI 설계 (와이어프레임)

> **참고 이미지**: `layout/` 폴더에 Liferay LDAP 설정 UI 참조 이미지 포함
> - `01_status.png` - 연결 상태 화면
> - `02_server.png` - 서버 설정 화면
> - `03_authentication.png` - 인증 설정 화면
> - `04_users_groups.png` - 사용자 및 그룹 매핑 화면
> - `05_import_export.png` - 가져오기/내보내기 설정 화면

### 6.1 전체 레이아웃 구조

좌측 사이드바 네비게이션 + 우측 콘텐츠 영역 구조

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION                                                                    │
├──────────────────────┬──────────────────────────────────────────────────────────────┤
│                      │                                                              │
│  Status              │   [콘텐츠 영역]                                              │
│  ──────────────────  │                                                              │
│  Server              │                                                              │
│                      │                                                              │
│  Authentication      │                                                              │
│                      │                                                              │
│  Users & Groups      │                                                              │
│                      │                                                              │
│  Import & Export     │                                                              │
│                      │                                                              │
│  System              │                                                              │
│                      │                                                              │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.2 Status (연결 상태)

LDAP 서버 연결 상태 및 요약 정보 표시

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  Status                                                      │
├──────────────────────┤                                                              │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│  ▌Status             │  │  ✓ Connection Successful                               │  │
│                      │  │  LDAP server is reachable and authentication was       │  │
│  Server              │  │  successful. The system is ready for LDAP operations.  │  │
│                      │  │  Response Time: 36ms                                   │  │
│  Authentication      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│  Users & Groups      │  CONNECTION SUMMARY                                          │
│                      │  ─────────────────────────────────────────────────────────   │
│  Import & Export     │                                                              │
│                      │  Server Name        AD-OPENSHIFT [Zentyal-8]                 │
│  System              │                                                              │
│                      │  Base Provider URL  ldap://ldap.openshift.co.kr:389          │
│                      │                                                              │
│                      │  Base DN            CN=Users,DC=openshift,DC=co,DC=kr        │
│                      │                                                              │
│                      │  Principal          Admin.sys@openshift.co.kr                │
│                      │                                                              │
│                      │  Credentials        Configured ✓                             │
│                      │                                                              │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │  ℹ This configuration is read-only and is loaded from │  │
│                      │  │  Odoo Instance Settings. Go to Settings > LDAP        │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.3 Server (서버 설정)

LDAP 서버 연결 정보 설정

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  Server                                                      │
├──────────────────────┤                                                              │
│                      │  Server Name *                                               │
│  Status              │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ AD-OPENSHIFT [Zentyal-8]                               │  │
│  ▌Server             │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│  Authentication      │  CONNECTION                                                  │
│                      │  ─────────────────────────────────────────────────────────   │
│  Users & Groups      │                                                              │
│                      │  Server Vendor (Default Values)                              │
│  Import & Export     │  ┌──────────────────────────────────────────────────┐ ┌────┐ │
│                      │  │ Load Default Server Configuration For...     ▼  │ │Apply│ │
│  System              │  └──────────────────────────────────────────────────┘ └────┘ │
│                      │  Select a server vendor to load default search filters      │
│                      │                                                              │
│                      │  Base Provider URL * ⓘ                                       │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ ldap://ldap.openshift.co.kr:389                        │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Base DN * ⓘ                                                 │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ CN=Users,DC=openshift,DC=co,DC=kr                      │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Security Principal * ⓘ                                      │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ Admin.sys@openshift.co.kr                              │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Security Credential * ⓘ                                     │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ ••••••••••••••••                                       │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  ┌─────────────────┐                                         │
│                      │  │ Test Connection │                                         │
│                      │  └─────────────────┘                                         │
│                      │                                                              │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                        ┌──────┐ ┌────────┐   │
│                      │                                        │ Save │ │ Cancel │   │
│                      │                                        └──────┘ └────────┘   │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.4 Authentication (인증 설정)

LDAP 인증 방식 및 비밀번호 정책 설정

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  Authentication                                              │
├──────────────────────┤                                                              │
│                      │  ☑ Enable LDAP Authentication ⓘ                              │
│  Status              │                                                              │
│                      │  ☐ Required ⓘ                                                │
│  Server              │                                                              │
│                      │  ☑ Use LDAP Password Policy ⓘ                                │
│  ▌Authentication     │                                                              │
│                      │  PASSWORD SETTINGS                                           │
│  Users & Groups      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│  Import & Export     │  Method ⓘ                                                    │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│  System              │  │ Bind                                               ▼  │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Password Encryption Algorithm ⓘ                             │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ None                                               ▼  │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                        ┌──────┐ ┌────────┐   │
│                      │                                        │ Save │ │ Cancel │   │
│                      │                                        └──────┘ └────────┘   │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.5 Users & Groups (사용자 및 그룹 매핑)

LDAP 속성과 Odoo 필드 간 매핑 설정 (핵심 화면)

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  Users & Groups                                              │
├──────────────────────┤                                                              │
│                      │  USERS                                                       │
│  Status              │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│  Server              │  SEARCH                                                      │
│                      │                                                              │
│  Authentication      │  Authentication Search Filter ⓘ                              │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│  ▌Users & Groups     │  │ (&(objectClass=person)(userPrincipalName=@email@))    │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│  Import & Export     │                                                              │
│                      │  User Search Filter ⓘ                                        │
│  System              │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ (&(objectClass=person)(!(isCriticalSystemObject=TRUE)) │  │
│                      │  │ (!(userPrincipalName=*sys@*)))                         │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  USER MAPPING                                                │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│                      │  Screen Name          Last Name                              │
│                      │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ sAMAccountName   │  │ sn               │                  │
│                      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│                      │  Email Address        Full Name                              │
│                      │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ userprincipalname│  │ displayName      │                  │
│                      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│                      │  Password             Job Title                              │
│                      │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ unicodePwd       │  │ title            │                  │
│                      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│                      │  First Name           Status                                 │
│                      │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ givenName        │  │                  │                  │
│                      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│                      │  Middle Name          Group  ← AD 그룹 매핑 (핵심)           │
│                      │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ middleName       │  │ memberOf         │  ← memberOf 속성 │
│                      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                        ┌──────┐ ┌────────┐   │
│                      │                                        │ Save │ │ Cancel │   │
│                      │                                        └──────┘ └────────┘   │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.6 Import & Export (가져오기/내보내기 설정)

그룹 동기화 및 자동 가져오기 설정 (핵심 화면)

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  Import & Export                                             │
├──────────────────────┤                                                              │
│                      │  IMPORT                                                      │
│  Status              │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│  Server              │  ☑ Enable Import ⓘ                                           │
│                      │                                                              │
│  Authentication      │  ☐ Import on Startup ⓘ                                       │
│                      │                                                              │
│  Users & Groups      │  IMPORT SETTINGS                                             │
│                      │  ─────────────────────────────────────────────────────────   │
│  ▌Import & Export    │                                                              │
│                      │  Import Interval (minutes) ⓘ                                 │
│  System              │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ 5                                                      │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Import Method ⓘ                                             │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ User                                               ▼  │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  Lock Expiration Time (ms) ⓘ                                 │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ 86400000                                               │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  User Sync Strategy ⓘ                                        │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ Auth Type                                          ▼  │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  PASSWORD SETTINGS                                           │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│                      │  ☐ Enable User Password Import ⓘ                             │
│                      │                                                              │
│                      │  ☐ Auto-generate Passwords ⓘ                                 │
│                      │                                                              │
│                      │  Default Password ⓘ                                          │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ ••••                                                   │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  GROUP SETTINGS  ← AD 그룹 동기화 설정 (핵심)                │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│                      │  ☑ Enable Group Cache ⓘ                                      │
│                      │                                                              │
│                      │  ☑ Create Role Per Group ⓘ  ← AD 그룹별 Odoo 그룹 자동 생성  │
│                      │                                                              │
│                      │  Group Prefix Filter ⓘ  ← 특정 접두사 그룹만 동기화          │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ ODOO_                                                  │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                        ┌──────┐ ┌────────┐   │
│                      │                                        │ Save │ │ Cancel │   │
│                      │                                        └──────┘ └────────┘   │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.7 System (시스템 설정)

동기화 로그 및 시스템 관리 기능

```
┌──────────────────────┬──────────────────────────────────────────────────────────────┐
│  LDAP CONNECTION     │  System                                                      │
├──────────────────────┤                                                              │
│                      │  SYNC ACTIONS                                                │
│  Status              │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│  Server              │  ┌──────────────────┐  ┌──────────────────┐                  │
│                      │  │ 🔄 Sync Now      │  │ 📋 View Logs     │                  │
│  Authentication      │  └──────────────────┘  └──────────────────┘                  │
│                      │                                                              │
│  Users & Groups      │  SYNC STATISTICS                                             │
│                      │  ─────────────────────────────────────────────────────────   │
│  Import & Export     │                                                              │
│                      │  Last Sync             2026-01-08 14:30:22                   │
│  ▌System             │  Total Users Synced    156                                   │
│                      │  Total Groups Synced   12                                    │
│                      │  Failed Syncs (24h)    0                                     │
│                      │                                                              │
│                      │  SYNC LOG (Recent)                                           │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│                      │  ┌────────────────────────────────────────────────────────┐  │
│                      │  │ Time          │ User       │ Action   │ Groups │Status │  │
│                      │  ├────────────────────────────────────────────────────────┤  │
│                      │  │ 14:30:22      │ john.doe   │ Login    │ 3      │ ✓     │  │
│                      │  │ 14:25:15      │ jane.smith │ Login    │ 2      │ ✓     │  │
│                      │  │ 14:20:00      │ admin      │ Manual   │ All    │ ✓     │  │
│                      │  │ 13:15:42      │ bob.kim    │ Login    │ 1 new  │ ✓     │  │
│                      │  │ 12:00:00      │ system     │ LDAP Err │ -      │ ✗     │  │
│                      │  └────────────────────────────────────────────────────────┘  │
│                      │                                                              │
│                      │  ADVANCED                                                    │
│                      │  ─────────────────────────────────────────────────────────   │
│                      │                                                              │
│                      │  ☐ Debug Mode ⓘ                                              │
│                      │                                                              │
│                      │  ☐ Force Full Sync on Next Run ⓘ                             │
│                      │                                                              │
│                      │  ┌────────────────────┐                                      │
│                      │  │ 🗑️ Clear Sync Cache │                                      │
│                      │  └────────────────────┘                                      │
│                      │                                                              │
└──────────────────────┴──────────────────────────────────────────────────────────────┘
```

---

### 6.8 Odoo 그룹 권한 설정 화면

AD에서 동기화된 그룹의 권한 설정 (기존 Odoo 그룹 폼 활용)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  그룹 / Sales                                                      [저장] [삭제]   │
├─────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                     │
│  이름 *           [Sales________________________________]                           │
│                                                                                     │
│  카테고리         [AD Groups                         ▼]                             │
│                                                                                     │
│  ┌─ AD 정보 (읽기 전용) ─────────────────────────────────────────────────────────┐  │
│  │ Source DN: CN=Sales,OU=Groups,DC=openshift,DC=co,DC=kr                       │  │
│  │ Last Sync: 2026-01-08 14:30:22                                               │  │
│  └──────────────────────────────────────────────────────────────────────────────┘  │
│                                                                                     │
│  ┌───────────────┬─────────────────┬─────────────────┐                              │
│  │ Users (15)    │ Access Rights   │ Record Rules    │                              │
│  └───────────────┴─────────────────┴─────────────────┘                              │
│                                                                                     │
│  Access Rights                                                    [+ Add Line]      │
│  ───────────────────────────────────────────────────────────────────────────────    │
│  │ Name                  │ Model          │ Read │ Write │ Create │ Delete │        │
│  ├───────────────────────────────────────────────────────────────────────────       │
│  │ Sales Order Access    │ sale.order     │  ✓   │  ✓    │  ✓     │  ☐     │        │
│  │ Partner Read          │ res.partner    │  ✓   │  ☐    │  ☐     │  ☐     │        │
│  │ Product Read          │ product.product│  ✓   │  ☐    │  ☐     │  ☐     │        │
│                                                                                     │
│  Record Rules                                                     [+ Add Line]      │
│  ───────────────────────────────────────────────────────────────────────────────    │
│  │ Name                  │ Model          │ Domain Filter                     │     │
│  ├───────────────────────────────────────────────────────────────────────────       │
│  │ Own Company Only      │ sale.order     │ [('company_id', 'in', company_ids)]│     │
│  │ Own Team Partners     │ res.partner    │ [('user_id', '=', user.id)]       │     │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 6.9 UI 네비게이션 흐름도

```
                              ┌─────────────────────┐
                              │    관리자 로그인     │
                              └──────────┬──────────┘
                                         │
                                         ▼
                    ┌────────────────────────────────────────┐
                    │  설정 > LDAP CONNECTION                │
                    └────────────────────┬───────────────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         │                               │                               │
         ▼                               ▼                               ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ 1. Status       │           │ 2. Server       │           │ 3. Authentication│
│ (연결 확인)     │           │ (서버 설정)     │           │ (인증 방식)      │
└────────┬────────┘           └────────┬────────┘           └────────┬────────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
         ┌─────────────────────────────┼─────────────────────────────┐
         │                             │                             │
         ▼                             ▼                             ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│ 4. Users&Groups │           │ 5. Import&Export│           │ 6. System       │
│ (속성 매핑)     │           │ (그룹 동기화)   │           │ (로그/관리)     │
│ ┌─────────────┐ │           │ ┌─────────────┐ │           │ ┌─────────────┐ │
│ │ memberOf    │ │           │ │ Enable Group│ │           │ │ Sync Now    │ │
│ │ → Group     │ │           │ │ Cache       │ │           │ │ View Logs   │ │
│ └─────────────┘ │           │ │ Create Role │ │           │ └─────────────┘ │
└────────┬────────┘           │ │ Per Group ✓ │ │           └────────┬────────┘
         │                    │ └─────────────┘ │                    │
         │                    └────────┬────────┘                    │
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
                                       ▼
                         ┌─────────────────────────┐
                         │  사용자 LDAP 로그인 시   │
                         │  AD 그룹 자동 동기화     │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │  설정 > 그룹 관리       │
                         │  (AD Groups 카테고리)   │
                         └────────────┬────────────┘
                                      │
                                      ▼
                         ┌─────────────────────────┐
                         │  그룹 상세 화면 (6.8)   │
                         │  - 접근 권한 설정       │
                         │  - 레코드 규칙 설정     │
                         └─────────────────────────┘
```

---

## 7. 예상 결과

### 6.1 관리자 워크플로우

1. **LDAP 설정**에서 "Sync AD Groups" 활성화
2. 사용자가 LDAP 로그인 시 AD 그룹 자동 생성
3. **설정 > 사용자 & 회사 > 그룹**에서 AD 그룹 확인
4. 해당 그룹에 **접근 권한** 및 **레코드 규칙** 설정

### 6.2 사용자 경험

```
[사용자: john.doe LDAP 로그인]
       ↓
[AD 그룹: Sales, Marketing, Managers]
       ↓
[Odoo 그룹 자동 생성/연결]
   - Sales (AD Groups 카테고리)
   - Marketing (AD Groups 카테고리)
   - Managers (AD Groups 카테고리)
       ↓
[관리자가 Sales 그룹에 권한 부여]
   - sale.order 읽기/쓰기
   - 자기 회사 레코드만 접근
       ↓
[john.doe는 Sales 권한으로 Odoo 사용]
```

---

## 7. 의존성

```python
# __manifest__.py
{
    'name': 'TEPS LDAP Connector',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'depends': ['auth_ldap'],  # Odoo 기본 LDAP 모듈
    'external_dependencies': {
        'python': ['python-ldap'],
    },
}
```

---

## 8. Liferay LDAP 코드 패턴 참조

> **참조 소스**: `/Users/cmars/@Libs/liferay-portal/modules/apps/portal-security/portal-security-ldap-impl`

Liferay Portal의 LDAP 그룹 가져오기 로직을 분석하여 Odoo 구현에 참고합니다.

### 8.1 핵심 메서드 매핑

| Liferay 메서드 | 위치 (줄) | Odoo 대응 메서드 | 기능 |
|---------------|----------|----------------|------|
| `_importGroups()` | 1240-1356 | `_sync_ad_groups()` | 사용자의 LDAP 그룹 속성에서 그룹 목록 추출 |
| `_addRole()` | 868-921 | `_create_odoo_group()` | 그룹이 없을 시 자동 생성 |
| `_importUserGroup()` | 1570-1648 | `_update_user_groups()` | 사용자-그룹 관계 업데이트 |
| `_getGroupMappings()` | 1205-1238 | `_get_group_mappings()` | 그룹 매핑 설정 조회 |

### 8.2 Liferay 핵심 로직 분석

#### _importGroups() 패턴 (1240-1356줄)
```java
// Liferay 원본 (Java)
private long[] _importGroups(
    LDAPImportContext ldapImportContext, Attributes userAttributes, User user)
    throws Exception {

    // 1. 사용자 속성에서 그룹 정보 추출
    String userMappingsGroup = userMappings.get("group"); // "memberOf"
    Attribute userGroupAttribute = userAttributes.get(userMappingsGroup);

    // 2. 각 그룹 처리
    Set<Long> newUserGroupIds = new LinkedHashSet<>();
    for (int i = 0; i < userGroupAttribute.size(); i++) {
        String groupDN = (String) userGroupAttribute.get(i);
        long userGroupId = _importGroup(ldapImportContext, groupDN, user);
        if (userGroupId > 0) {
            newUserGroupIds.add(userGroupId);
        }
    }

    // 3. 사용자 그룹 관계 업데이트
    _updateUserGroups(newUserGroupIds, user.getUserId());
}
```

#### Python 변환 패턴
```python
# Odoo 구현 (Python)
def _sync_ad_groups(self, ldap_config, user_attributes, user):
    """Liferay _importGroups() 패턴 적용"""

    # 1. 사용자 속성에서 그룹 정보 추출
    user_mappings_group = 'memberOf'  # LDAP 속성명
    member_of_list = user_attributes.get(user_mappings_group, [])

    # 2. 각 그룹 처리
    new_group_ids = set()
    for group_dn in member_of_list:
        group_id = self._import_group(ldap_config, group_dn, user)
        if group_id:
            new_group_ids.add(group_id)

    # 3. 사용자 그룹 관계 업데이트
    self._update_user_groups(new_group_ids, user.id)
```

### 8.3 설정 매핑 테이블

| Liferay 설정 | Odoo 필드 | 설명 |
|-------------|----------|------|
| `importGroupCacheEnabled` | `group_cache_enabled` | 그룹 캐시 활성화 |
| `importCreateRolePerGroup` | `auto_create_groups` | AD 그룹별 자동 생성 |
| `userMappings.group` | `group_attribute` | memberOf 속성명 |
| `groupMappings.groupName` | - | CN 추출 (고정값) |

### 8.4 _addRole() 패턴 (868-921줄)

그룹 자동 생성 로직:

```java
// Liferay 원본
private Role _addRole(
    long companyId, String name, Map<Locale, String> titleMap) {

    // 1. 기존 그룹 검색
    Role role = _roleLocalService.fetchRole(companyId, name);

    // 2. 없으면 새로 생성
    if (role == null) {
        role = _roleLocalService.addRole(
            userId, null, 0, name, titleMap, descriptionMap,
            RoleConstants.TYPE_REGULAR, null, serviceContext);
    }

    return role;
}
```

```python
# Odoo 구현
def _add_odoo_group(self, group_name, category_id):
    """Liferay _addRole() 패턴 적용"""

    # 1. 기존 그룹 검색
    existing_group = self.env['res.groups'].sudo().search([
        ('name', 'ilike', group_name)
    ], limit=1)

    # 2. 없으면 새로 생성
    if not existing_group:
        existing_group = self.env['res.groups'].sudo().create({
            'name': group_name,
            'category_id': category_id,
            'comment': f'Auto-created from AD: {group_name}'
        })

    return existing_group.id
```

### 8.5 그룹 관계 업데이트 패턴

```python
def _update_user_groups(self, new_group_ids, user_id):
    """
    Liferay _updateUserGroups() 패턴 적용
    - 기존 AD 그룹 제거
    - 새 그룹 할당
    """
    user = self.browse(user_id)
    ad_category = self.env.ref('teps_odoo_ldap_connector.module_category_ad_groups')

    # AD 카테고리 그룹만 필터링하여 제거
    ad_groups_to_remove = user.groups_id.filtered(
        lambda g: g.category_id == ad_category
    )

    # Command API 사용
    commands = [(3, g.id) for g in ad_groups_to_remove]  # 제거
    commands += [(4, gid) for gid in new_group_ids]       # 추가

    user.write({'groups_id': commands})
```

### 8.6 참고할 Liferay 설정 구조

```java
// Liferay portal-security-ldap-impl 주요 설정 키
public class LDAPConstants {
    public static final String IMPORT_CREATE_ROLE_PER_GROUP = "importCreateRolePerGroup";
    public static final String IMPORT_GROUP_CACHE_ENABLED = "importGroupCacheEnabled";
    public static final String IMPORT_USER_SYNC_STRATEGY = "importUserSyncStrategy";
    public static final String USER_MAPPINGS_GROUP = "userMappings.group";
}
```

---

## 9. 관련 문서

- [Odoo 권한 관리 체계](../../@Docs/docs/odoo-permission-management.md)
- [LDAP 그룹 동기화 분석](../../@Docs/docs/ldap-group-sync-analysis.md)
- [LDAP 문제 해결](../../@Docs/docs/ldap-troubleshooting.md)
- [Liferay LDAP 모듈 소스](https://github.com/liferay/liferay-portal/tree/master/modules/apps/portal-security/portal-security-ldap-impl)

---

*작성자: Claude Code*
*최종 수정: 2026-01-08*
