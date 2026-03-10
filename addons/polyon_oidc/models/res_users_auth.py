from odoo import models, SUPERUSER_ID
from odoo.exceptions import AccessDenied


class UsersAuth(models.Model):
    _inherit = 'res.users'

    def _check_credentials(self, credential, env):
        """비밀번호 로그인 차단 — OAuth만 허용.

        예외: superuser(uid=1)와 admin(uid=2)은 비밀번호 허용.
        Core가 JSON-RPC로 Odoo API를 호출할 때 admin 인증이 필요하기 때문.
        """
        # superuser / admin은 비밀번호 허용 (Core JSON-RPC 접근용)
        if self.id in (SUPERUSER_ID, 2):
            return super()._check_credentials(credential, env)

        cred_type = credential.get('type', 'password') if isinstance(credential, dict) else 'password'
        if cred_type == 'password':
            raise AccessDenied('비밀번호 로그인이 비활성화되었습니다. PolyON SSO를 사용하세요.')
        return super()._check_credentials(credential, env)