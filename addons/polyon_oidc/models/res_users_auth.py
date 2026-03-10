from odoo import models
from odoo.exceptions import AccessDenied

class UsersAuth(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        """비밀번호 로그인 차단 — OAuth만 허용."""
        cred_type = credential.get('type', 'password') if isinstance(credential, dict) else 'password'
        if cred_type == 'password':
            raise AccessDenied('비밀번호 로그인이 비활성화되었습니다. PolyON SSO를 사용하세요.')
        return super()._check_credentials(credential, env)