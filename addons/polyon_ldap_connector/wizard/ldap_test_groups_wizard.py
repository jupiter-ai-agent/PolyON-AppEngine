# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LdapTestGroupsWizard(models.TransientModel):
    _name = 'ldap.test.groups.wizard'
    _description = 'Test LDAP Groups Wizard'

    ldap_id = fields.Many2one('res.company.ldap', string='LDAP Server', readonly=True)
    line_ids = fields.One2many('ldap.test.groups.wizard.line', 'wizard_id', string='Groups')
    group_count = fields.Integer(string='Group Count', compute='_compute_group_count')

    @api.depends('line_ids')
    def _compute_group_count(self):
        for wizard in self:
            wizard.group_count = len(wizard.line_ids)


class LdapTestGroupsWizardLine(models.TransientModel):
    _name = 'ldap.test.groups.wizard.line'
    _description = 'Test LDAP Groups Wizard Line'

    wizard_id = fields.Many2one('ldap.test.groups.wizard', string='Wizard', ondelete='cascade')
    sequence = fields.Integer(string='#')
    name = fields.Char(string='Name')
    description = fields.Char(string='Description')
    member_count = fields.Integer(string='Members')
