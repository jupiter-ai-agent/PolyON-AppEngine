import json
import logging
import os
import secrets
import time

import jwt
import requests
import werkzeug.utils
from jwt.algorithms import RSAAlgorithm
from urllib.parse import urlencode

from odoo import http
from odoo.http import request


logger = logging.getLogger(__name__)

_jwks_cache = {}
_JWKS_TTL = 3600  # 1시간


def _oidc_env(key, fallback=""):
    return os.getenv(key, fallback)


def _oidc_config(admin=False):
    """PRC가 주입한 OIDC 환경변수에서 설정을 읽는다.
    
    admin=True: admin realm 설정 (Console 관리자 → Odoo admin 권한)
    admin=False: polyon realm 설정 (일반 사원)
    
    토큰 교환/JWKS는 서버→서버이므로 내부 K8s URL 우선.
    auth_endpoint는 브라우저→KC이므로 외부 URL 사용.
    """
    if admin:
        return {
            "issuer": _oidc_env("OIDC_ADMIN_ISSUER"),
            "client_id": _oidc_env("OIDC_ADMIN_CLIENT_ID"),
            "client_secret": _oidc_env("OIDC_ADMIN_CLIENT_SECRET"),
            "auth_endpoint": _oidc_env("OIDC_ADMIN_AUTH_ENDPOINT"),
            "token_endpoint": _oidc_env("OIDC_ADMIN_TOKEN_ENDPOINT_INTERNAL"),
            "jwks_uri": _oidc_env("OIDC_ADMIN_JWKS_URI_INTERNAL"),
            "is_admin": True,
        }
    return {
        "issuer": _oidc_env("OIDC_ISSUER"),
        "client_id": _oidc_env("OIDC_CLIENT_ID"),
        "client_secret": _oidc_env("OIDC_CLIENT_SECRET"),
        "auth_endpoint": _oidc_env("OIDC_AUTH_ENDPOINT"),
        "token_endpoint": _oidc_env("OIDC_TOKEN_ENDPOINT_INTERNAL") or _oidc_env("OIDC_TOKEN_ENDPOINT"),
        "jwks_uri": _oidc_env("OIDC_JWKS_URI_INTERNAL") or _oidc_env("OIDC_JWKS_URI"),
        "is_admin": False,
    }


def get_jwks(jwks_url):
    """Keycloak JWKS에서 공개키를 가져온다 (TTL 캐시)."""
    now = time.time()
    cached = _jwks_cache.get(jwks_url)
    if cached and (now - cached["ts"]) < _JWKS_TTL:
        return cached["keys"]
    response = requests.get(jwks_url, timeout=10)
    response.raise_for_status()
    keys = response.json().get("keys", [])
    _jwks_cache[jwks_url] = {"keys": keys, "ts": now}
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
        # kid miss — 캐시 무효화 후 재시도
        _jwks_cache.pop(cfg["jwks_uri"], None)
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


