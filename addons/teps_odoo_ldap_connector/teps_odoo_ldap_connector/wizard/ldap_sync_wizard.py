# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

SYNC_MODE_SELECTION = [
    ('group', 'Group Policy'),
    ('enable', 'Include'),
    ('disable', 'Exclude'),
]


class LdapSyncWizard(models.Model):
    _name = 'ldap.sync.wizard'
    _description = 'LDAP Sync Wizard'
    _auto = True

    # LDAP 서버당 위자드 1개만 허용
    _ldap_id_unique = models.Constraint(
        'UNIQUE(ldap_id)',
        'A sync wizard already exists for this LDAP server.',
    )

    ldap_id = fields.Many2one('res.company.ldap', string='LDAP Server', readonly=True, required=True)
    ldap_server_name = fields.Char(related='ldap_id.ldap_server', string='Server', readonly=True)

    user_line_ids = fields.One2many('ldap.sync.wizard.user.line', 'wizard_id', string='Users')
    group_line_ids = fields.One2many('ldap.sync.wizard.group.line', 'wizard_id', string='Groups')

    # Counts (computed)
    user_count = fields.Integer(string='Total Users', compute='_compute_counts')
    group_count = fields.Integer(string='Total Groups', compute='_compute_counts')
    sync_user_count = fields.Integer(string='Sync Target Users', compute='_compute_counts')
    selected_group_count = fields.Integer(string='Selected Groups', compute='_compute_counts')

    # ── Scheduling ──
    sync_enabled = fields.Boolean(string='Enable Scheduled Sync', default=False)
    sync_interval = fields.Integer(string='Sync Interval (minutes)', default=60)

    # ── Sync Status ──
    last_sync_date = fields.Datetime(string='Last Sync Date', readonly=True)
    last_sync_status = fields.Char(string='Last Sync Status', readonly=True)
    last_sync_user_count = fields.Integer(string='Last Sync Users', readonly=True)

    @api.depends('user_line_ids.sync_mode', 'user_line_ids.is_sync_target',
                 'group_line_ids.selected')
    def _compute_counts(self):
        for wizard in self:
            wizard.user_count = len(wizard.user_line_ids)
            wizard.group_count = len(wizard.group_line_ids)
            wizard.sync_user_count = len(wizard.user_line_ids.filtered('is_sync_target'))
            wizard.selected_group_count = len(wizard.group_line_ids.filtered('selected'))

    def write(self, vals):
        """sync_enabled/sync_interval 변경 시 cron 간격도 동기화"""
        res = super().write(vals)
        if 'sync_enabled' in vals or 'sync_interval' in vals:
            self._update_cron_interval()
        return res

    def _update_cron_interval(self):
        """위자드의 sync_interval 값을 cron에 반영"""
        cron = self.env.ref(
            'teps_odoo_ldap_connector.ir_cron_ldap_user_import',
            raise_if_not_found=False
        )
        if not cron:
            return
        # sync_enabled인 위자드가 하나라도 있으면 cron 활성화
        enabled_wizards = self.sudo().search([('sync_enabled', '=', True)])
        if enabled_wizards:
            # 가장 짧은 interval 사용
            min_interval = min(w.sync_interval for w in enabled_wizards)
            min_interval = max(min_interval, 1)  # 최소 1분
            cron.sudo().write({
                'active': True,
                'interval_number': min_interval,
                'interval_type': 'minutes',
            })
        else:
            cron.sudo().write({'active': False})

    def _reload(self):
        """현재 위자드 페이지를 새로고침"""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # =========================================================================
    # Bulk Actions (return False to preserve tab position)
    # =========================================================================
    def action_set_all_users_enable(self):
        self.user_line_ids.write({'sync_mode': 'enable'})
        return False

    def action_set_all_users_disable(self):
        self.user_line_ids.write({'sync_mode': 'disable'})
        return False

    def action_set_all_users_group(self):
        self.user_line_ids.write({'sync_mode': 'group'})
        return False

    def action_select_all_groups(self):
        self.group_line_ids.write({'selected': True})
        return False

    def action_deselect_all_groups(self):
        self.group_line_ids.write({'selected': False})
        return False

    def _get_selected_group_dns(self):
        """선택된 그룹의 DN 목록 반환"""
        return set(self.group_line_ids.filtered('selected').mapped('ldap_dn'))

    # =========================================================================
    # Refresh from LDAP (preserves existing policies)
    # =========================================================================
    def action_refresh_from_ldap(self):
        """
        LDAP에서 최신 데이터를 가져와 위자드 라인 갱신.
        - 새 사용자/그룹: 기본값으로 추가 (user: group policy, group: selected=True)
        - 삭제된 사용자/그룹: 위자드 라인 제거
        - 기존 사용자/그룹: 속성 업데이트, 정책(sync_mode/selected) 유지
        """
        self.ensure_one()

        try:
            user_data, group_data = self.ldap_id._query_ldap_users_and_groups()
        except Exception as e:
            _logger.error("Refresh from LDAP failed: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('LDAP Connection Failed'),
                    'message': str(e),
                    'sticky': True,
                }
            }

        # ── 사용자 라인 갱신 ──
        existing_user_lines = {line.ldap_dn: line for line in self.user_line_ids}
        seen_user_dns = set()

        new_user_lines = []
        for ud in user_data:
            dn = ud['ldap_dn']
            seen_user_dns.add(dn)

            if dn in existing_user_lines:
                # 기존 라인: 속성만 업데이트 (sync_mode 유지)
                existing_user_lines[dn].write({
                    'screen_name': ud['screen_name'],
                    'email': ud['email'],
                    'first_name': ud['first_name'],
                    'last_name': ud['last_name'],
                    'job_title': ud['job_title'],
                    'group_count': ud['group_count'],
                    'member_group_dns': ud['member_group_dns'],
                    'ldap_entry_data': ud['ldap_entry_data'],
                })
            else:
                # 새 사용자: 기본 group policy로 추가
                new_user_lines.append(dict(ud, wizard_id=self.id))

        if new_user_lines:
            self.env['ldap.sync.wizard.user.line'].create(new_user_lines)

        # LDAP에서 삭제된 사용자 라인 제거
        deleted_user_lines = self.user_line_ids.filtered(
            lambda l: l.ldap_dn not in seen_user_dns
        )
        if deleted_user_lines:
            deleted_user_lines.unlink()

        # ── 그룹 라인 갱신 ──
        existing_group_lines = {line.ldap_dn: line for line in self.group_line_ids}
        seen_group_dns = set()

        new_group_lines = []
        for gd in group_data:
            dn = gd['ldap_dn']
            seen_group_dns.add(dn)

            if dn in existing_group_lines:
                # 기존 라인: 속성만 업데이트 (selected 유지)
                existing_group_lines[dn].write({
                    'name': gd['name'],
                    'description': gd['description'],
                    'member_count': gd['member_count'],
                    'sequence': gd['sequence'],
                })
            else:
                # 새 그룹: 기본 selected=True로 추가
                new_group_lines.append(dict(gd, wizard_id=self.id))

        if new_group_lines:
            self.env['ldap.sync.wizard.group.line'].create(new_group_lines)

        # LDAP에서 삭제된 그룹 라인 제거
        deleted_group_lines = self.group_line_ids.filtered(
            lambda l: l.ldap_dn not in seen_group_dns
        )
        if deleted_group_lines:
            deleted_group_lines.unlink()

        _logger.info(
            "Refreshed wizard for %s: %d users (+%d new, -%d removed), %d groups (+%d new, -%d removed)",
            self.ldap_server_name,
            len(user_data), len(new_user_lines), len(deleted_user_lines),
            len(group_data), len(new_group_lines), len(deleted_group_lines),
        )

        return self._reload()

    # =========================================================================
    # Sync (strong binding policy, persistent wizard)
    # =========================================================================
    def action_sync_selected(self):
        """
        강력한 바인딩 정책 동기화:
        - Sync 대상 사용자 → 동기화 + active=True (재활성화)
        - Sync 대상 아닌 AD 사용자 → active=False (아카이브)
        - 선택된 그룹 → 동기화
        - 선택 안 된 AD 그룹 → 멤버십 제거
        위자드 데이터는 유지됨 (persistent)
        """
        self.ensure_one()
        ldap_config = self.ldap_id

        # 동기화 대상 사용자 계산
        selected_group_dns = self._get_selected_group_dns()
        sync_users = self.user_line_ids.filtered(
            lambda u: u._is_sync_target(selected_group_dns)
        )
        non_sync_users = self.user_line_ids - sync_users
        selected_groups = self.group_line_ids.filtered('selected')
        non_selected_groups = self.group_line_ids - selected_groups

        _logger.info(
            "Sync (strong binding): %d/%d users, %d/%d groups",
            len(sync_users), len(self.user_line_ids),
            len(selected_groups), len(self.group_line_ids)
        )

        created_groups = 0
        removed_groups = 0
        synced_users = 0
        archived_users = 0
        error_count = 0

        # ── 1. 선택된 그룹 동기화 ──
        ad_category = self.env.ref(
            'teps_odoo_ldap_connector.module_category_ad_groups',
            raise_if_not_found=False
        )
        for gline in selected_groups:
            try:
                group_id = self.env['res.users'].sudo()._get_or_create_odoo_group(
                    gline.name,
                    gline.ldap_dn,
                    ad_category.id if ad_category else False,
                    True
                )
                if group_id:
                    created_groups += 1
            except Exception as e:
                _logger.error("Error syncing group %s: %s", gline.name, e)
                error_count += 1

        # ── 2. 선택 안 된 AD 그룹: 모든 AD 사용자에서 멤버십 제거 ──
        for gline in non_selected_groups:
            try:
                odoo_group = self.env['res.groups'].sudo().search([
                    ('name', '=ilike', gline.name),
                    ('comment', 'like', '[AD Group]'),
                ], limit=1)
                if odoo_group:
                    ad_users_in_group = self.env['res.users'].sudo().search([
                        ('ldap_id', '=', ldap_config.id),
                        ('group_ids', 'in', [odoo_group.id]),
                    ])
                    if ad_users_in_group:
                        ad_users_in_group.sudo().write({
                            'group_ids': [(3, odoo_group.id)]
                        })
                        removed_groups += 1
                        _logger.info("Removed AD group '%s' from %d users", gline.name, len(ad_users_in_group))
            except Exception as e:
                _logger.error("Error removing group %s: %s", gline.name, e)
                error_count += 1

        # ── 3. 동기화 대상 사용자 동기화 (active=True 보장) ──
        conf = {
            'id': ldap_config.id,
            'ldap_server': ldap_config.ldap_server,
            'ldap_server_port': ldap_config.ldap_server_port,
            'ldap_binddn': ldap_config.ldap_binddn,
            'ldap_password': ldap_config.ldap_password,
            'ldap_filter': ldap_config.user_search_filter or ldap_config.ldap_filter,
            'ldap_base': ldap_config.users_dn or ldap_config.ldap_base,
            'ldap_tls': ldap_config.ldap_tls,
            'user': (ldap_config.user.id,) if ldap_config.user else False,
            'create_user': ldap_config.create_user,
            'company': (ldap_config.company.id, ldap_config.company.name),
        }

        for uline in sync_users:
            try:
                entry_data = json.loads(uline.ldap_entry_data) if uline.ldap_entry_data else {}
                attrs = {}
                for k, v in entry_data.items():
                    attrs[k] = [val.encode('utf-8') if isinstance(val, str) else val for val in v]

                ldap_entry = (uline.ldap_dn, attrs)
                login = uline.screen_name

                if not login:
                    continue

                existing_user = self.env['res.users'].sudo().with_context(active_test=False).search([
                    ('login', '=ilike', login)
                ], limit=1)

                if existing_user:
                    values = ldap_config._map_ldap_attributes(conf, login, ldap_entry)
                    if not existing_user.ldap_id:
                        values['ldap_id'] = ldap_config.id
                        values['ldap_dn'] = uline.ldap_dn
                    if not existing_user.active:
                        values['active'] = True
                        _logger.info("Reactivated user: %s", login)
                    existing_user.write(values)
                    if ldap_config.sync_groups:
                        existing_user._sync_ad_groups_for_user(ldap_config, ldap_entry)
                else:
                    user_id = ldap_config._get_or_create_user(conf, login, ldap_entry)
                    if user_id:
                        _logger.info("Created user via sync wizard: %s", login)

                synced_users += 1
            except Exception as e:
                _logger.error("Error syncing user %s: %s", uline.screen_name, e, exc_info=True)
                error_count += 1

        # ── 4. 동기화 대상이 아닌 AD 사용자 아카이브 ──
        for uline in non_sync_users:
            try:
                login = uline.screen_name
                if not login:
                    continue
                existing_user = self.env['res.users'].sudo().search([
                    ('login', '=ilike', login),
                    ('ldap_id', '=', ldap_config.id),
                ], limit=1)
                if existing_user and existing_user.active:
                    existing_user.write({'active': False})
                    archived_users += 1
                    _logger.info("Archived non-target AD user: %s", login)
            except Exception as e:
                _logger.error("Error archiving user %s: %s", uline.screen_name, e, exc_info=True)
                error_count += 1

        # ── 결과 저장 + 알림 ──
        message = _(
            'Sync: %(users)d synced, %(archived)d archived, '
            '%(groups)d groups, %(removed)d removed, %(errors)d errors',
            users=synced_users, archived=archived_users,
            groups=created_groups, removed=removed_groups, errors=error_count
        )
        _logger.info("Sync wizard result: %s", message)

        # 위자드 상태 업데이트 (persistent)
        self.write({
            'last_sync_date': fields.Datetime.now(),
            'last_sync_status': message,
            'last_sync_user_count': synced_users,
        })

        # LDAP config 상태도 업데이트 (메인 폼에서 볼 수 있도록)
        ldap_config.write({
            'last_sync_date': fields.Datetime.now(),
            'last_sync_status': message,
            'last_sync_user_count': synced_users,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if error_count == 0 else 'warning',
                'title': _('Sync Completed'),
                'message': message,
                'sticky': False,
            }
        }

    # =========================================================================
    # Cron Job
    # =========================================================================
    @api.model
    def _cron_sync_ldap(self):
        """Cron: sync_enabled인 위자드에 대해 refresh → sync 실행"""
        wizards = self.sudo().search([('sync_enabled', '=', True)])
        for wizard in wizards:
            try:
                _logger.info("Cron sync starting for LDAP server: %s", wizard.ldap_server_name)
                wizard.action_refresh_from_ldap()
                wizard.action_sync_selected()
            except Exception as e:
                _logger.error(
                    "Cron LDAP sync failed for server %s: %s",
                    wizard.ldap_server_name, str(e),
                    exc_info=True,
                )


