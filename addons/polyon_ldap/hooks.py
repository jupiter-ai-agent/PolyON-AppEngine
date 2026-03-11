import logging
import os

from odoo import api, SUPERUSER_ID

logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    """PRC directory 환경변수에서 LDAP 설정을 읽어 res.company.ldap 레코드를 생성한다."""
    ldap_host = os.getenv("LDAP_HOST", "")
    ldap_port = os.getenv("LDAP_PORT", "389")
    ldap_base_dn = os.getenv("LDAP_BASE_DN", "")
    ldap_bind_dn = os.getenv("LDAP_BIND_DN", "")
    ldap_bind_password = os.getenv("LDAP_BIND_PASSWORD", "")

    if not ldap_host or not ldap_base_dn:
        logger.warning("LDAP 환경변수 미설정 — LDAP 자동 설정 건너뜀")
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    ldap_model = env["res.company.ldap"].sudo()
    company = env["res.company"].sudo().search([], limit=1)

    if not company:
        logger.error("회사 레코드 없음 — LDAP 설정 불가")
        return

    existing = ldap_model.search([("ldap_server", "=", ldap_host)], limit=1)

    ldap_values = {
        "company": company.id,
        "ldap_server": ldap_host,
        "ldap_server_port": int(ldap_port),
        "ldap_base": ldap_base_dn,
        "ldap_binddn": ldap_bind_dn,
        "ldap_password": ldap_bind_password,
        "ldap_filter": "(&(objectClass=user)(sAMAccountName=%s))",
        "create_user": False,  # SSO로만 생성, LDAP 자동 생성 금지
    }

    if existing:
        existing.write(ldap_values)
        logger.info("기존 LDAP 설정 업데이트: %s", ldap_host)
    else:
        ldap_model.create(ldap_values)
        logger.info("LDAP 설정 자동 생성: %s", ldap_host)