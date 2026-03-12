import logging

from odoo import api, SUPERUSER_ID

logger = logging.getLogger(__name__)


def post_init_hook(env):
    # 설치 시 PRC 환경변수에서 S3 설정을 읽어 ir.config_parameter에 저장한다
    env["ir.config_parameter"].set_default_s3_attachment_configuration_from_environment()
    logger.info("PolyON S3 Attachment 기본 설정을 PRC 환경변수에서 초기화했습니다.")
