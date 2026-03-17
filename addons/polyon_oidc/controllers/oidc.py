import base64
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
_logger = logger  # alias for compatibility


# ── KC JWT groups 클레임 → Odoo [AD Group] 동기화 헬퍼 (teps 패턴 포팅) ──────

def _get_groups_from_token(access_token):
    """JWT access_token payload에서 groups 클레임 추출 (검증 없이 파싱).

    KC polyon realm에 LDAP 그룹 매퍼가 설정된 경우 groups 클레임이 포함됨.
    - DN 형식: 'CN=Sales,OU=Groups,DC=cmars,DC=com'
    - 이름 형식: 'Sales'
    클레임이 없으면 빈 리스트 반환 → 동기화 skip.
    """
    try:
        parts = access_token.split('.')
        if len(parts) < 2:
            return []
        # Base64 URL padding 보정
        padded = parts[1] + '=' * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.b64decode(padded).decode('utf-8'))
        groups = payload.get('groups', [])
        return groups if isinstance(groups, list) else []
    except Exception:
        return []


def _extract_cn_from_dn(dn):
    """DN에서 CN 값 추출.

    'CN=Sales,OU=Groups,DC=cmars,DC=com' → 'Sales'
    이미 이름 형식(= 없음)이면 그대로 반환.
    """
    if not dn:
        return None
    if '=' not in dn:
        return dn  # 이미 이름 형식
    for part in dn.split(','):
        part = part.strip()
        if part.upper().startswith('CN='):
            return part[3:]
    return None


def _get_or_create_odoo_group(env, group_name, source_dn=None):
    """Odoo에서 그룹 검색. 없으면 [AD Group] 마커로 신규 생성.

    teps _get_or_create_odoo_group() 패턴.
    source_dn: LDAP DN 또는 KC 그룹 경로 (comment에 기록)
    """
    ResGroups = env['res.groups'].sudo()

    # 대소문자 무관 검색
    existing = ResGroups.search([('name', '=ilike', group_name)], limit=1)
    if existing:
        _logger.debug("Found existing group: %s (id=%d)", group_name, existing.id)
        return existing.id

    # 신규 생성 — comment에 [AD Group] 마커 삽입 (teps 패턴)
    try:
        comment = f'[AD Group] Auto-created from Active Directory.'
        if source_dn:
            comment += f'\nSource DN: {source_dn}'
        new_group = ResGroups.create({
            'name': group_name,
            'comment': comment,
        })
        _logger.info("Created [AD Group]: %s (id=%d)", group_name, new_group.id)
        return new_group.id
    except Exception as e:
        _logger.error("Group create failed for %s: %s", group_name, e)
        return None


def _update_user_ad_groups(user, new_group_ids):
    """사용자의 [AD Group] 계열 그룹만 갱신. 기타 그룹(권한 등)은 유지.

    teps _update_user_ad_groups() 패턴.
    """
    # [AD Group] 마커가 있는 현재 그룹만 대상
    current_ad_groups = user.group_ids.filtered(
        lambda g: g.comment and '[AD Group]' in g.comment
    )

    commands = []
    # 새 목록에 없는 기존 AD 그룹 제거
    for group in current_ad_groups:
        if group.id not in new_group_ids:
            commands.append((3, group.id))
    # 새 그룹 추가 (현재 없는 것만)
    current_ids = set(user.group_ids.ids)
    for gid in new_group_ids:
        if gid not in current_ids:
            commands.append((4, gid))

    if commands:
        user.sudo().write({'group_ids': commands})
        removed = sum(1 for c in commands if c[0] == 3)
        added = sum(1 for c in commands if c[0] == 4)
        _logger.debug("Updated AD groups for %s: -%d +%d", user.login, removed, added)


