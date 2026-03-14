# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class ResCompanyLdap(models.Model):
    """LDAP 서버 설정 확장 - AD 그룹 동기화 및 사용자 매핑 기능 추가"""
    _inherit = 'res.company.ldap'

    # =========================================================================
    # USERS - Base DN and Search Filters
    # =========================================================================
    users_dn = fields.Char(
        string='Users DN',
        help='Base DN for user searches (e.g., OU=Users,DC=company,DC=com). '
             'If empty, uses the main LDAP Base DN.'
    )

    auth_search_filter = fields.Char(
        string='Authentication Search Filter',
        default='(&(objectClass=person)(userPrincipalName=%(user)s))',
        help='LDAP filter used for user authentication. Use %(user)s as placeholder for login.'
    )

    user_search_filter = fields.Char(
        string='User Search Filter',
        default='(&(objectClass=person)(!(isCriticalSystemObject=TRUE))(!(userPrincipalName=*sys@*)))',
        help='LDAP filter used to search users for bulk import/sync.'
    )

    # =========================================================================
    # USERS - User Mapping (LDAP Attribute → Odoo Field)
    # =========================================================================
    ldap_attr_login = fields.Char(
        string='Screen Name',
        default='sAMAccountName',
        help='LDAP attribute for user login/screen name'
    )

    ldap_attr_lastname = fields.Char(
        string='Last Name',
        default='sn',
        help='LDAP attribute for user last name (surname)'
    )

    ldap_attr_email = fields.Char(
        string='Email Address',
        default='userPrincipalName',
        help='LDAP attribute for user email address'
    )

    ldap_attr_fullname = fields.Char(
        string='Full Name',
        default='displayName',
        help='LDAP attribute for user full name (display name)'
    )

    ldap_attr_firstname = fields.Char(
        string='First Name',
        default='givenName',
        help='LDAP attribute for user first name'
    )

    ldap_attr_jobtitle = fields.Char(
        string='Job Title',
        default='title',
        help='LDAP attribute for user job title'
    )

    ldap_attr_middlename = fields.Char(
        string='Middle Name',
        default='middleName',
        help='LDAP attribute for user middle name'
    )

    ldap_attr_photo = fields.Char(
        string='Portrait',
        default='thumbnailPhoto',
        help='LDAP attribute for user photo/portrait'
    )

    # =========================================================================
    # AD Group Synchronization Settings
    # =========================================================================
    groups_dn = fields.Char(
        string='Groups DN',
        help='Base DN for group searches (e.g., OU=Groups,DC=company,DC=com). '
             'If empty, uses the main LDAP Base DN.'
    )

    sync_groups = fields.Boolean(
        string='Sync AD Groups',
        default=True,
        help='Enable automatic AD group synchronization on user login'
    )

    create_role_per_group = fields.Boolean(
        string='Create Role Per Group',
        default=True,
        help='Automatically create an Odoo role (group) for each AD group. '
             'When enabled, AD groups will be mapped to Odoo groups automatically.'
    )

    group_attribute = fields.Char(
        string='Group',
        default='memberOf',
        help='LDAP attribute containing group membership (typically memberOf)'
    )

    group_filter = fields.Char(
        string='Group Filter',
        default='(objectClass=group)',
        help='LDAP filter for group search (used for manual sync)'
    )

    # =========================================================================
    # Sync Status (Read-only, updated by Sync Wizard)
    # =========================================================================
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
        readonly=True,
    )

    last_sync_status = fields.Char(
        string='Last Sync Status',
        readonly=True,
    )

    last_sync_user_count = fields.Integer(
        string='Last Sync User Count',
        readonly=True,
    )

    # =========================================================================
    # Override Methods
    # =========================================================================
    def _get_or_create_user(self, conf, login, ldap_entry):
        """
        사용자 생성/조회 후 AD 그룹 동기화 수행
        원본 메서드를 오버라이드하여 그룹 동기화 로직 추가
        """
        user_id = super()._get_or_create_user(conf, login, ldap_entry)

        if user_id:
            try:
                ldap_config = self.sudo().browse(conf['id'])
                user = self.env['res.users'].sudo().browse(user_id)

                dn = ldap_entry[0] if ldap_entry else ''
                if not user.ldap_id:
                    user.write({
                        'ldap_id': ldap_config.id,
                        'ldap_dn': dn,
                    })

                if ldap_config.sync_groups:
                    user._sync_ad_groups_for_user(ldap_config, ldap_entry)
                    _logger.info("AD group sync triggered for user %s (id=%d)", login, user_id)

            except Exception as e:
                _logger.error("AD group sync failed for user %s: %s", login, str(e), exc_info=True)

        return user_id

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        """LDAP 엔트리에서 Odoo 사용자 값 매핑"""
        values = super()._map_ldap_attributes(conf, login, ldap_entry)

        ldap_config = self.sudo().browse(conf['id'])
        attrs = ldap_entry[1]

        def get_attr(attr_name, default=''):
            if not attr_name:
                return default
            val = attrs.get(attr_name, [])
            if val:
                v = val[0]
                return v.decode('utf-8') if isinstance(v, bytes) else v
            return default

        if ldap_config.ldap_attr_fullname:
            fullname = get_attr(ldap_config.ldap_attr_fullname)
            if fullname:
                values['name'] = fullname

        if ldap_config.ldap_attr_email:
            email = get_attr(ldap_config.ldap_attr_email)
            if email:
                values['email'] = email

        return values

    # =========================================================================
    # LDAP Query Helper (used by Sync Wizard)
    # =========================================================================
    def _query_ldap_users_and_groups(self):
        """
        LDAP 서버에서 사용자와 그룹 조회.
        Returns: (user_data_list, group_data_list)
        - user_data_list: [{'screen_name', 'email', ..., 'ldap_dn', 'ldap_entry_data', 'member_group_dns'}, ...]
        - group_data_list: [{'name', 'description', 'member_count', 'ldap_dn'}, ...]
        """
        self.ensure_one()
        import ldap as ldap_lib

        conf = {
            'id': self.id,
            'ldap_server': self.ldap_server,
            'ldap_server_port': self.ldap_server_port,
            'ldap_binddn': self.ldap_binddn,
            'ldap_password': self.ldap_password,
            'ldap_base': self.ldap_base,
            'ldap_tls': self.ldap_tls,
        }
        connection = self._connect(conf)
        if self.ldap_binddn and self.ldap_password:
            connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

        # ── 사용자 검색 ──
        user_filter = self.user_search_filter or self.ldap_filter or '(objectClass=person)'
        user_base = self.users_dn or self.ldap_base
        user_results = connection.search_st(user_base, ldap_lib.SCOPE_SUBTREE, user_filter, timeout=30)

        user_data_list = []
        for dn, entry in user_results:
            if not dn:
                continue

            def _get_attr(attr_name, e=entry):
                if not attr_name:
                    return ''
                val = e.get(attr_name, [])
                if val:
                    v = val[0]
                    return v.decode('utf-8') if isinstance(v, bytes) else v
                return ''

            # LDAP entry를 JSON으로 직렬화
            serialized = {}
            for k, v in entry.items():
                serialized[k] = [
                    val.decode('utf-8', errors='replace') if isinstance(val, bytes) else str(val)
                    for val in v
                ]

            group_attr = self.group_attribute or 'memberOf'
            groups = entry.get(group_attr, [])
            group_dns = [
                g.decode('utf-8') if isinstance(g, bytes) else g
                for g in groups
            ]

            user_data_list.append({
                'screen_name': _get_attr(self.ldap_attr_login or 'sAMAccountName'),
                'email': _get_attr(self.ldap_attr_email or 'userPrincipalName'),
                'first_name': _get_attr(self.ldap_attr_firstname or 'givenName'),
                'last_name': _get_attr(self.ldap_attr_lastname or 'sn'),
                'job_title': _get_attr(self.ldap_attr_jobtitle or 'title'),
                'group_count': len(groups),
                'member_group_dns': json.dumps(group_dns),
                'ldap_dn': dn,
                'ldap_entry_data': json.dumps(serialized, ensure_ascii=False),
            })

        # ── 그룹 검색 ──
        group_filter_str = self.group_filter or '(objectClass=group)'
        group_base = self.groups_dn or self.ldap_base
        group_results = connection.search_st(group_base, ldap_lib.SCOPE_SUBTREE, group_filter_str, timeout=30)

        group_data_list = []
        seq = 0
        for dn, entry in group_results:
            if not dn:
                continue
            seq += 1

            def _get_attr(attr_name, e=entry):
                if not attr_name:
                    return ''
                val = e.get(attr_name, [])
                if val:
                    v = val[0]
                    return v.decode('utf-8') if isinstance(v, bytes) else v
                return ''

            members = entry.get('member', [])
            group_data_list.append({
                'sequence': seq,
                'name': _get_attr('cn') or _get_attr('name'),
                'description': _get_attr('description'),
                'member_count': len(members),
                'ldap_dn': dn,
            })

        return user_data_list, group_data_list

    # =========================================================================
    # Actions
    # =========================================================================
    def action_open_sync_wizard(self):
        """Sync Wizard 열기 (기존 위자드 있으면 재사용, 없으면 LDAP 조회 후 생성)"""
        self.ensure_one()

        # 기존 위자드가 있으면 그대로 열기 (사용자 선택 상태 유지)
        existing_wizard = self.env['ldap.sync.wizard'].sudo().search([
            ('ldap_id', '=', self.id)
        ], limit=1)
        if existing_wizard:
            return {
                'name': _('Sync LDAP Users & Groups'),
                'type': 'ir.actions.act_window',
                'res_model': 'ldap.sync.wizard',
                'res_id': existing_wizard.id,
                'view_mode': 'form',
                'target': 'current',
            }

        try:
            user_data, group_data = self._query_ldap_users_and_groups()

            wizard = self.env['ldap.sync.wizard'].create({'ldap_id': self.id})

            if user_data:
                self.env['ldap.sync.wizard.user.line'].create([
                    dict(d, wizard_id=wizard.id) for d in user_data
                ])

            if group_data:
                self.env['ldap.sync.wizard.group.line'].create([
                    dict(d, wizard_id=wizard.id) for d in group_data
                ])

            return {
                'name': _('Sync LDAP Users & Groups'),
                'type': 'ir.actions.act_window',
                'res_model': 'ldap.sync.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'current',
            }

        except Exception as e:
            _logger.error("Open sync wizard failed: %s", str(e), exc_info=True)
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

    def action_test_ldap_users(self):
        """테스트: LDAP 사용자 목록을 모달로 표시"""
        self.ensure_one()
        import ldap

        conf = {
            'id': self.id,
            'ldap_server': self.ldap_server,
            'ldap_server_port': self.ldap_server_port,
            'ldap_binddn': self.ldap_binddn,
            'ldap_password': self.ldap_password,
            'ldap_filter': self.user_search_filter or self.ldap_filter,
            'ldap_base': self.users_dn or self.ldap_base,
            'ldap_tls': self.ldap_tls,
        }

        try:
            connection = self._connect(conf)
            if self.ldap_binddn and self.ldap_password:
                connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

            search_filter = self.user_search_filter or self.ldap_filter or '(objectClass=person)'
            search_base = self.users_dn or self.ldap_base

            results = connection.search_st(search_base, ldap.SCOPE_SUBTREE, search_filter, timeout=30)

            wizard = self.env['ldap.test.users.wizard'].create({'ldap_id': self.id})

            line_vals = []
            for dn, entry in results[:50]:
                if not dn:
                    continue

                def get_attr(attr_name, e=entry):
                    if not attr_name:
                        return ''
                    val = e.get(attr_name, [])
                    if val:
                        v = val[0]
                        return v.decode('utf-8') if isinstance(v, bytes) else v
                    return ''

                group_attr = self.group_attribute or 'memberOf'
                groups = entry.get(group_attr, [])

                line_vals.append({
                    'wizard_id': wizard.id,
                    'screen_name': get_attr(self.ldap_attr_login or 'sAMAccountName'),
                    'email': get_attr(self.ldap_attr_email or 'userPrincipalName'),
                    'first_name': get_attr(self.ldap_attr_firstname or 'givenName'),
                    'last_name': get_attr(self.ldap_attr_lastname or 'sn'),
                    'job_title': get_attr(self.ldap_attr_jobtitle or 'title'),
                    'group_count': len(groups),
                })

            self.env['ldap.test.users.wizard.line'].create(line_vals)

            return {
                'name': _('LDAP'),
                'type': 'ir.actions.act_window',
                'res_model': 'ldap.test.users.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
                'context': {'dialog_size': 'extra-large'},
            }

        except Exception as e:
            _logger.error("Test LDAP Users failed: %s", str(e), exc_info=True)
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

    def action_test_ldap_groups(self):
        """테스트: LDAP 그룹 목록을 모달로 표시"""
        self.ensure_one()
        import ldap

        try:
            conf = {
                'id': self.id,
                'ldap_server': self.ldap_server,
                'ldap_server_port': self.ldap_server_port,
                'ldap_binddn': self.ldap_binddn,
                'ldap_password': self.ldap_password,
                'ldap_base': self.groups_dn or self.ldap_base,
                'ldap_tls': self.ldap_tls,
            }

            connection = self._connect(conf)
            if self.ldap_binddn and self.ldap_password:
                connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

            search_filter = self.group_filter or '(objectClass=group)'
            search_base = self.groups_dn or self.ldap_base

            results = connection.search_st(search_base, ldap.SCOPE_SUBTREE, search_filter, timeout=30)

            wizard = self.env['ldap.test.groups.wizard'].create({'ldap_id': self.id})

            line_vals = []
            seq = 0
            for dn, entry in results[:50]:
                if not dn:
                    continue
                seq += 1

                def get_attr(attr_name, e=entry):
                    if not attr_name:
                        return ''
                    val = e.get(attr_name, [])
                    if val:
                        v = val[0]
                        return v.decode('utf-8') if isinstance(v, bytes) else v
                    return ''

                members = entry.get('member', [])
                line_vals.append({
                    'wizard_id': wizard.id,
                    'sequence': seq,
                    'name': get_attr('cn') or get_attr('name'),
                    'description': get_attr('description'),
                    'member_count': len(members),
                })

            self.env['ldap.test.groups.wizard.line'].create(line_vals)

            return {
                'name': _('LDAP'),
                'type': 'ir.actions.act_window',
                'res_model': 'ldap.test.groups.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
                'context': {'dialog_size': 'extra-large'},
            }

        except Exception as e:
            _logger.error("Test LDAP Groups failed: %s", str(e), exc_info=True)
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
