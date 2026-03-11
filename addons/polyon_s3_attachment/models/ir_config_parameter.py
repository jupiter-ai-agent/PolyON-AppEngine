import os

from odoo import api, models


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model
    def set_default_s3_attachment_configuration_from_environment(self):
        # PRC 환경변수에서 S3 설정 값을 읽어 기본 설정으로 저장한다
        configuration = self.sudo()

        s3_host_from_environment = os.getenv("AWS_HOST") or os.getenv("S3_ENDPOINT", "")
        s3_bucket_from_environment = os.getenv("AWS_BUCKET_NAME") or os.getenv("S3_BUCKET", "")
        s3_access_key_from_environment = os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("S3_ACCESS_KEY", "")
        s3_secret_key_from_environment = os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("S3_SECRET_KEY", "")

        values_to_store = {
            "polyon_s3_attachment.aws_host": s3_host_from_environment,
            "polyon_s3_attachment.aws_bucket_name": s3_bucket_from_environment,
            "polyon_s3_attachment.aws_access_key_id": s3_access_key_from_environment,
            "polyon_s3_attachment.aws_secret_access_key": s3_secret_key_from_environment,
        }

        for parameter_key, parameter_value in values_to_store.items():
            if not parameter_value:
                continue
            configuration.set_param(parameter_key, parameter_value)

