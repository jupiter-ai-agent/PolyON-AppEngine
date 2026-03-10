from odoo import models, api
from odoo.exceptions import UserError

class Users(models.Model):
    _inherit = 'res.users'

    @api.model_create_multi
    def create(self, vals_list):
        """PP Core(polyon_sync context)만 사용자 생성 허용."""
        if not self.env.context.get('polyon_sync'):
            raise UserError(
                '사용자 생성은 PolyON Console에서만 가능합니다.\n'
                'AD 계정을 추가하면 자동으로 동기화됩니다.'
            )
        return super().create(vals_list)

    def write(self, vals):
        """보호 필드 변경은 PP Core만 허용."""
        protected_fields = {'name', 'login', 'email', 'password', 'active', 'oauth_uid'}
        if protected_fields & set(vals.keys()):
            if not self.env.context.get('polyon_sync'):
                raise UserError(
                    '사용자 정보는 PolyON Console에서 변경하세요.\n'
                    'AD 계정 정보가 자동 동기화됩니다.'
                )
        return super().write(vals)

    def unlink(self):
        """사용자 삭제 차단 — 비활성화만 허용."""
        if not self.env.context.get('polyon_sync'):
            raise UserError('사용자 삭제는 PolyON Console에서만 가능합니다.')
        return super().unlink()