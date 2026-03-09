{
    "name": "PolyON LDAP Auto Configuration",
    "summary": "PRC 환경변수를 기반으로 Odoo LDAP 공급자를 자동 설정하는 모듈",
    "version": "0.1.0",
    "author": "Triangle.s",
    "website": "https://github.com/jupiter-ai-agent/PolyON-Odoo",
    "license": "LGPL-3",
    "category": "Authentication",
    "depends": ["base", "auth_ldap"],
    "data": [],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
}

