from odoo import api, SUPERUSER_ID


def post_init_hook(cr, registry):
    # 설치 시 PRC 환경변수에서 Redis 세션 설정을 읽어 ir.config_parameter에 저장한다
    environment = api.Environment(cr, SUPERUSER_ID, {})
    environment["ir.config_parameter"].set_default_redis_session_configuration_from_environment()

