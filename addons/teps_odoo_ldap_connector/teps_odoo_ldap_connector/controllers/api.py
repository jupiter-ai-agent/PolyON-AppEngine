# -*- coding: utf-8 -*-
import json
import logging
import functools

from odoo import http, fields
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


def _json_response(data, status=200):
    """JSON 응답 헬퍼"""
    body = json.dumps(data, ensure_ascii=False, default=str)
    return Response(
        body,
        status=status,
        content_type='application/json; charset=utf-8',
    )


def _error_response(message, status=400):
    """에러 응답 헬퍼"""
    return _json_response({'error': message}, status=status)


def api_key_required(func):
    """
    API Key 인증 데코레이터.
    헤더에서 X-API-Key 또는 Authorization: Bearer <key> 를 확인하여
    Odoo의 res.users.apikeys 테이블에서 유효성 검증.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # API Key 추출
        api_key = request.httprequest.headers.get('X-API-Key')
        if not api_key:
            auth_header = request.httprequest.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                api_key = auth_header[7:].strip()

        if not api_key:
            return _error_response('API key required. Use X-API-Key header or Authorization: Bearer <key>', 401)

        # Odoo API Key 검증
        try:
            uid = request.env['res.users.apikeys']._check_credentials(
                scope='rpc', key=api_key
            )
            if not uid:
                return _error_response('Invalid API key', 401)

            # 관리자 권한 확인
            user = request.env['res.users'].sudo().browse(uid)
            if not user.has_group('base.group_system'):
                return _error_response('Insufficient permissions. Admin access required.', 403)

            # 인증된 사용자 환경으로 전환
            request.update_env(user=uid)

        except Exception as e:
            _logger.warning("API key validation failed: %s", str(e))
            return _error_response('Invalid API key', 401)

        return func(*args, **kwargs)
    return wrapper


def _get_wizard(wizard_id=None):
    """위자드 조회 헬퍼"""
    domain = []
    if wizard_id:
        domain = [('id', '=', int(wizard_id))]
    wizards = request.env['ldap.sync.wizard'].sudo().search(domain, limit=1)
    return wizards


class LdapSyncApiController(http.Controller):
    """
    LDAP Sync Wizard REST API Controller

    Base URL: /api/v1/ldap-sync
    Authentication: API Key (X-API-Key header or Authorization: Bearer <key>)
    """

    # =====================================================================
    # Wizard (Overview)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/wizards', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def list_wizards(self, **kwargs):
        """모든 LDAP Sync 위자드 목록 조회"""
        wizards = request.env['ldap.sync.wizard'].sudo().search([])
        result = []
        for w in wizards:
            result.append({
                'id': w.id,
                'ldap_server': w.ldap_server_name,
                'user_count': w.user_count,
                'group_count': w.group_count,
                'sync_user_count': w.sync_user_count,
                'selected_group_count': w.selected_group_count,
                'sync_enabled': w.sync_enabled,
                'sync_interval': w.sync_interval,
                'last_sync_date': w.last_sync_date,
                'last_sync_status': w.last_sync_status,
                'last_sync_user_count': w.last_sync_user_count,
            })
        return _json_response({'wizards': result})

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def get_wizard(self, wizard_id, **kwargs):
        """특정 위자드 상세 조회"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        return _json_response({
            'id': wizard.id,
            'ldap_server': wizard.ldap_server_name,
            'user_count': wizard.user_count,
            'group_count': wizard.group_count,
            'sync_user_count': wizard.sync_user_count,
            'selected_group_count': wizard.selected_group_count,
            'sync_enabled': wizard.sync_enabled,
            'sync_interval': wizard.sync_interval,
            'last_sync_date': wizard.last_sync_date,
            'last_sync_status': wizard.last_sync_status,
            'last_sync_user_count': wizard.last_sync_user_count,
        })

    # =====================================================================
    # Groups (Tab 1)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/groups', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def list_groups(self, wizard_id, **kwargs):
        """위자드의 AD 그룹 목록 조회"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        groups = []
        for g in wizard.group_line_ids:
            groups.append({
                'id': g.id,
                'selected': g.selected,
                'sequence': g.sequence,
                'name': g.name,
                'description': g.description,
                'member_count': g.member_count,
                'ldap_dn': g.ldap_dn,
                'exists_in_odoo': g.exists_in_odoo,
            })

        return _json_response({
            'wizard_id': wizard.id,
            'total': len(groups),
            'selected': len([g for g in groups if g['selected']]),
            'groups': groups,
        })

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/groups', type='http', auth='none',
                methods=['PUT'], csrf=False)
    @api_key_required
    def update_groups(self, wizard_id, **kwargs):
        """
        AD 그룹 선택 상태 변경

        JSON Body:
            {"groups": [{"id": 1, "selected": true}, {"id": 2, "selected": false}]}
        or:
            {"select_all": true}
        or:
            {"deselect_all": true}
        """
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            data = json.loads(request.httprequest.data)
        except (json.JSONDecodeError, TypeError):
            return _error_response('Invalid JSON body')

        if data.get('select_all'):
            wizard.action_select_all_groups()
            return _json_response({'message': 'All groups selected', 'selected_count': wizard.group_count})

        if data.get('deselect_all'):
            wizard.action_deselect_all_groups()
            return _json_response({'message': 'All groups deselected', 'selected_count': 0})

        groups_data = data.get('groups', [])
        if not groups_data:
            return _error_response('No groups data provided. Use {"groups": [{"id": 1, "selected": true}]}')

        updated = 0
        for gd in groups_data:
            gid = gd.get('id')
            selected = gd.get('selected')
            if gid is None or selected is None:
                continue
            line = wizard.group_line_ids.filtered(lambda l: l.id == gid)
            if line:
                line.write({'selected': bool(selected)})
                updated += 1

        return _json_response({
            'message': f'{updated} groups updated',
            'selected_count': wizard.selected_group_count,
        })

    # =====================================================================
    # Users (Tab 2)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/users', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def list_users(self, wizard_id, **kwargs):
        """위자드의 AD 사용자 목록 조회"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        users = []
        for u in wizard.user_line_ids:
            users.append({
                'id': u.id,
                'sync_mode': u.sync_mode,
                'is_sync_target': u.is_sync_target,
                'screen_name': u.screen_name,
                'email': u.email,
                'first_name': u.first_name,
                'last_name': u.last_name,
                'job_title': u.job_title,
                'group_count': u.group_count,
                'ldap_dn': u.ldap_dn,
                'exists_in_odoo': u.exists_in_odoo,
            })

        return _json_response({
            'wizard_id': wizard.id,
            'total': len(users),
            'sync_targets': len([u for u in users if u['is_sync_target']]),
            'users': users,
        })

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/users', type='http', auth='none',
                methods=['PUT'], csrf=False)
    @api_key_required
    def update_users(self, wizard_id, **kwargs):
        """
        사용자 동기화 정책 변경

        JSON Body:
            {"users": [{"id": 1, "sync_mode": "enable"}, {"id": 2, "sync_mode": "disable"}]}
        or:
            {"set_all": "group"}     (group | enable | disable)
        """
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            data = json.loads(request.httprequest.data)
        except (json.JSONDecodeError, TypeError):
            return _error_response('Invalid JSON body')

        valid_modes = ('group', 'enable', 'disable')

        set_all = data.get('set_all')
        if set_all:
            if set_all not in valid_modes:
                return _error_response(f'Invalid mode. Use one of: {valid_modes}')
            wizard.user_line_ids.write({'sync_mode': set_all})
            return _json_response({
                'message': f'All users set to {set_all}',
                'sync_targets': wizard.sync_user_count,
            })

        users_data = data.get('users', [])
        if not users_data:
            return _error_response('No users data provided. Use {"users": [{"id": 1, "sync_mode": "enable"}]}')

        updated = 0
        errors = []
        for ud in users_data:
            uid = ud.get('id')
            mode = ud.get('sync_mode')
            if uid is None or mode is None:
                continue
            if mode not in valid_modes:
                errors.append(f'Invalid sync_mode "{mode}" for user id {uid}')
                continue
            line = wizard.user_line_ids.filtered(lambda l: l.id == uid)
            if line:
                line.write({'sync_mode': mode})
                updated += 1

        result = {
            'message': f'{updated} users updated',
            'sync_targets': wizard.sync_user_count,
        }
        if errors:
            result['errors'] = errors
        return _json_response(result)

    # =====================================================================
    # Schedule (Tab 3)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/schedule', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def get_schedule(self, wizard_id, **kwargs):
        """스케줄 설정 조회"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        return _json_response({
            'wizard_id': wizard.id,
            'sync_enabled': wizard.sync_enabled,
            'sync_interval': wizard.sync_interval,
            'last_sync_date': wizard.last_sync_date,
            'last_sync_status': wizard.last_sync_status,
            'last_sync_user_count': wizard.last_sync_user_count,
        })

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/schedule', type='http', auth='none',
                methods=['PUT'], csrf=False)
    @api_key_required
    def update_schedule(self, wizard_id, **kwargs):
        """
        스케줄 설정 변경

        JSON Body:
            {"sync_enabled": true, "sync_interval": 5}
        """
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            data = json.loads(request.httprequest.data)
        except (json.JSONDecodeError, TypeError):
            return _error_response('Invalid JSON body')

        vals = {}
        if 'sync_enabled' in data:
            vals['sync_enabled'] = bool(data['sync_enabled'])
        if 'sync_interval' in data:
            interval = int(data['sync_interval'])
            if interval < 1:
                return _error_response('sync_interval must be >= 1 minute')
            vals['sync_interval'] = interval

        if not vals:
            return _error_response('No valid fields provided. Use sync_enabled and/or sync_interval.')

        wizard.write(vals)

        return _json_response({
            'message': 'Schedule updated',
            'sync_enabled': wizard.sync_enabled,
            'sync_interval': wizard.sync_interval,
        })

    # =====================================================================
    # Actions (Refresh / Sync Now)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/refresh', type='http', auth='none',
                methods=['POST'], csrf=False)
    @api_key_required
    def action_refresh(self, wizard_id, **kwargs):
        """LDAP에서 최신 데이터 갱신 (정책 유지)"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            wizard.action_refresh_from_ldap()
        except Exception as e:
            _logger.error("API refresh failed: %s", str(e), exc_info=True)
            return _error_response(f'Refresh failed: {str(e)}', 500)

        return _json_response({
            'message': 'Refresh completed',
            'user_count': wizard.user_count,
            'group_count': wizard.group_count,
        })

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/sync', type='http', auth='none',
                methods=['POST'], csrf=False)
    @api_key_required
    def action_sync(self, wizard_id, **kwargs):
        """강력한 바인딩 정책으로 동기화 실행 (Sync Now와 동일)"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            wizard.action_sync_selected()
        except Exception as e:
            _logger.error("API sync failed: %s", str(e), exc_info=True)
            return _error_response(f'Sync failed: {str(e)}', 500)

        return _json_response({
            'message': 'Sync completed',
            'last_sync_date': wizard.last_sync_date,
            'last_sync_status': wizard.last_sync_status,
            'last_sync_user_count': wizard.last_sync_user_count,
        })

    @http.route('/api/v1/ldap-sync/wizards/<int:wizard_id>/refresh-and-sync', type='http', auth='none',
                methods=['POST'], csrf=False)
    @api_key_required
    def action_refresh_and_sync(self, wizard_id, **kwargs):
        """Refresh + Sync 한 번에 실행 (cron과 동일)"""
        wizard = _get_wizard(wizard_id)
        if not wizard:
            return _error_response('Wizard not found', 404)

        try:
            wizard.action_refresh_from_ldap()
            wizard.action_sync_selected()
        except Exception as e:
            _logger.error("API refresh-and-sync failed: %s", str(e), exc_info=True)
            return _error_response(f'Refresh and sync failed: {str(e)}', 500)

        return _json_response({
            'message': 'Refresh and sync completed',
            'user_count': wizard.user_count,
            'group_count': wizard.group_count,
            'last_sync_date': wizard.last_sync_date,
            'last_sync_status': wizard.last_sync_status,
            'last_sync_user_count': wizard.last_sync_user_count,
        })

    # =====================================================================
    # Status (Quick overview)
    # =====================================================================

    @http.route('/api/v1/ldap-sync/status', type='http', auth='none',
                methods=['GET'], csrf=False)
    @api_key_required
    def get_status(self, **kwargs):
        """전체 LDAP 동기화 상태 요약"""
        wizards = request.env['ldap.sync.wizard'].sudo().search([])
        result = []
        for w in wizards:
            result.append({
                'id': w.id,
                'ldap_server': w.ldap_server_name,
                'sync_enabled': w.sync_enabled,
                'sync_interval': w.sync_interval,
                'total_users': w.user_count,
                'sync_targets': w.sync_user_count,
                'total_groups': w.group_count,
                'selected_groups': w.selected_group_count,
                'last_sync_date': w.last_sync_date,
                'last_sync_status': w.last_sync_status,
            })
        return _json_response({'status': result})
