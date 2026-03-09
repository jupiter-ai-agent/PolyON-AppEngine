from odoo import api, fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    def _get_ldap_environment_configuration(self):
        # PRC 환경변수에서 LDAP 설정 값을 읽는다
        parameter_values = {
            "ldap_server": self.env["ir.config_parameter"].sudo().get_param(
                "polyon_ldap_auto.ldap_server", default=""
            ),
            "ldap_server_port": self.env["ir.config_parameter"]
            .sudo()
            .get_param("polyon_ldap_auto.ldap_server_port", default=""),
            "ldap_binddn": self.env["ir.config_parameter"].sudo().get_param(
                "polyon_ldap_auto.ldap_binddn", default=""
            ),
            "ldap_password": self.env["ir.config_parameter"]
            .sudo()
            .get_param("polyon_ldap_auto.ldap_password", default=""),
            "ldap_base": self.env["ir.config_parameter"].sudo().get_param(
                "polyon_ldap_auto.ldap_base", default=""
            ),
        }
        return parameter_values

    @api.model
    def create_default_ldap_configuration_from_environment(self):
        # 기본 Company에 대한 LDAP 공급자를 PRC 환경변수 기반으로 생성한다
        main_company = self.env.ref("base.main_company", raise_if_not_found=False)
        if not main_company:
            return

        ldap_configuration_model = self.env["res.company.ldap"].sudo()

        existing_configuration = ldap_configuration_model.search(
            [("company", "=", main_company.id)], limit=1
        )
        if existing_configuration:
            return

        environment_values = self._get_ldap_environment_configuration()

        if not environment_values.get("ldap_server") or not environment_values.get(
            "ldap_base"
        ):
            return

        ldap_configuration_model.create(
            {
                "company": main_company.id,
                "ldap_server": environment_values["ldap_server"],
                "ldap_server_port": int(
                    environment_values.get("ldap_server_port") or "389"
                ),
                "ldap_binddn": environment_values["ldap_binddn"],
                "ldap_password": environment_values["ldap_password"],
                "ldap_base": environment_values["ldap_base"],
                "ldap_filter": "(&(objectClass=user)(sAMAccountName=%s))",
                "ldap_tls": False,
                "create_user": True,
            }
        )