def _sync_ad_groups_from_token(user, access_token):
    """KC JWT access_token → Odoo [AD Group] 동기화 (teps 방식).

    - access_token에서 groups 클레임을 직접 추출
    - groups 클레임 없으면(KC 매퍼 미설정 등) 동기화 skip → 로그인은 정상 진행
    - KC 경로 형식('/Sales') 및 LDAP DN 형식('CN=Sales,...') 모두 처리
    - 실패해도 로그인은 계속 진행

    teps _sync_ad_groups_for_user() 패턴 포팅.
    """
    try:
        groups = _get_groups_from_token(access_token)
        if not groups:
            return  # groups 클레임 없음 → KC 매퍼 미설정, skip

        new_group_ids = set()
        for group_entry in groups:
            # KC group-ldap-mapper는 '/Sales' 또는 'CN=Sales,...' 형태로 전달
            if group_entry.startswith('/'):
                # KC 기본 그룹 경로 형식: '/Sales' → 'Sales'
                group_name = group_entry.lstrip('/')
                source_dn = group_entry
            else:
                # LDAP DN 형식
                group_name = _extract_cn_from_dn(group_entry)
                source_dn = group_entry

            if not group_name:
                continue

            gid = _get_or_create_odoo_group(user.env, group_name, source_dn)
            if gid:
                new_group_ids.add(gid)

        _update_user_ad_groups(user, new_group_ids)
        _logger.info(
            "AD group sync completed for %s: %d groups",
            user.login, len(new_group_ids)
        )
    except Exception as e:
        _logger.warning("AD group sync failed for %s: %s", getattr(user, 'login', '?'), e)

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


