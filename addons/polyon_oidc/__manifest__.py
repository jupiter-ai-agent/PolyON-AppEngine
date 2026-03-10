{
    "name": "PolyON OIDC SSO",
    "version": "19.0.1.0.0",
    "category": "Authentication",
    "summary": "Keycloak OIDC SSO for PolyON Platform",
    "author": "Triangle.s",
    "depends": ["base", "web", "auth_oauth"],
    "data": [
        "views/hide_menus.xml",
        "views/login_template.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "auto_install": False,
    "license": "LGPL-3",
}

