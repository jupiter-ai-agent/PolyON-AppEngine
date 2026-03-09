import json
import logging
import os
import secrets

import jwt
import requests
from jwt.algorithms import RSAAlgorithm
from urllib.parse import urlencode

from odoo import http
from odoo.http import request


logger = logging.getLogger(__name__)

jwks_cache = {}


def _oidc_env(key, fallback=""):
    return os.getenv(key, fallback)


def _oidc_config():
    """PRC가 주입한 OIDC 환경변수에서 설정을 읽는다."""
    return {
        "issuer": _oidc_env("OIDC_ISSUER"),
        "client_id": _oidc_env("OIDC_CLIENT_ID"),
        "client_secret": _oidc_env("OIDC_CLIENT_SECRET"),
        "auth_endpoint": _oidc_env("OIDC_AUTH_ENDPOINT"),
        "token_endpoint": _oidc_env("OIDC_TOKEN_ENDPOINT"),
        "jwks_uri": _oidc_env("OIDC_JWKS_URI"),
    }


def get_jwks(jwks_url):
    """Keycloak JWKS 엔드포인트에서 공개키를 가져온다."""
    if jwks_url in jwks_cache:
        return jwks_cache[jwks_url]
    response = requests.get(jwks_url, timeout=10)
    response.raise_for_status()
    keys = response.json().get("keys", [])
    jwks_cache[jwks_url] = keys
    return keys


def verify_jwt(token, cfg):
    """JWT를 Keycloak 공개키로 검증하고 payload를 반환한다."""
    if not all([cfg["issuer"], cfg["client_id"], cfg["jwks_uri"]]):
        raise ValueError("OIDC 환경변수 미설정")

    unverified_header = jwt.get_unverified_header(token)
    key_identifier = unverified_header.get("kid")

    keys = get_jwks(cfg["jwks_uri"])
    key_data = next((key for key in keys if key.get("kid") == key_identifier), None)
    if not key_data:
        raise ValueError(f"JWKS에서 kid={key_identifier} 키를 찾을 수 없음")

    public_key = RSAAlgorithm.from_jwk(json.dumps(key_data))

    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=cfg["issuer"],
        audience=cfg["client_id"],
    )
    return payload


def _find_or_create_user(username, email, name):
    """Odoo에서 사용자를 찾거나 자동 생성한다."""
    user_model = request.env["res.users"].sudo()
    user = user_model.search([("login", "=", username)], limit=1)

    if not user:
        user = user_model.create({
            "login": username,
            "name": name or username,
            "email": email or "",
            "groups_id": [(6, 0, [request.env.ref("base.group_user").id])],
        })
        logger.info("OIDC 사용자 자동 생성: %s", username)

    return user


class OIDCController(http.Controller):

    # ── 1. /web/login override → Keycloak으로 리다이렉트 ──
    @http.route("/web/login", type="http", auth="none", website=False)
    def web_login(self, redirect=None, **kwargs):
        """Odoo 기본 로그인 대신 Keycloak Authorization Code Flow 시작."""
        # 이미 로그인된 세션이면 바로 리다이렉트
        if request.session.uid:
            return request.redirect(redirect or "/web")

        cfg = _oidc_config()
        if not cfg["auth_endpoint"] or not cfg["client_id"]:
            # OIDC 미설정 — fallback (개발 환경)
            logger.warning("OIDC 미설정, 기본 로그인으로 fallback")
            return request.render("web.login", {"error": "OIDC 설정을 확인하세요"})

        # PKCE state 생성
        state = secrets.token_urlsafe(32)
        request.session["oidc_state"] = state
        request.session["oidc_redirect"] = redirect or "/web"

        # Keycloak의 redirect_uri = Odoo의 callback 엔드포인트
        base_url = request.httprequest.host_url.rstrip("/")
        redirect_uri = base_url + "/polyon/oidc/callback"

        params = {
            "client_id": cfg["client_id"],
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": redirect_uri,
            "state": state,
        }

        auth_url = cfg["auth_endpoint"] + "?" + urlencode(params)
        return request.redirect(auth_url)

    # ── 2. Keycloak callback → Authorization Code → Token → 세션 생성 ──
    @http.route("/polyon/oidc/callback", type="http", auth="none", csrf=False)
    def oidc_callback(self, code=None, state=None, error=None, **kwargs):
        """Keycloak에서 돌아온 authorization code로 토큰 교환."""
        if error:
            logger.warning("OIDC 에러: %s", error)
            return request.redirect("/web")

        # state 검증
        saved_state = request.session.pop("oidc_state", None)
        if not state or state != saved_state:
            logger.warning("OIDC state 불일치")
            return request.redirect("/web")

        cfg = _oidc_config()
        redirect_to = request.session.pop("oidc_redirect", "/web")

        # Authorization Code → Token 교환
        base_url = request.httprequest.host_url.rstrip("/")
        redirect_uri = base_url + "/polyon/oidc/callback"

        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": cfg["client_id"],
        }
        if cfg["client_secret"]:
            token_data["client_secret"] = cfg["client_secret"]

        try:
            resp = requests.post(cfg["token_endpoint"], data=token_data, timeout=10)
            resp.raise_for_status()
            tokens = resp.json()
        except Exception as e:
            logger.error("OIDC 토큰 교환 실패: %s", e)
            return request.redirect("/web")

        # ID Token 검증
        id_token = tokens.get("id_token", "")
        try:
            payload = verify_jwt(id_token, cfg)
        except Exception as e:
            logger.warning("OIDC ID Token 검증 실패: %s", e)
            return request.redirect("/web")

        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            logger.warning("ID Token에 preferred_username 없음")
            return request.redirect("/web")

        # 사용자 찾기/생성 + 세션
        _find_or_create_user(username, email, name)

        request.session.authenticate(
            request.db,
            username,
            {"type": "token"},
        )

        return request.redirect(redirect_to)

    # ── 3. iframe용 JWT 직접 로그인 (Console/Portal에서 사용) ──
    @http.route("/polyon/oidc/login", type="http", auth="none", csrf=False)
    def oidc_login(self, token=None, redirect="/web", **kwargs):
        """Console/Portal iframe에서 JWT 토큰으로 직접 로그인."""
        if not token:
            return request.redirect("/web/login")

        cfg = _oidc_config()
        try:
            payload = verify_jwt(token, cfg)
        except Exception as e:
            logger.warning("OIDC JWT 검증 실패: %s", e)
            return request.redirect("/web/login")

        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            return request.redirect("/web/login")

        _find_or_create_user(username, email, name)

        request.session.authenticate(
            request.db,
            username,
            {"type": "token"},
        )

        return request.redirect(redirect)
