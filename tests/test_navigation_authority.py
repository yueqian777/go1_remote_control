import pathlib
import sys
import time
import unittest
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pc'))
from server import App, make_handler


class FakeLink:
    def __init__(self):
        self.calls = []
        self.connected = True
        self.robot = {'control_active': True, 'armed': True, 'health': 'OK'}

    def snapshot(self):
        return {'connected': self.connected, 'robot_fresh': True, 'robot': dict(self.robot)}

    def submit(self, action, key='', **kwargs):
        self.calls.append((action, key, kwargs))


class NavigationAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.app = App({'host': '127.0.0.1', 'port': 8765, 'token': '1' * 64,
                        'navigation_token': 'nav-secret', 'simulation': True}, 8099)
        self.app.link = FakeLink()

    def test_navigation_reuses_same_link_and_never_takes_or_arms(self):
        self.app.navigation.authorize('task-1', 'nav-secret')
        result = self.app.navigation.command('task-1', 'nav-secret', 'cmd-1', 'forward')
        self.assertTrue(result['accepted'])
        self.assertEqual(self.app.link.calls, [('heartbeat', 'w', {})])
        with self.assertRaisesRegex(ValueError, 'duplicate_command_id'):
            self.app.navigation.command('task-1', 'nav-secret', 'cmd-1', 'forward')

    def test_manual_stop_revokes_navigation_lease(self):
        self.app.navigation.authorize('task-1', 'nav-secret')
        self.app.navigation.command('task-1', 'nav-secret', 'cmd-1', 'turn_left')
        body = {'action': 'stop', 'browser': 'a' * 32, 'seq': 1, 'tick': 0}
        self.app.control(body)
        self.assertFalse(self.app.navigation.snapshot()['active'])
        self.assertEqual(self.app.link.calls[-1][0], 'stop')

    def test_lease_expiry_requests_stop_and_clears_owner(self):
        self.app.navigation.authorize('task-1', 'nav-secret')
        self.app.navigation.lease_until = time.monotonic() - 1
        state = self.app.navigation.snapshot()
        self.assertFalse(state['active'])
        self.assertEqual(self.app.link.calls[-1][0], 'stop')

    def test_missing_navigation_token_does_not_enable_feature(self):
        app = App({'host': '127.0.0.1', 'port': 8765, 'token': '1' * 64,
                   'simulation': True}, 8099)
        app.link = FakeLink()
        with self.assertRaises(PermissionError):
            app.navigation.authorize('task-1', 'anything')

    def test_loopback_http_exposes_navigation_lease_without_new_transport(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.app.port = server.server_port
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            headers = {'Origin': base, 'X-Go1-Local-Token': self.app.token,
                       'X-Go1-Navigation-Token': 'nav-secret',
                       'Content-Type': 'application/json'}
            body = json.dumps({'task_id': 'task-http'}).encode()
            with urllib.request.urlopen(urllib.request.Request(
                    base + '/api/navigation/authorize', body, headers)) as response:
                self.assertTrue(json.load(response)['active'])
            body = json.dumps({'task_id': 'task-http', 'command_id': 'cmd-http',
                               'primitive': 'forward'}).encode()
            with urllib.request.urlopen(urllib.request.Request(
                    base + '/api/navigation/command', body, headers)) as response:
                self.assertTrue(json.load(response)['accepted'])
            self.assertEqual([call[0] for call in self.app.link.calls], ['heartbeat'])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
