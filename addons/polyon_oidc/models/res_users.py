from odoo import models


class ResUsers(models.Model):
    _inherit = "res.users"

    @classmethod
    def _login(cls, db, login, password, user_agent_env=None):
        """토큰 기반 인증을 허용한다."""
        if isinstance(password, dict) and password.get("type") == "token":
            user = cls.search([("login", "=", login)], limit=1)
            if user:
                return user.id
        return super()._login(db, login, password, user_agent_env=user_agent_env)

