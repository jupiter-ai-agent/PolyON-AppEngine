# -*- coding: utf-8 -*-

import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LdapTestUsersWizard(models.TransientModel):
    _name = 'ldap.test.users.wizard'
    _description = 'Test LDAP Users Wizard'

    ldap_id = fields.Many2one('res.company.ldap', string='LDAP Server', readonly=True)
    line_ids = fields.One2many('ldap.test.users.wizard.line', 'wizard_id', string='Users')
    user_count = fields.Integer(string='User Count', compute='_compute_user_count')
    has_incomplete_users = fields.Boolean(string='Has Incomplete Users', compute='_compute_has_incomplete_users')

    @api.depends('line_ids')
    def _compute_user_count(self):
        for wizard in self:
            wizard.user_count = len(wizard.line_ids)

    @api.depends('line_ids.is_complete')
    def _compute_has_incomplete_users(self):
        for wizard in self:
            wizard.has_incomplete_users = any(not line.is_complete for line in wizard.line_ids)


class LdapTestUsersWizardLine(models.TransientModel):
    _name = 'ldap.test.users.wizard.line'
    _description = 'Test LDAP Users Wizard Line'

    wizard_id = fields.Many2one('ldap.test.users.wizard', string='Wizard', ondelete='cascade')
    screen_name = fields.Char(string='Screen Name')
    email = fields.Char(string='Email Address')
    first_name = fields.Char(string='First Name')
    last_name = fields.Char(string='Last Name')
    job_title = fields.Char(string='Job Title')
    group_count = fields.Integer(string='Groups')
    is_complete = fields.Boolean(string='Is Complete', compute='_compute_is_complete')

    @api.depends('screen_name', 'email', 'first_name', 'last_name')
    def _compute_is_complete(self):
        for line in self:
            line.is_complete = bool(line.screen_name and line.email and line.first_name and line.last_name)