class LdapSyncWizardUserLine(models.Model):
    _name = 'ldap.sync.wizard.user.line'
    _description = 'LDAP Sync Wizard User Line'

    _wizard_dn_unique = models.Constraint(
        'UNIQUE(wizard_id, ldap_dn)',
        'Duplicate user entry in this wizard.',
    )

    wizard_id = fields.Many2one('ldap.sync.wizard', string='Wizard', ondelete='cascade', required=True)
    sync_mode = fields.Selection(
        SYNC_MODE_SELECTION,
        string='Sync',
        default='group',
        required=True,
    )
    is_sync_target = fields.Boolean(
        string='Target',
        compute='_compute_is_sync_target',
        store=True,
    )
    screen_name = fields.Char(string='Screen Name')
    email = fields.Char(string='Email')
    first_name = fields.Char(string='First Name')
    last_name = fields.Char(string='Last Name')
    job_title = fields.Char(string='Job Title')
    group_count = fields.Integer(string='Groups')
    member_group_dns = fields.Text(string='Member Group DNs')
    ldap_dn = fields.Char(string='LDAP DN', required=True)
    ldap_entry_data = fields.Text(string='LDAP Entry Data')
    exists_in_odoo = fields.Boolean(string='Exists', compute='_compute_exists_in_odoo')

    def _is_sync_target(self, selected_group_dns=None):
        """이 사용자가 동기화 대상인지 판정"""
        if self.sync_mode == 'enable':
            return True
        if self.sync_mode == 'disable':
            return False
        if selected_group_dns is None:
            selected_group_dns = self.wizard_id._get_selected_group_dns()
        if not selected_group_dns:
            return False
        user_groups = set(json.loads(self.member_group_dns or '[]'))
        return bool(user_groups & selected_group_dns)

    @api.depends('sync_mode', 'member_group_dns',
                 'wizard_id.group_line_ids.selected')
    def _compute_is_sync_target(self):
        for line in self:
            line.is_sync_target = line._is_sync_target()

    @api.depends('screen_name')
    def _compute_exists_in_odoo(self):
        for line in self:
            if line.screen_name:
                line.exists_in_odoo = bool(self.env['res.users'].sudo().search([
                    ('login', '=ilike', line.screen_name)
                ], limit=1))
            else:
                line.exists_in_odoo = False


class LdapSyncWizardGroupLine(models.Model):
    _name = 'ldap.sync.wizard.group.line'
    _description = 'LDAP Sync Wizard Group Line'

    _wizard_dn_unique = models.Constraint(
        'UNIQUE(wizard_id, ldap_dn)',
        'Duplicate group entry in this wizard.',
    )

    wizard_id = fields.Many2one('ldap.sync.wizard', string='Wizard', ondelete='cascade', required=True)
    selected = fields.Boolean(string='Select', default=True)
    sequence = fields.Integer(string='#')
    name = fields.Char(string='Name')
    description = fields.Char(string='Description')
    member_count = fields.Integer(string='Members')
    ldap_dn = fields.Char(string='LDAP DN', required=True)
    exists_in_odoo = fields.Boolean(string='Exists', compute='_compute_exists_in_odoo')

    @api.depends('name')
    def _compute_exists_in_odoo(self):
        for line in self:
            if line.name:
                line.exists_in_odoo = bool(self.env['res.groups'].sudo().search([
                    ('name', '=ilike', line.name)
                ], limit=1))
            else:
                line.exists_in_odoo = False
