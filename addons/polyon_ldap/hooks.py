import logging
import os

from odoo import api, SUPERUSER_ID

logger = logging.getLogger(__name__)

def post_init_hook(env):
    """PRC directory 환경변수에서 LDAP 설정을 읽어 res.company.ldap 레코드를 생성한다.
    teps_odoo_ldap_connector 필드 포함 (AD 사용자/그룹 자동 동기화).
    """
    ldap_host = os.getenv("LDAP_HOST", "")
    ldap_port = int(os.getenv("LDAP_PORT", "389"))
    ldap_base_dn = os.getenv("LDAP_BASE_DN", "")
    ldap_bind_dn = os.getenv("LDAP_BIND_DN", "")
    ldap_bind_password = os.getenv("LDAP_BIND_PASSWORD", "")
    ldap_users_dn = os.getenv("LDAP_USERS_DN", ldap_base_dn)
    ldap_groups_dn = os.getenv("LDAP_GROUPS_DN", ldap_base_dn)

    if not ldap_host or not ldap_base_dn:
        logger.warning("LDAP 환경변수 미설정 — LDAP 자동 설정 건너뜀")
        return

    ldap_model = env["res.company.ldap"].sudo()
    company = env["res.company"].sudo().search([], limit=1)

    if not company:
        logger.error("회사 레코드 없음 — LDAP 설정 불가")
        return

    existing = ldap_model.search([("ldap_server", "=", ldap_host)], limit=1)

    ldap_values = {
        "company": company.id,
        "ldap_server": ldap_host,
        "ldap_server_port": ldap_port,
        "ldap_base": ldap_base_dn,
        "ldap_binddn": ldap_bind_dn,
        "ldap_password": ldap_bind_password,
        # 인증용 필터 (OIDC 사용 시 실질적으로 미사용이지만 설정 필수)
        "ldap_filter": "(&(objectClass=user)(sAMAccountName=%s))",
        # 사용자 자동 생성 — LDAP/OIDC 로그인 시 res.users에 자동 프로비저닝
        "create_user": True,
    }

    # teps_odoo_ldap_connector 필드 (모듈 설치된 경우에만 적용)
    teps_fields = {}
    if "users_dn" in ldap_model._fields:
        teps_fields.update({
            "users_dn": ldap_users_dn,
            "auth_search_filter": "(&(objectClass=user)(sAMAccountName=%(user)s))",
            "user_search_filter": (
                "(&(objectClass=user)"
                "(!(isCriticalSystemObject=TRUE))"
                "(!(sAMAccountName=krbtgt))"
                "(!(sAMAccountName=guest))"
                ")"
            ),
            # 사용자 속성 매핑
            "ldap_attr_login": "sAMAccountName",
            "ldap_attr_email": "userPrincipalName",
            "ldap_attr_fullname": "displayName",
            "ldap_attr_firstname": "givenName",
            "ldap_attr_lastname": "sn",
            "ldap_attr_jobtitle": "title",
            # 그룹 동기화
            "groups_dn": ldap_groups_dn,
            "sync_groups": True,
        })

    ldap_values.update(teps_fields)

    if existing:
        existing.write(ldap_values)
        logger.info("기존 LDAP 설정 업데이트: %s (teps_fields=%s)", ldap_host, bool(teps_fields))
    else:
        ldap_model.create(ldap_values)
        logger.info("LDAP 설정 자동 생성: %s (teps_fields=%s)", ldap_host, bool(teps_fields))
