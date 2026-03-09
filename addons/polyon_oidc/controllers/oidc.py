import json
import logging
import os

import jwt
import requests
from jwt.algorithms import RSAAlgorithm

from odoo import http
from odoo.http import request


로그_기록기 = logging.getLogger(__name__)

_jwks_캐시 = {}


def _jwks_가져오기(jwks_주소):
    """Keycloak JWKS 엔드포인트에서 공개키를 가져온다."""
    if jwks_주소 in _jwks_캐시:
        return _jwks_캐시[jwks_주소]
    응답 = requests.get(jwks_주소, timeout=10)
    응답.raise_for_status()
    키_목록 = 응답.json().get("keys", [])
    _jwks_캐시[jwks_주소] = 키_목록
    return 키_목록


def _jwt_검증(토큰_문자열):
    """JWT를 Keycloak 공개키로 검증하고 payload를 반환한다."""
    발급자_주소 = os.getenv("OIDC_ISSUER", "")
    클라이언트_아이디 = os.getenv("OIDC_CLIENT_ID", "")
    jwks_주소 = os.getenv("OIDC_JWKS_URI", "")

    if not all([발급자_주소, 클라이언트_아이디, jwks_주소]):
        raise ValueError("OIDC 환경변수 미설정")

    확인_되지_않은_헤더 = jwt.get_unverified_header(토큰_문자열)
    키_아이디 = 확인_되지_않은_헤더.get("kid")

    키_목록 = _jwks_가져오기(jwks_주소)
    키_데이터 = next((키 for 키 in 키_목록 if 키.get("kid") == 키_아이디), None)
    if not 키_데이터:
        raise ValueError(f"JWKS에서 kid={키_아이디} 키를 찾을 수 없음")

    공개키 = RSAAlgorithm.from_jwk(json.dumps(키_데이터))

    payload = jwt.decode(
        토큰_문자열,
        공개키,
        algorithms=["RS256"],
        issuer=발급자_주소,
        audience=클라이언트_아이디,
    )
    return payload


class OIDC컨트롤러(http.Controller):
    @http.route("/polyon/oidc/login", type="http", auth="none", csrf=False)
    def oidc_로그인(self, token=None, redirect="/web", **kwargs):
        """JWT 토큰을 검증하고 Odoo 세션을 생성한다."""
        if not token:
            return request.redirect("/web/login")

        try:
            페이로드 = _jwt_검증(token)
        except Exception as 예외:
            로그_기록기.warning("OIDC JWT 검증 실패: %s", 예외)
            return request.redirect("/web/login")

        사용자_아이디 = 페이로드.get("preferred_username", "")
        이메일 = 페이로드.get("email", "")
        이름 = 페이로드.get("name", "") or 사용자_아이디

        if not 사용자_아이디:
            로그_기록기.warning("JWT에 preferred_username 없음")
            return request.redirect("/web/login")

        사용자_모델 = request.env["res.users"].sudo()
        사용자 = 사용자_모델.search([("login", "=", 사용자_아이디)], limit=1)

        if not 사용자:
            사용자 = 사용자_모델.create(
                {
                    "login": 사용자_아이디,
                    "name": 이름,
                    "email": 이메일,
                    "groups_id": [
                        (
                            6,
                            0,
                            [request.env.ref("base.group_user").id],
                        )
                    ],
                }
            )
            로그_기록기.info("OIDC 사용자 자동 생성: %s", 사용자_아이디)

        request.session.authenticate(
            request.db,
            사용자_아이디,
            {"type": "token"},
        )

        return request.redirect(redirect)