def verify_jwt(token, cfg, verify_audience=True):
    """JWT를 Keycloak 공개키로 검증하고 payload를 반환한다.
    
    verify_audience=False: token-auth처럼 access_token을 직접 받는 경우
    (KC access_token의 aud는 리소스 서버 기준이라 client_id와 다를 수 있음)
    """
    if not all([cfg["issuer"], cfg["jwks_uri"]]):
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

    decode_options = {}
    if not verify_audience:
        decode_options["verify_aud"] = False

    payload = jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        issuer=cfg["issuer"],
        audience=cfg["client_id"] if verify_audience else None,
        options=decode_options,
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
            logger.error("OIDC 사용자 생성/조회 실패: %s", e, exc_info=True)
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

        # KC access_token → Odoo [AD Group] 동기화 (teps 방식)
        access_token = tokens.get("access_token", "")
        _sync_ad_groups_from_token(user, access_token)

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
            logger.error("admin OIDC 사용자 처리 실패: %s", e, exc_info=True)
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

        # KC access_token → Odoo [AD Group] 동기화 (teps 방식)
        access_token = tokens.get("access_token", "")
        _sync_ad_groups_from_token(user, access_token)

        logger.info("admin OIDC 로그인 성공: %s (uid=%s)", user.login, user.id)
        return request.redirect(redirect_to)

    # ── 5. Console admin token-auth — Bearer JWT → Odoo 세션 (CORS) ──
    @http.route("/polyon/oidc/admin/token-auth", type="http", auth="none", methods=["POST", "OPTIONS"], csrf=False)
    def admin_token_auth(self, **kwargs):
        """Console이 admin realm access_token으로 Odoo 세션을 직접 생성.

        CORS: console.cmars.com → apps.cmars.com cross-origin 허용.
        Console에서 이미 KC admin realm 인증이 된 상태이므로 재인증 불필요.
        """
        from werkzeug.wrappers import Response as WerkzeugResponse

        origin = request.httprequest.headers.get("Origin", "")
        ALLOWED_ORIGINS = ["https://console.cmars.com"]

        def _cors(resp):
            if origin in ALLOWED_ORIGINS:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
                resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
                resp.headers["Vary"] = "Origin"
            return resp

        def _json(data, status=200):
            return _cors(WerkzeugResponse(
                json.dumps(data), status=status, content_type="application/json"
            ))

        # CORS preflight
        if request.httprequest.method == "OPTIONS":
            return _cors(WerkzeugResponse(status=204))

        auth_header = request.httprequest.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return _json({"error": "no token"}, 401)

        token = auth_header[7:]
        cfg = _oidc_config(admin=True)

        try:
            payload = verify_jwt(token, cfg, verify_audience=False)
        except Exception as e:
            logger.warning("admin token-auth JWT 검증 실패: %s", e)
            return _json({"error": "invalid token"}, 401)

        username = payload.get("preferred_username", "")
        email = payload.get("email", "")
        name = payload.get("name", "") or username

        if not username:
            return _json({"error": "no username"}, 400)

        try:
            user = _find_or_create_user(username, email, name, is_admin=True)
        except Exception as e:
            logger.error("admin token-auth 사용자 처리 실패: %s", e)
            return _json({"error": "user create failed"}, 500)

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

        logger.info("admin token-auth 로그인 성공: %s (uid=%s)", user.login, user.id)
        return _json({"status": "ok", "uid": user.id})

    # ── 6. iframe용 JWT 직접 로그인 (Console/Portal에서 사용) ──
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

    # ── 7. 내부 그룹 재동기화 — Core API에서 호출 ──────────────────────────────
    @http.route("/polyon/oidc/internal/group-sync", type="http", auth="none", methods=["POST"], csrf=False)
    def internal_group_sync(self, **kwargs):
        """내부 전용 — Core API가 호출하여 모든 Odoo 사용자의 KC 그룹 재동기화.

        KC Admin API로 각 사용자의 그룹을 조회하고 Odoo [AD Group] 동기화.
        cluster 내부에서만 호출 가능 (인증 없음).
        """
        from werkzeug.wrappers import Response as WerkzeugResponse

        def _json(data, status=200):
            return WerkzeugResponse(
                json.dumps(data), status=status, content_type="application/json"
            )

        kc_url = os.getenv("KC_INTERNAL_URL", "http://polyon-auth.polyon.svc.cluster.local:8080")
        kc_admin_password = os.getenv("KC_ADMIN_PASSWORD", "")

        if not kc_admin_password:
            logger.error("internal_group_sync: KC_ADMIN_PASSWORD not set")
            return _json({"error": "KC_ADMIN_PASSWORD not configured"}, 500)

        # KC Admin 토큰 획득
        try:
            token_resp = requests.post(
                f"{kc_url}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "admin-cli",
                    "username": "admin",
                    "password": kc_admin_password,
                },
                timeout=10,
            )
            token_resp.raise_for_status()
            admin_token = token_resp.json().get("access_token", "")
        except Exception as e:
            logger.error("internal_group_sync: KC admin token failed: %s", e)
            return _json({"error": "KC admin token failed"}, 500)

        kc_headers = {"Authorization": f"Bearer {admin_token}"}

        # Odoo 사용자 목록 (admin/system 제외)
        env = request.env
        excluded = ["admin", "__system__", "OdooBot", "public"]
        users = env["res.users"].sudo().search([
            ("active", "=", True),
            ("login", "not in", excluded),
        ])

        synced = 0
        skipped = 0
        errors = 0

        for user in users:
            try:
                # KC에서 사용자 검색
                search_resp = requests.get(
                    f"{kc_url}/admin/realms/polyon/users",
                    params={"username": user.login, "exact": "true", "max": 1},
                    headers=kc_headers,
                    timeout=5,
                )
                if search_resp.status_code != 200:
                    skipped += 1
                    continue

                kc_users = search_resp.json()
                if not kc_users:
                    skipped += 1
                    continue

                kc_user_id = kc_users[0].get("id")
                if not kc_user_id:
                    skipped += 1
                    continue

                # KC 사용자 그룹 조회
                groups_resp = requests.get(
                    f"{kc_url}/admin/realms/polyon/users/{kc_user_id}/groups",
                    headers=kc_headers,
                    timeout=5,
                )
                if groups_resp.status_code != 200:
                    skipped += 1
                    continue

                kc_groups = groups_resp.json()
                # KC Admin API에서 가져온 그룹 이름 목록 → Odoo [AD Group] 동기화
                group_names = [g.get("name", "") for g in kc_groups if g.get("name")]

                new_group_ids = set()
                for gname in group_names:
                    if not gname:
                        continue
                    gid = _get_or_create_odoo_group(user.env, gname, source_dn=f"KC:{gname}")
                    if gid:
                        new_group_ids.add(gid)
                _update_user_ad_groups(user, new_group_ids)
                synced += 1

            except Exception as e:
                logger.warning("internal_group_sync: error for %s: %s", user.login, e)
                errors += 1

        logger.info(
            "internal_group_sync completed: synced=%d skipped=%d errors=%d",
            synced, skipped, errors
        )
        return _json({"synced": synced, "skipped": skipped, "errors": errors})
