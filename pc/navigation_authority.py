"""Navigation ownership layered on the existing RobotLink/App authority.

Navigation never opens a second socket and never performs TAKE or ARM. It can
only use an already active manual control session, and every primitive is
bounded by a task lease and a command id. A browser STOP, DISARM or disconnect
revokes this authority immediately.
"""
import re
import time


KEYS = {
    'forward': 'w', 'backward': 's', 'strafe_left': 'j',
    'strafe_right': 'l', 'turn_left': 'z', 'turn_right': 'c',
}
SAFE_PRIMITIVES = set(KEYS)
TASK_RE = re.compile(r'[A-Za-z0-9_.:-]{1,96}\Z')
COMMAND_RE = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')


class NavigationAuthority:
    def __init__(self, app, token, *, lease_s=.9, primitive_ttl_s=.7):
        self.app = app
        self.token = token if isinstance(token, str) else ''
        self.lease_s = float(lease_s)
        self.primitive_ttl_s = float(primitive_ttl_s)
        self.task_id = ''
        self.lease_until = 0.
        self.last_command_id = ''
        self.active_primitive = ''
        self.revocation_reason = ''

    def _expire_locked(self, now=None):
        now = time.monotonic() if now is None else now
        if self.task_id and now >= self.lease_until:
            try:
                self.app.link.submit('stop')
            except (ValueError, OSError):
                pass
            self.revocation_reason = 'navigation_lease_expired'
            self.task_id = ''
            self.lease_until = 0.
            self.last_command_id = ''
            self.active_primitive = ''
            if self.app.owner == '__navigation__':
                self.app.owner = ''
                self.app.owner_until = 0.

    def _require_token(self, token):
        if not self.token or not isinstance(token, str) or token != self.token:
            raise PermissionError('navigation_token_rejected')

    def _require_task(self, task_id):
        if not isinstance(task_id, str) or not TASK_RE.fullmatch(task_id):
            raise ValueError('navigation_task_id_invalid')

    def _ready(self):
        state = self.app.link.snapshot()
        robot = state.get('robot') or {}
        if (state.get('connected') is not True or state.get('robot_fresh') is not True
                or robot.get('control_active') is not True or robot.get('armed') is not True):
            raise PermissionError('navigation_control_session_not_ready')

    def authorize(self, task_id, token):
        with self.app.lock:
            self._expire_locked()
            self._require_token(token)
            self._require_task(task_id)
            if self.app.owner and self.app.owner != '__navigation__' and time.monotonic() < self.app.owner_until:
                raise PermissionError('navigation_authority_conflict')
            self._ready()
            self.task_id = task_id
            self.lease_until = time.monotonic() + self.lease_s
            self.last_command_id = ''
            self.active_primitive = ''
            self.revocation_reason = ''
            self.app.owner = '__navigation__'
            self.app.owner_until = self.lease_until
            return self.snapshot()

    def command(self, task_id, token, command_id, primitive, ttl_s=None):
        with self.app.lock:
            now = time.monotonic()
            self._expire_locked(now)
            self._require_token(token)
            if task_id != self.task_id or now >= self.lease_until:
                raise PermissionError('navigation_lease_invalid')
            if not isinstance(command_id, str) or not COMMAND_RE.fullmatch(command_id):
                raise ValueError('navigation_command_id_invalid')
            if command_id == self.last_command_id:
                raise ValueError('navigation_duplicate_command_id')
            if primitive not in SAFE_PRIMITIVES:
                raise ValueError('navigation_primitive_invalid')
            self._ready()
            ttl = self.primitive_ttl_s if ttl_s is None else float(ttl_s)
            if not .05 <= ttl <= self.primitive_ttl_s:
                raise ValueError('navigation_primitive_ttl_invalid')
            # RobotLink is the only transport owner. This heartbeat is one
            # axis and is bounded by the receiver's own TTL.
            self.app.link.submit('heartbeat', KEYS[primitive])
            self.last_command_id = command_id
            self.active_primitive = primitive
            self.lease_until = now + self.lease_s
            self.app.owner_until = self.lease_until
            return {'accepted': True, 'task_id': task_id, 'command_id': command_id,
                    'primitive': primitive, 'expires_in_s': ttl}

    def stop(self, task_id, token, reason='navigation_stop'):
        with self.app.lock:
            self._require_token(token)
            if task_id and task_id != self.task_id:
                raise PermissionError('navigation_lease_invalid')
            self.app.link.submit('stop')
            self.revoke_locked(reason)
            return {'accepted': True, 'primitive': 'stop', 'reason': reason}

    def release(self, task_id, token):
        with self.app.lock:
            self._require_token(token)
            if task_id and task_id != self.task_id:
                raise PermissionError('navigation_lease_invalid')
            self.app.link.submit('stop')
            try:
                self.app.link.submit('release')
            finally:
                self.revoke_locked('navigation_release')
            return {'accepted': True, 'released': True}

    def revoke_locked(self, reason):
        self.task_id = ''
        self.lease_until = 0.
        self.last_command_id = ''
        self.active_primitive = ''
        self.revocation_reason = reason
        if self.app.owner == '__navigation__':
            self.app.owner = ''
            self.app.owner_until = 0.

    def revoke(self, reason):
        with self.app.lock:
            self.revoke_locked(reason)

    def snapshot(self):
        self._expire_locked()
        remaining = max(0., self.lease_until - time.monotonic()) if self.task_id else 0.
        return {'active': bool(self.task_id), 'task_id': self.task_id or None,
                'active_primitive': self.active_primitive or None,
                'last_command_id': self.last_command_id or None,
                'lease_remaining_s': remaining,
                'revocation_reason': self.revocation_reason or None}
