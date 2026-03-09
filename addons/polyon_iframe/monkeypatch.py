import logging

from odoo.http import Root

logger = logging.getLogger(__name__)


def _install_iframe_header_patch():
    original_get_response = Root.get_response

    def patched_get_response(self, httprequest, result, explicit_session):
        response = original_get_response(self, httprequest, result, explicit_session)
        if "X-Frame-Options" in response.headers:
            response.headers.pop("X-Frame-Options", None)
        return response

    if getattr(Root, "_polyon_iframe_patched", False):
        return

    Root.get_response = patched_get_response
    Root._polyon_iframe_patched = True
    logger.info("PolyON iframe 패치가 적용되었습니다. X-Frame-Options 헤더가 제거됩니다.")


_install_iframe_header_patch()

