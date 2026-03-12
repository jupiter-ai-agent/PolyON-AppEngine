{
    "name": "PolyON LDAP Configuration",
    "version": "19.0.1.0.0",
    "category": "Authentication",
    "summary": "PRC directory 환경변수로 Samba AD LDAP 설정 자동화",
    "author": "Triangle.s",
    "depends": ["base", "auth_ldap", "teps_odoo_ldap_connector"],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}