# -*- coding: utf-8 -*-
{
    'name': 'PolyON LDAP Connector',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'summary': 'AD Group Synchronization for Odoo',
    'description': """
PolyON LDAP Connector
=====================

Active Directory 그룹을 Odoo 그룹으로 자동 동기화하는 모듈입니다.

주요 기능:
----------
* LDAP 로그인 시 memberOf 속성에서 AD 그룹 자동 동기화
* AD 그룹 → Odoo 그룹 자동 생성
* 매핑 테이블 없이 직접 동기화
* Odoo UI에서 그룹별 권한 설정 가능
* 그룹 접두사 필터링 지원

설정 방법:
----------
1. 설정 > 일반 설정 > LDAP 서버에서 'Sync AD Groups' 활성화
2. 사용자가 LDAP 로그인 시 AD 그룹 자동 동기화
3. 설정 > 사용자 & 회사 > 그룹에서 동기화된 그룹 확인

참고:
-----
* OCA users_ldap_groups 모듈의 Odoo 19.0 대체 모듈
* Liferay Portal LDAP 모듈 패턴 참조
    """,
    'author': 'PolyON',
    'website': 'https://www.polyon.co.kr',
    'license': 'LGPL-3',
    'depends': [
        'auth_ldap',
    ],
    'external_dependencies': {
        'python': ['ldap'],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/ldap_group_category.xml',
        'data/ldap_cron.xml',
        'wizard/ldap_test_users_wizard_views.xml',
        'wizard/ldap_test_groups_wizard_views.xml',
        'wizard/ldap_sync_wizard_views.xml',
        'views/res_company_ldap_views.xml',
        'views/res_groups_views.xml',
        'views/res_users_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'polyon_ldap_connector/static/src/css/ldap_form.css',
        ],
    },
    'post_init_hook': '_post_init_update_cron',
    'installable': True,
    'application': True,
    'auto_install': False,
}
