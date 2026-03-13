# -*- coding: utf-8 -*-
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
    # IMPORT - Scheduled Synchronization Settings
    # =========================================================================
    import_enabled = fields.Boolean(
        string='Enable Scheduled Import',
        default=False,
        help='Enable automatic LDAP user import on schedule'
    )

    import_interval = fields.Integer(
        string='Import Interval (minutes)',
        default=60,
        help='How often to run the LDAP import (in minutes). Minimum: 5 minutes.'
    )

    import_on_startup = fields.Boolean(
        string='Import on Startup',
        default=False,
        help='Run LDAP import when Odoo server starts'
    )

    update_existing_users = fields.Boolean(
        string='Update Existing Users',
        default=True,
        help='Update existing Odoo users with LDAP data during import'
    )

    user_deletion_strategy = fields.Selection(
        selection=[
            ('deactivate', 'Deactivate User'),
            ('delete', 'Delete User'),
            ('nothing', 'Keep User'),
        ],
        string='User Deletion Strategy',
        default='deactivate',
        help='What to do when a user is removed from LDAP:\n'
             '- Deactivate: Set user as inactive in Odoo\n'
             '- Delete: Permanently remove user from Odoo\n'
             '- Keep: Do nothing, keep user in Odoo'
    )

    # =========================================================================
    # IMPORT - Sync Status (Read-only)
    # =========================================================================
    last_sync_date = fields.Datetime(
        string='Last Sync Date',
        readonly=True,
        help='Date and time of the last successful synchronization'
    )

    last_sync_status = fields.Char(
        string='Last Sync Status',
        readonly=True,
        help='Status message from the last synchronization'
    )

    last_sync_user_count = fields.Integer(
        string='Last Sync User Count',
        readonly=True,
        help='Number of users synchronized in the last import'
    )

    # =========================================================================
    # Override Methods
    # =========================================================================
    def _get_ldap_dicts(self):
        """
        auth_search_filter 필드를 conf 딕셔너리에 포함하여 반환.
        Odoo 기본 _get_ldap_dicts()는 ldap_filter만 포함하므로 확장 필요.
        """
        configs = super()._get_ldap_dicts()
        if not configs:
            return configs

        # id → conf 매핑
        config_map = {c['id']: c for c in configs}
        records = self.sudo().browse(list(config_map.keys()))
        for record in records:
            if record.id in config_map:
                config_map[record.id]['auth_search_filter'] = record.auth_search_filter or False

        return configs

    def _get_entry(self, conf, login):
        """
        AD Bind 방식 인증용 DN 검색.
        auth_search_filter가 설정된 경우 기본 ldap_filter 대신 사용.

        지원 형식:
        - %(user)s  — sAMAccountName=%(user)s 처럼 named placeholder
        - %s        — 기본 Odoo 방식 (filter_format 사용, 자동 이스케이프)
        auth_search_filter 미설정 시 Odoo 기본 동작(_get_entry) 그대로.
        """
        auth_filter = conf.get('auth_search_filter')
        if not auth_filter:
            return super()._get_entry(conf, login)

        from ldap.filter import escape_filter_chars, filter_format

        if '%(user)s' in auth_filter:
            # named placeholder 형식 — 직접 이스케이프
            escaped_login = escape_filter_chars(login)
            formatted_filter = auth_filter % {'user': escaped_login}
        elif '%s' in auth_filter:
            # positional placeholder — filter_format(이스케이프 내장)
            placeholders = auth_filter.count('%s')
            formatted_filter = filter_format(auth_filter, [login] * placeholders)
        else:
            # 플레이스홀더 없음 (고정 필터) — 그대로 사용
            _logger.warning(
                "auth_search_filter %r contains no placeholder (%%s or %%(user)s). "
                "All users matching this filter will be returned.",
                auth_filter,
            )
            formatted_filter = auth_filter

        _logger.debug(
            "AD bind search: base=%s filter=%s", conf.get('ldap_base'), formatted_filter
        )

        results = self._query(conf, formatted_filter)
        results = [entry for entry in results if entry[0]]

        dn, entry = False, False
        if len(results) == 1:
            dn, _ = entry = results[0]
        elif len(results) > 1:
            _logger.warning(
                "auth_search_filter returned %d results for login %r — expected exactly 1. "
                "Authentication denied.",
                len(results), login,
            )

        return dn, entry

    def _get_or_create_user(self, conf, login, ldap_entry):
        """
        사용자 생성/조회 후 AD 그룹 동기화 수행
        원본 메서드를 오버라이드하여 그룹 동기화 로직 추가
        """
        # polyon_sync context로 사용자 생성 잠금 해제
        user_id = super(ResCompanyLdap, self.with_context(polyon_sync=True))._get_or_create_user(conf, login, ldap_entry)

        if user_id:
            try:
                # LDAP 설정 레코드 조회
                ldap_config = self.sudo().browse(conf['id'])

                # 사용자 레코드 조회
                user = self.env['res.users'].sudo().browse(user_id)

                # LDAP 소스 정보 업데이트 (처음 생성 시 또는 아직 설정되지 않은 경우)
                dn = ldap_entry[0] if ldap_entry else ''
                if not user.ldap_id:
                    user.write({
                        'ldap_id': ldap_config.id,
                        'ldap_dn': dn,
                    })
                    _logger.debug("Set LDAP source for user %s: server=%s", login, ldap_config.ldap_server)

                # AD 그룹 동기화 수행
                if ldap_config.sync_groups:
                    user._sync_ad_groups_for_user(ldap_config, ldap_entry)

                    _logger.info(
                        "AD group sync triggered for user %s (id=%d)",
                        login, user_id
                    )

            except Exception as e:
                # 그룹 동기화 실패해도 로그인은 허용
                _logger.error(
                    "AD group sync failed for user %s: %s",
                    login, str(e),
                    exc_info=True
                )

        return user_id

    def _map_ldap_attributes(self, conf, login, ldap_entry):
        """
        LDAP 엔트리에서 Odoo 사용자 값 매핑
        User Mapping 설정을 사용하여 확장된 속성 매핑
        """
        # 기본 매핑 가져오기
        values = super()._map_ldap_attributes(conf, login, ldap_entry)

        # LDAP 설정 조회
        ldap_config = self.sudo().browse(conf['id'])
        attrs = ldap_entry[1]

        def get_attr(attr_name, default=''):
            """LDAP 속성값 추출 헬퍼"""
            if not attr_name:
                return default
            val = attrs.get(attr_name, [])
            if val:
                v = val[0]
                return v.decode('utf-8') if isinstance(v, bytes) else v
            return default

        # 확장 속성 매핑
        if ldap_config.ldap_attr_fullname:
            fullname = get_attr(ldap_config.ldap_attr_fullname)
            if fullname:
                values['name'] = fullname

        if ldap_config.ldap_attr_email:
            email = get_attr(ldap_config.ldap_attr_email)
            if email:
                values['email'] = email

        # 추가 속성 (Odoo 표준 필드가 있는 경우)
        # Job Title은 hr 모듈이 설치된 경우에만 사용 가능

        return values

    # =========================================================================
    # Actions
    # =========================================================================
    def action_sync_all_users(self):
        """
        수동 동기화: LDAP에서 사용자 가져오기 및 그룹 동기화
        - 새 사용자 생성 (create_user 설정에 따라)
        - 기존 사용자 업데이트
        - AD 그룹 동기화
        """
        self.ensure_one()

        if not self.sync_groups:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Sync Disabled'),
                    'message': _('AD Group synchronization is not enabled for this LDAP server.'),
                    'sticky': False,
                }
            }

        try:
            # _import_ldap_users 호출하여 사용자 가져오기 및 그룹 동기화
            result = self._import_ldap_users()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _('Sync Completed'),
                    'message': result,
                    'sticky': False,
                }
            }

        except Exception as e:
            _logger.error("Sync all users failed: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Sync Failed'),
                    'message': str(e),
                    'sticky': True,
                }
            }

    def action_test_ldap_users(self):
        """
        테스트: LDAP 사용자 목록을 모달로 표시
        """
        self.ensure_one()
        import ldap

        # LDAP 연결 설정
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
            # LDAP 연결
            connection = self._connect(conf)

            # LDAP 바인딩 (인증)
            if self.ldap_binddn and self.ldap_password:
                connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

            # 사용자 검색
            search_filter = self.user_search_filter or self.ldap_filter or '(objectClass=person)'
            search_base = self.users_dn or self.ldap_base

            results = connection.search_st(
                search_base,
                ldap.SCOPE_SUBTREE,
                search_filter,
                timeout=30
            )

            # 위자드 생성
            wizard = self.env['ldap.test.users.wizard'].create({
                'ldap_id': self.id,
            })

            # 사용자 라인 생성 (최대 50명)
            line_vals = []
            for dn, entry in results[:50]:
                if not dn:
                    continue

                def get_attr(attr_name):
                    if not attr_name:
                        return ''
                    val = entry.get(attr_name, [])
                    if val:
                        v = val[0]
                        return v.decode('utf-8') if isinstance(v, bytes) else v
                    return ''

                # 그룹 수 계산
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
        """
        테스트: LDAP 그룹 목록을 모달로 표시
        """
        self.ensure_one()
        import ldap

        try:
            # LDAP 연결
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

            # LDAP 바인딩 (인증)
            if self.ldap_binddn and self.ldap_password:
                connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

            # 그룹 검색
            search_filter = self.group_filter or '(objectClass=group)'
            search_base = self.groups_dn or self.ldap_base

            results = connection.search_st(
                search_base,
                ldap.SCOPE_SUBTREE,
                search_filter,
                timeout=30
            )

            # 위자드 생성
            wizard = self.env['ldap.test.groups.wizard'].create({
                'ldap_id': self.id,
            })

            # 그룹 라인 생성 (최대 50개)
            line_vals = []
            seq = 0
            for dn, entry in results[:50]:
                if not dn:
                    continue

                seq += 1

                def get_attr(attr_name):
                    if not attr_name:
                        return ''
                    val = entry.get(attr_name, [])
                    if val:
                        v = val[0]
                        return v.decode('utf-8') if isinstance(v, bytes) else v
                    return ''

                # CN에서 그룹 이름 추출
                group_name = get_attr('cn') or get_attr('name')

                # 멤버 수 계산
                members = entry.get('member', [])

                line_vals.append({
                    'wizard_id': wizard.id,
                    'sequence': seq,
                    'name': group_name,
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

    # =========================================================================
    # LDAP Import Methods
    # =========================================================================
    @api.model
    def _cron_import_ldap_users(self):
        """
        Cron Job: 모든 활성화된 LDAP 서버에서 사용자 가져오기
        polyon_sync=True context로 실행하여 사용자 생성/수정 잠금 해제
        """
        ldap_configs = self.sudo().search([
            ('import_enabled', '=', True),
        ])

        for config in ldap_configs:
            try:
                config.with_context(polyon_sync=True)._import_ldap_users()
            except Exception as e:
                _logger.error(
                    "LDAP import cron failed for server %s: %s",
                    config.ldap_server, str(e),
                    exc_info=True
                )

    def action_import_users_now(self):
        """
        수동 Import: 현재 LDAP 서버에서 사용자 가져오기
        """
        self.ensure_one()

        if not self.import_enabled:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Import Disabled'),
                    'message': _('Scheduled import is not enabled for this LDAP server.'),
                    'sticky': False,
                }
            }

        try:
            result = self._import_ldap_users()
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _('Import Completed'),
                    'message': result,
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error("Manual import failed: %s", str(e), exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'danger',
                    'title': _('Import Failed'),
                    'message': str(e),
                    'sticky': True,
                }
            }

    def _import_ldap_users(self):
        """
        LDAP에서 사용자 목록 가져와서 Odoo에 동기화
        """
        self.ensure_one()
        import ldap

        _logger.info("Starting LDAP user import from %s", self.ldap_server)

        # LDAP 연결 설정 (auth_ldap 형식에 맞춤)
        conf = {
            'id': self.id,
            'ldap_server': self.ldap_server,
            'ldap_server_port': self.ldap_server_port,
            'ldap_binddn': self.ldap_binddn,
            'ldap_password': self.ldap_password,
            'ldap_filter': self.user_search_filter or self.ldap_filter,
            'ldap_base': self.users_dn or self.ldap_base,
            'ldap_tls': self.ldap_tls,
            'user': (self.user.id,) if self.user else False,  # tuple 형식
            'create_user': self.create_user,
            'company': (self.company.id, self.company.name),  # 필수: company tuple
        }

        # LDAP 연결
        connection = self._connect(conf)

        # LDAP 바인딩 (인증)
        if self.ldap_binddn and self.ldap_password:
            connection.simple_bind_s(self.ldap_binddn, self.ldap_password)

        # 사용자 검색
        search_filter = self.user_search_filter or self.ldap_filter or '(objectClass=person)'
        search_base = self.users_dn or self.ldap_base

        try:
            results = connection.search_st(
                search_base,
                ldap.SCOPE_SUBTREE,
                search_filter,
                timeout=60
            )
        except ldap.LDAPError as e:
            _logger.error("LDAP search failed: %s", str(e))
            raise

        ldap_logins = set()
        created_count = 0
        updated_count = 0
        error_count = 0

        for dn, entry in results:
            if not dn:
                continue

            try:
                # 로그인 속성 추출
                login_attr = self.ldap_attr_login or 'sAMAccountName'
                login_values = entry.get(login_attr, [])
                if not login_values:
                    continue

                login = login_values[0]
                if isinstance(login, bytes):
                    login = login.decode('utf-8')

                login = login.lower()
                ldap_logins.add(login)

                # 기존 사용자 검색
                existing_user = self.env['res.users'].sudo().search([
                    ('login', '=ilike', login)
                ], limit=1)

                if existing_user:
                    if self.update_existing_users:
                        # 기존 사용자 업데이트
                        values = self._map_ldap_attributes(conf, login, (dn, entry))

                        # LDAP 소스 정보도 업데이트 (아직 설정되지 않은 경우)
                        if not existing_user.ldap_id:
                            values['ldap_id'] = self.id
                            values['ldap_dn'] = dn

                        existing_user.write(values)

                        # 그룹 동기화
                        if self.sync_groups:
                            existing_user._sync_ad_groups_for_user(self, (dn, entry))

                        updated_count += 1
                        _logger.debug("Updated user: %s", login)
                else:
                    # 새 사용자 생성
                    if self.create_user:
                        user_id = self._get_or_create_user(conf, login, (dn, entry))
                        if user_id:
                            created_count += 1
                            _logger.debug("Created user: %s", login)

            except Exception as e:
                _logger.error("Error processing LDAP entry %s: %s", dn, str(e))
                error_count += 1

        # 삭제된 사용자 처리
        deleted_count = 0
        if self.user_deletion_strategy != 'nothing':
            deleted_count = self._handle_deleted_users(ldap_logins)

        # 동기화 상태 업데이트
        from odoo.fields import Datetime
        status_msg = _(
            'Created: %(created)d, Updated: %(updated)d, '
            'Removed: %(deleted)d, Errors: %(errors)d',
            created=created_count,
            updated=updated_count,
            deleted=deleted_count,
            errors=error_count
        )

        self.write({
            'last_sync_date': Datetime.now(),
            'last_sync_status': status_msg,
            'last_sync_user_count': created_count + updated_count,
        })

        _logger.info(
            "LDAP import completed for %s: %s",
            self.ldap_server, status_msg
        )

        return status_msg

    def _handle_deleted_users(self, ldap_logins):
        """
        LDAP에서 삭제된 사용자 처리
        ldap_id가 설정된 사용자만 대상 (LDAP에서 가져온 사용자만)
        """
        self.ensure_one()

        # LDAP으로 생성된 사용자 중 LDAP에 없는 사용자 찾기
        # admin 및 템플릿 사용자는 제외
        excluded_logins = ['admin', 'ldap_template']
        if self.user:
            excluded_logins.append(self.user.login)

        # ldap_id가 현재 LDAP 서버인 사용자만 대상 (LDAP에서 가져온 사용자만)
        odoo_users = self.env['res.users'].sudo().search([
            ('active', '=', True),
            ('ldap_id', '=', self.id),  # 이 LDAP 서버에서 가져온 사용자만
            ('login', 'not in', excluded_logins),
        ])

        deleted_count = 0
        for user in odoo_users:
            if user.login.lower() not in ldap_logins:
                if self.user_deletion_strategy == 'deactivate':
                    user.write({'active': False})
                    _logger.info("Deactivated user not in LDAP: %s", user.login)
                    deleted_count += 1
                elif self.user_deletion_strategy == 'delete':
                    _logger.info("Deleting user not in LDAP: %s", user.login)
                    user.unlink()
                    deleted_count += 1

        return deleted_count
