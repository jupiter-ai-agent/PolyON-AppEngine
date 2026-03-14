# -*- coding: utf-8 -*-
from . import controllers
from . import models
from . import wizard


def _post_init_update_cron(env):
    """Update cron to point to ldap.sync.wizard model (for existing databases)."""
    cron = env.ref('polyon_ldap_connector.ir_cron_ldap_user_import', raise_if_not_found=False)
    if cron:
        model = env['ir.model'].search([('model', '=', 'ldap.sync.wizard')], limit=1)
        if model and cron.ir_actions_server_id:
            cron.ir_actions_server_id.write({
                'model_id': model.id,
                'code': 'model._cron_sync_ldap()',
            })
