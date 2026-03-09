import logging

from odoo.http import Root

logger = logging.getLogger(__name__)


def _install_iframe_header_patch():
    original_get_response = Root.get_response

    def patched_get_response(self, httprequest, result, explicit_session):
        response = original_get_response(self, httprequest, result, explicit_session)
        if "X-Frame-Options" in response.headers:
            response.headers.pop("X-Frame-Options", None)

        # 세션 쿠키가 iframe (크로스 도메인)에서도 동작하도록 SameSite=None; Secure를 강제한다
        session_cookie_name = "session_id"
        updated_cookies = []

        for header_name, header_value in response.headers.get_all("Set-Cookie", []):
            if session_cookie_name in header_value and "SameSite" not in header_value:
                # SameSite=None; Secure 속성이 없으면 추가한다
                header_value = header_value + "; SameSite=None; Secure"
            updated_cookies.append((header_name, header_value))

        if updated_cookies:
            # 기존 Set-Cookie 헤더를 제거하고 수정된 값으로 다시 설정한다
            response.headers.pop("Set-Cookie", None)
            for header_name, header_value in updated_cookies:
                response.headers.add(header_name, header_value)

        return response

    if getattr(Root, "_polyon_iframe_patched", False):
        return

    Root.get_response = patched_get_response
    Root._polyon_iframe_patched = True
    logger.info("PolyON iframe 패치가 적용되었습니다. X-Frame-Options 헤더가 제거됩니다.")


_install_iframe_header_patch()

