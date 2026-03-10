import logging
import os

from odoo import SUPERUSER_ID, api

logger = logging.getLogger(__name__)


def post_init_hook(cr, registry):
    # OIDC 환경변수가 없으면 Provider를 생성하지 않는다
    issuer = os.getenv("OIDC_ISSUER", "")
    client_id = os.getenv("OIDC_CLIENT_ID", "")
    auth_endpoint = os.getenv("OIDC_AUTH_ENDPOINT", "")
    token_endpoint = os.getenv("OIDC_TOKEN_ENDPOINT", "")

    if not all([issuer, client_id, auth_endpoint, token_endpoint]):
        logger.error("OIDC 환경변수가 부족하여 auth_oauth Provider를 생성하지 못했습니다.")
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    provider_model = env["auth.oauth.provider"].sudo()

    existing_provider = provider_model.search(
        [("client_id", "=", client_id), ("auth_endpoint", "=", auth_endpoint)], limit=1
    )

    provider_values = {
        "name": "Keycloak (PolyON)",
        "enabled": True,
        "client_id": client_id,
        "auth_endpoint": auth_endpoint,
        "validation_endpoint": token_endpoint,
        "scope": "openid profile email",
    }

    if existing_provider:
        existing_provider.write(provider_values)
        logger.info("기존 Keycloak OIDC Provider 구성을 업데이트했습니다.")
    else:
        provider_model.create(provider_values)
        logger.info("새로운 Keycloak OIDC Provider 구성을 생성했습니다.")

