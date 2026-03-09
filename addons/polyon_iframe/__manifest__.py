{
    "name": "PolyON Iframe Support",
    "summary": "X-Frame-Options 헤더를 제거하여 Console/Portal iframe 임베딩을 허용하는 모듈",
    "version": "0.2.0",
    "author": "Triangle.s",
    "website": "https://github.com/jupiter-ai-agent/PolyON-Odoo",
    "license": "LGPL-3",
    "category": "Web",
    "depends": ["web"],
    "data": [],
    "post_load": "polyon_iframe_post_load",
    "installable": True,
    "auto_install": False,
}
