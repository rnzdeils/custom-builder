import importlib.util
import io
import json
import socket
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'doctor.py'
spec = importlib.util.spec_from_file_location('pixtuoid_herdr_doctor', SOURCE)
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)

class FakeServer:
    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / 'sock'
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(str(self.path))
        self.socket.listen(3)
        self.req = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
    def serve(self):
        for i in range(3):
            conn, _ = self.socket.accept()
            with conn:
                data = b''
                while not data.endswith(b'\n'):
                    part = conn.recv(4096)
                    if not part: break
                    data += part
                req = json.loads(data)
                self.req.append(req)
                method = req['method']
                if method == 'session.snapshot':
                    result = {'snapshot': {'agents': [{'pane_id':'w1:p1','agent':'pi','agent_status':'idle'}], 'panes':[{'pane_id':'w1:p1'}]}}
                else:
                    result = {'type':'pong' if method=='ping' else 'subscription_started'}
                conn.sendall((json.dumps({'id':req['id'], 'result':result}) + '\n').encode())
    def close(self):
        self.thread.join(timeout=2)
        self.socket.close()
        self.dir.cleanup()

class DoctorTests(unittest.TestCase):
    def test_snapshot_envelope(self):
        snap = {'result': {'snapshot': {'agents': [{'pane_id':'a','agent':'pi','agent_status':'idle'}], 'panes': []}}}
        self.assertEqual(len(doctor.unwrap(snap)['agents']), 1)
        with redirect_stdout(io.StringIO()):
            n, _ = doctor.describe(snap)
        self.assertEqual(n, 1)
    def test_socket_roundtrip_readonly(self):
        server = FakeServer()
        try:
            self.assertEqual(doctor.request(server.path,'ping')['result']['type'],'pong')
            n, _ = (0, None)
            with redirect_stdout(io.StringIO()):
                n, _ = doctor.describe(doctor.request(server.path,'session.snapshot'))
            self.assertEqual(n,1)
            resp = doctor.request(server.path,'events.subscribe', {'subscriptions':[{'type': t} for t in doctor.SUBSCRIPTIONS]})
            self.assertNotIn('error',resp)
            self.assertEqual(server.req[2]['params']['subscriptions'][-1]['type'],'pane.updated')
            self.assertNotIn('pane.agent_status_changed',doctor.SUBSCRIPTIONS)
        finally:
            server.close()
    def test_herdr_overlay_has_safe_subscription_and_polling(self):
        overlay = (SOURCE.parent / 'overlay/herdr.rs').read_text()
        self.assertIn('const REFRESH: Duration = Duration::from_secs(5);', overlay)
        self.assertIn('let subscriptions = ["pane.created",', overlay)
        self.assertNotIn('"pane.agent_status_changed", "pane.updated"',overlay)
        self.assertIn('pub(crate) fn focus_slot',overlay)

if __name__ == '__main__': unittest.main()
