"""
PolyON Iframe Support — Console/Portal iframe 임베딩을 위한 패치 (Odoo 19 호환)

1. X-Frame-Options 헤더 제거
2. session_id 쿠키에 SameSite=None; Secure 강제
"""
import logging

logger = logging.getLogger(__name__)


def polyon_iframe_post_load():
    """Odoo post_load hook — Application.__call__ 패치"""
    from odoo.http import Application

    original_call = Application.__call__

    def patched_call(self, environ, start_response):
        """WSGI 응답 헤더에서 X-Frame-Options 제거 + SameSite 패치"""

        patched_headers = []

        def custom_start_response(status, headers, exc_info=None):
            new_headers = []
            for name, value in headers:
                # X-Frame-Options 제거
                if name.lower() == 'x-frame-options':
                    continue
                # session_id 쿠키에 SameSite=None; Secure
                if name.lower() == 'set-cookie' and 'session_id' in value:
                    if 'SameSite' not in value:
                        value = value + '; SameSite=None; Secure'
                new_headers.append((name, value))
            return start_response(status, new_headers, exc_info)

        return original_call(self, environ, custom_start_response)

    if getattr(Application, '_polyon_iframe_patched', False):
        return

    Application.__call__ = patched_call
    Application._polyon_iframe_patched = True
    logger.info("PolyON iframe 패치 적용: X-Frame-Options 제거 + SameSite=None")
