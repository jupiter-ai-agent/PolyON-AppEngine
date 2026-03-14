# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    """사용자 모델 확장 - AD 그룹 동기화 헬퍼 메서드"""
    _inherit = 'res.users'

    # LDAP 소스 추적 필드
    ldap_id = fields.Many2one(
        'res.company.ldap',
        string='LDAP Server',
        readonly=True,
        help='LDAP server that this user was imported from. '
             'Empty for locally-created users.'
    )

    ldap_dn = fields.Char(
        string='LDAP DN',
        readonly=True,
        help='Distinguished Name in LDAP directory'
    )

    is_ldap_user = fields.Boolean(
        string='Is LDAP User',
        compute='_compute_is_ldap_user',
        store=True,
        help='True if this user was imported from LDAP'
    )

    # AD 그룹만 표시하는 computed 필드
    ad_group_ids = fields.Many2many(
        'res.groups',
        string='AD Groups',
        compute='_compute_ad_group_ids',
        help='Groups synchronized from Active Directory'
    )

    @api.depends('ldap_id')
    def _compute_is_ldap_user(self):
        """LDAP 사용자 여부 계산"""
        for user in self:
            user.is_ldap_user = bool(user.ldap_id)

    @api.depends('group_ids')
    def _compute_ad_group_ids(self):
        """사용자의 AD 그룹만 필터링하여 반환"""
        for user in self:
            user.ad_group_ids = user.group_ids.filtered(
                lambda g: g.comment and '[AD Group]' in g.comment
            )

    def _sync_ad_groups_for_user(self, ldap_config, ldap_entry):
        """
        단일 사용자에 대해 AD 그룹 동기화 수행
        res.company.ldap에서 호출됨

        :param ldap_config: res.company.ldap 레코드
        :param ldap_entry: LDAP 엔트리 튜플 (dn, attrs)
        """
        self.ensure_one()

        if not ldap_config.sync_groups:
            return

        _logger.info("Starting AD group sync for user: %s", self.login)

        # 1. LDAP 엔트리에서 memberOf 속성 추출
        dn, attrs = ldap_entry
        group_attr = ldap_config.group_attribute or 'memberOf'
        member_of_list = attrs.get(group_attr, [])

        # bytes를 string으로 변환
        member_of_list = [
            m.decode('utf-8') if isinstance(m, bytes) else m
            for m in member_of_list
        ]

        # 2. AD 그룹 카테고리 조회
        ad_category = self.env.ref(
            'polyon_ldap_connector.module_category_ad_groups',
            raise_if_not_found=False
        )

        # memberOf가 없으면 빈 set으로 처리 (기존 AD 그룹 모두 제거)
        if not member_of_list:
            _logger.info("No memberOf attributes found for user: %s - removing all AD groups", self.login)
            self._update_user_ad_groups(set(), ad_category)
            return

        _logger.debug("Found %d group memberships for user %s", len(member_of_list), self.login)

        # 3. 각 DN에서 CN 추출 및 그룹 처리
        new_group_ids = set()
        for group_dn in member_of_list:
            cn = self._extract_cn_from_dn(group_dn)
            if not cn:
                continue

            # Odoo 그룹 검색 또는 생성
            group_id = self._get_or_create_odoo_group(
                cn,
                group_dn,
                ad_category.id if ad_category else False,
                ldap_config.create_role_per_group
            )
            if group_id:
                new_group_ids.add(group_id)

        # 4. 사용자 그룹 업데이트
        self._update_user_ad_groups(new_group_ids, ad_category)

        _logger.info(
            "AD group sync completed for user %s: %d groups synced",
            self.login, len(new_group_ids)
        )

    def _extract_cn_from_dn(self, dn):
        """
        DN에서 CN 값 추출
        예: 'CN=Sales,OU=Groups,DC=openshift,DC=co,DC=kr' → 'Sales'
        """
        if not dn:
            return None

        for part in dn.split(','):
            part = part.strip()
            if part.upper().startswith('CN='):
                return part[3:]
        return None

    def _get_or_create_odoo_group(self, group_name, source_dn, category_id, auto_create):
        """
        Odoo 그룹 검색 또는 생성
        Liferay _addRole() 패턴 적용

        Note: Odoo 19에서 res.groups.category_id가 privilege_id로 변경됨
              AD 그룹은 카테고리 없이 생성됨
        """
        ResGroups = self.env['res.groups'].sudo()

        # 1. 기존 그룹 검색 (이름으로)
        existing_group = ResGroups.search([
            ('name', '=ilike', group_name)
        ], limit=1)

        if existing_group:
            _logger.debug("Found existing group: %s (id=%d)", group_name, existing_group.id)
            return existing_group.id

        # 2. 자동 생성이 활성화된 경우 새 그룹 생성
        if auto_create:
            try:
                # Odoo 19: category_id 대신 comment에 카테고리 정보 저장
                new_group = ResGroups.create({
                    'name': group_name,
                    'comment': f'[AD Group] Auto-created from Active Directory.\nSource DN: {source_dn}'
                })
                _logger.info("Created new group from AD: %s (id=%d)", group_name, new_group.id)
                return new_group.id
            except Exception as e:
                _logger.error("Failed to create group %s: %s", group_name, str(e))
                return None
        else:
            _logger.debug("Group %s not found and auto_create is disabled", group_name)
            return None

    def _update_user_ad_groups(self, new_group_ids, ad_category):
        """
        사용자의 AD 그룹 관계 업데이트
        Liferay _updateUserGroups() 패턴 적용

        Note: Odoo 19에서 groups_id가 group_ids로 변경됨
              AD 그룹은 comment에 '[AD Group]'으로 식별
        """
        self.ensure_one()

        # AD 그룹 식별: comment에 '[AD Group]' 포함 여부
        current_ad_groups = self.group_ids.filtered(
            lambda g: g.comment and '[AD Group]' in g.comment
        )

        # Command API로 그룹 업데이트
        commands = []

        # 1. 기존 AD 그룹 제거 (새 목록에 없는 것만)
        for group in current_ad_groups:
            if group.id not in new_group_ids:
                commands.append((3, group.id))  # unlink

        # 2. 새 그룹 추가 (현재 없는 것만)
        current_group_ids = set(self.group_ids.ids)
        for gid in new_group_ids:
            if gid not in current_group_ids:
                commands.append((4, gid))  # link

        if commands:
            self.sudo().write({'group_ids': commands})
            _logger.debug(
                "Updated groups for user %s: removed %d, added %d",
                self.login,
                sum(1 for c in commands if c[0] == 3),
                sum(1 for c in commands if c[0] == 4)
            )