def _find_or_create_user(username, email, name, is_admin=False):
    """Odoo에서 사용자를 찾거나 자동 생성한다.
    
    is_admin=True: admin realm에서 로그인 → Odoo Administrator 권한 부여
    is_admin=False: polyon realm에서 로그인 → 일반 사원 권한
    """
    env = request.env
    user_model = env["res.users"].sudo()
    user = user_model.search([("login", "=", username)], limit=1)

    # 기본 회사 조회 (company_id NOT NULL)
    company = env["res.company"].sudo().search([], limit=1, order="id asc")
    company_id = company.id if company else 1

    if not user:
        user = user_model.with_context(polyon_sync=True, no_reset_password=True).create({
            "login": username,
            "name": name or username,
            "email": email or "",
            "company_id": company_id,
            "company_ids": [(4, company_id)],
            "group_ids": [(4, env.ref("base.group_user").id)],
        })
        logger.info("OIDC 사용자 자동 생성: %s (company_id=%s)", username, company_id)

    # admin realm 로그인 → Odoo Administrator 그룹 보장
    if is_admin:
        admin_group = env.ref("base.group_system", raise_if_not_found=False)
        if admin_group and admin_group not in user.sudo().group_ids:
            user.sudo().write({"group_ids": [(4, admin_group.id)]})
            logger.info("OIDC admin 권한 부여: %s", username)

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

        # state 생성 — 쿠키로 저장 (auth=none route에서 세션 불안정)
        state = secrets.token_urlsafe(32)
        redirect_dest = redirect or "/web"

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
        response = werkzeug.utils.redirect(auth_url, code=303)
        # state와 redirect를 쿠키에 저장 (httponly, samesite=lax)
        response.set_cookie("oidc_state", state, httponly=True, samesite="Lax", max_age=300)
        response.set_cookie("oidc_redirect", redirect_dest, httponly=True, samesite="Lax", max_age=300)
        return response

    # ── 2. Keycloak callback → Authorization Code → Token → 세션 생성 ──
    @http.route("/polyon/oidc/callback", type="http", auth="none", csrf=False)
    def oidc_callback(self, code=None, state=None, error=None, **kwargs):
        """Keycloak에서 돌아온 authorization code로 토큰 교환."""
        if error:
            logger.warning("OIDC 에러: %s", error)
            return request.redirect("/web")

        # state 검증 — 쿠키에서 읽기
        saved_state = request.httprequest.cookies.get("oidc_state")
        if not state or state != saved_state:
            logger.warning("OIDC state 불일치 (got=%s, saved=%s)", state, saved_state)
            return request.redirect("/web")

        cfg = _oidc_config()
        redirect_to = request.httprequest.cookies.get("oidc_redirect", "/web")

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

        # 사용자 찾기/생성
        try:
            user = _find_or_create_user(username, email, name)
        except Exception as e:
            logger.error("OIDC 사용자 생성/조회 실패: %s", e)
            return request.redirect("/web?oidc_error=user_create")

        # Odoo 19 세션 설정 — session.finalize() 방식과 동일하게
        env = request.env(user=user.id)
        user_context = dict(env["res.users"].context_get())

        request.session.should_rotate = True
        request.session.update({
            "db": request.db,
            "login": user.login,
            "uid": user.id,
            "context": user_context,
            "session_token": user.sudo()._compute_session_token(request.session.sid),
        })

        logger.info("OIDC 로그인 성공: %s (uid=%s)", user.login, user.id)
        return request.redirect(redirect_to)

    # ── 3. Admin realm 로그인 시작 (Console → Odoo Admin) ──
    @http.route("/polyon/oidc/admin/login", type="http", auth="none", website=False)
    def oidc_admin_login(self, redirect=None, **kwargs):
        """Console 관리자 전용 — admin realm으로 Keycloak 인증 후 Odoo Administrator 권한 부여."""
        if request.session.uid:
            return request.redirect(redirect or "/web")

        cfg = _oidc_config(admin=True)
        if not cfg["auth_endpoint"] or not cfg["client_id"]:
            logger.warning("admin realm OIDC 미설정")
            return request.redirect("/web")

        state = secrets.token_urlsafe(32)
        redirect_dest = redirect or "/web"

        base_url = request.httprequest.host_url.rstrip("/")
        redirect_uri = base_url + "/polyon/oidc/admin/callback"

        params = {
            "client_id": cfg["client_id"],
            "response_type": "code",
            "scope": "openid profile email",
            "redirect_uri": redirect_uri,
            "state": state,
        }

        auth_url = cfg["auth_endpoint"] + "?" + urlencode(params)
        response = werkzeug.utils.redirect(auth_url, code=303)
        response.set_cookie("oidc_admin_state", state, httponly=True, samesite="Lax", max_age=300)
        response.set_cookie("oidc_admin_redirect", redirect_dest, httponly=True, samesite="Lax", max_age=300)
        return response

    # ── 4. Admin realm 콜백 ──
    @http.route("/polyon/oidc/admin/callback", type="http", auth="none", csrf=False)
    def oidc_admin_callback(self, code=None, state=None, error=None, **kwargs):
        """admin realm KC 콜백 — Administrator 권한으로 세션 생성."""
        if error:
            logger.warning("admin OIDC 에러: %s", error)
            return request.redirect("/web")

        saved_state = request.httprequest.cookies.get("oidc_admin_state")
        if not state or state != saved_state:
            logger.warning("admin OIDC state 불일치")
            return request.redirect("/web")

        cfg = _oidc_config(admin=True)
        redirect_to = request.httprequest.cookies.get("oidc_admin_redirect", "/web")

        base_url = request.httprequest.host_url.rstrip("/")
        redirect_uri = base_url + "/polyon/oidc/admin/callback"

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
            logger.error("admin OIDC 토큰 교환 실패: %s", e)
            return request.redirect("/web")

        id_token = tokens.get("id_token", "")
        try:
            payload = verify_jwt(id_token, cfg)
        except Exception as e:
            logger.warning("admin OIDC ID Token 검증 실패: %s", e)
            return request.redirect("/web")

        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            return request.redirect("/web")

        try:
            user = _find_or_create_user(username, email, name, is_admin=True)
        except Exception as e:
            logger.error("admin OIDC 사용자 처리 실패: %s", e)
            return request.redirect("/web?oidc_error=user_create")

        env = request.env(user=user.id)
        user_context = dict(env["res.users"].context_get())

        request.session.should_rotate = True
        request.session.update({
            "db": request.db,
            "login": user.login,
            "uid": user.id,
            "context": user_context,
            "session_token": user.sudo()._compute_session_token(request.session.sid),
        })

        logger.info("admin OIDC 로그인 성공: %s (uid=%s)", user.login, user.id)
        return request.redirect(redirect_to)

    # ── 5. iframe용 JWT 직접 로그인 (Console/Portal에서 사용) ──
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

        user = _find_or_create_user(username, email, name)

        env = request.env(user=user.id)
        user_context = dict(env["res.users"].context_get())
        request.session.should_rotate = True
        request.session.update({
            "db": request.db,
            "login": user.login,
            "uid": user.id,
            "context": user_context,
            "session_token": user.sudo()._compute_session_token(request.session.sid),
        })

        return request.redirect(redirect)
