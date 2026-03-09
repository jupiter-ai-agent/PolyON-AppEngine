import os
from urllib.parse import urlparse

from odoo import api, models


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model
    def set_default_redis_session_configuration_from_environment(self):
        # PRC 환경변수에서 Redis URL을 읽어 기본 세션 설정을 저장한다
        configuration = self.sudo()

        redis_url_from_environment = os.getenv("REDIS_URL", "")
        if not redis_url_from_environment:
            return

        parsed_redis_url = urlparse(redis_url_from_environment)
        redis_host = parsed_redis_url.hostname or ""
        redis_port = parsed_redis_url.port or 6379
        redis_database_index = parsed_redis_url.path.lstrip("/") or "0"

        values_to_store = {
            "polyon_redis_session.redis_host": redis_host,
            "polyon_redis_session.redis_port": str(redis_port),
            "polyon_redis_session.redis_dbindex": redis_database_index,
        }

        for parameter_key, parameter_value in values_to_store.items():
            if not parameter_value:
                continue
            configuration.set_param(parameter_key, parameter_value)

