import boto3

from odoo import models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _get_s3_client_and_bucket(self):
        # S3 설정값을 ir.config_parameter에서 읽어온다
        parameter_model = self.env["ir.config_parameter"].sudo()
        endpoint_url = parameter_model.get_param(
            "polyon_s3_attachment.aws_host", default=""
        )
        access_key = parameter_model.get_param(
            "polyon_s3_attachment.aws_access_key_id", default=""
        )
        secret_key = parameter_model.get_param(
            "polyon_s3_attachment.aws_secret_access_key", default=""
        )

        if not endpoint_url or not access_key or not secret_key:
            return None, None

        bucket_name = parameter_model.get_param(
            "polyon_s3_attachment.aws_bucket_name", default="odoo"
        )

        s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="us-east-1",
        )
        return s3_client, bucket_name

    def _file_write(self, binary_value, checksum):
        # S3 설정이 없으면 기존 로컬 filestore 로직을 그대로 사용한다
        s3_client, bucket_name = self._get_s3_client_and_bucket()
        if s3_client is None:
            return super()._file_write(binary_value, checksum)

        file_name = f"{checksum[:2]}/{checksum}"
        s3_client.put_object(Bucket=bucket_name, Key=file_name, Body=binary_value)
        return file_name

    def _file_read(self, file_name):
        # S3 설정이 없으면 기존 로직을 사용한다
        s3_client, bucket_name = self._get_s3_client_and_bucket()
        if s3_client is None:
            return super()._file_read(file_name)

        try:
            response = s3_client.get_object(Bucket=bucket_name, Key=file_name)
            return response["Body"].read()
        except Exception:
            return super()._file_read(file_name)

    def _file_delete(self, file_name):
        # S3 설정이 없으면 기존 로직을 사용한다
        s3_client, bucket_name = self._get_s3_client_and_bucket()
        if s3_client is None:
            return super()._file_delete(file_name)

        try:
            s3_client.delete_object(Bucket=bucket_name, Key=file_name)
        except Exception:
            # 삭제 실패 시에도 전체 트랜잭션을 막지 않는다
            pass

