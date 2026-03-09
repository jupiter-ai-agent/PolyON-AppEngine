import logging
import os

from odoo import api, SUPERUSER_ID

logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    # 설치 시 PRC 환경변수를 ir.config_parameter에 저장하고 LDAP 설정을 생성한다
    environment = api.Environment(cr, SUPERUSER_ID, {})
    configuration = environment["ir.config_parameter"].sudo()

    ldap_server_from_environment = os.getenv("LDAP_SERVER", "")
    ldap_port_from_environment = os.getenv("LDAP_PORT", "")
    ldap_bind_distinguished_name_from_environment = os.getenv("LDAP_BIND_DN", "")
    ldap_bind_password_from_environment = os.getenv("LDAP_BIND_PASSWORD", "")
    ldap_base_distinguished_name_from_environment = os.getenv("LDAP_BASE_DN", "")

    values_to_store = {
        "polyon_ldap_auto.ldap_server": ldap_server_from_environment,
        "polyon_ldap_auto.ldap_server_port": ldap_port_from_environment,
        "polyon_ldap_auto.ldap_binddn": ldap_bind_distinguished_name_from_environment,
        "polyon_ldap_auto.ldap_password": ldap_bind_password_from_environment,
        "polyon_ldap_auto.ldap_base": ldap_base_distinguished_name_from_environment,
    }

    for parameter_key, parameter_value in values_to_store.items():
        if not parameter_value:
            continue
        configuration.set_param(parameter_key, parameter_value)

    if not ldap_server_from_environment or not ldap_base_distinguished_name_from_environment:
        logger.info(
            "LDAP 환경변수가 충분하지 않아 기본 LDAP 설정을 생성하지 않았습니다."
        )
        return

    environment["res.company"].create_default_ldap_configuration_from_environment()

