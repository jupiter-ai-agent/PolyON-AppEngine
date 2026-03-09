import json
import logging
import os

import jwt
import requests
from jwt.algorithms import RSAAlgorithm

from odoo import http
from odoo.http import request


logger = logging.getLogger(__name__)

jwks_cache = {}


def get_jwks(jwks_url):
    """Keycloak JWKS 엔드포인트에서 공개키를 가져온다."""
    if jwks_url in jwks_cache:
        return jwks_cache[jwks_url]
    response = requests.get(jwks_url, timeout=10)
    response.raise_for_status()
    keys = response.json().get("keys", [])
    jwks_cache[jwks_url] = keys
    return keys


def verify_jwt(token):
    """JWT를 Keycloak 공개키로 검증하고 payload를 반환한다."""
    issuer_url = os.getenv("OIDC_ISSUER", "")
    client_identifier = os.getenv("OIDC_CLIENT_ID", "")
    jwks_url = os.getenv("OIDC_JWKS_URI", "")

    if not all([issuer_url, client_identifier, jwks_url]):
        raise ValueError("OIDC 환경변수 미설정")

    unverified_header = jwt.get_unverified_header(token)
    key_identifier = unverified_header.get("kid")

    keys = get_jwks(jwks_url)
    key_data = next((key for key in keys if key.get("kid") == key_identifier), None)
    if not key_data:
        raise ValueError(f"JWKS에서 kid={key_identifier} 키를 찾을 수 없음")

    public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))

    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=issuer_url,
        audience=client_identifier,
    )
    return payload


class OIDCController(http.Controller):
    @http.route("/polyon/oidc/login", type="http", auth="none", csrf=False)
    def oidc_login(self, token=None, redirect="/web", **kwargs):
        """JWT 토큰을 검증하고 Odoo 세션을 생성한다."""
        if not token:
            return request.redirect("/web/login")

        try:
            payload = verify_jwt(token)
        except Exception as exception:
            logger.warning("OIDC JWT 검증 실패: %s", exception)
            return request.redirect("/web/login")

        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            logger.warning("JWT에 preferred_username 없음")
            return request.redirect("/web/login")

        user_model = request.env["res.users"].sudo()
        user = user_model.search([("login", "=", username)], limit=1)

        if not user:
            user = user_model.create(
                {
                    "login": username,
                    "name": name,
                    "email": email,
                    "groups_id": [
                        (
                            6,
                            0,
                            [request.env.ref("base.group_user").id],
                        )
                    ],
                }
            )
            logger.info("OIDC 사용자 자동 생성: %s", username)

        request.session.authenticate(
            request.db,
            username,
            {"type": "token"},
        )

        return request.redirect(redirect)

