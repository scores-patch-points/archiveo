"""Tests for the archiveo gateway against a stand-in archive (no network, no archive.org).
    python3 -m unittest gateway/test_server.py -v     (from the repo root; or run this file directly)
"""
import gzip
import http.server
import json
import os
import re
import socketserver
import sys
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

os.environ.setdefault('no_proxy', '*')       # loopback only: never ask the OS for proxy settings during tests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as gw  # noqa: E402

KEY = 'k' * 40
ORIGIN = 'https://scores-patch-points.github.io'


class FakeArchive(http.server.BaseHTTPRequestHandler):
    """Behaves like the Wayback Machine as measured: POST /save, then /web/2/<url> redirects once captured."""
    captures = {}
    mode = 'ok'            # ok | gzip | never | corrupt | reject
    saves = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get('Content-Length', '0'))
        form = urllib.parse.parse_qs(self.rfile.read(n).decode())
        url = form.get('url', [''])[0]
        FakeArchive.saves.append((url, form.get('capture_all', [''])[0], self.headers.get('User-Agent', '')))
        if FakeArchive.mode == 'reject':
            self.send_response(429); self.end_headers(); return
        if FakeArchive.mode != 'never':
            def crawl():
                time.sleep(0.15)
                with urllib.request.urlopen(url, timeout=5) as r:
                    FakeArchive.captures[url] = ('20261124211621', r.read())
            threading.Thread(target=crawl, daemon=True).start()
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(b'<html>saving</html>')

    flaky = 0           # how many of the next lookups drop the connection (a flaky network between us and the archive)
    poison = False      # the replay endpoint answers 'not archived' from a cache, even though the capture exists (what hid a real capture)
    index_lag = 0       # how many index lookups say 'nothing yet' after the capture was made

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        if (self.path.startswith('/cdx/') or self.path.startswith('/wayback/')) and FakeArchive.flaky > 0:
            FakeArchive.flaky -= 1
            self.close_connection = True                  # no reply at all
            return
        if self.path.startswith('/cdx/') or self.path.startswith('/wayback/'):
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            hit = FakeArchive.captures.get(qs.get('url', [''])[0])
            if hit and FakeArchive.index_lag > 0:
                FakeArchive.index_lag -= 1; hit = None
            if self.path.startswith('/cdx/'):
                return self._json([['timestamp'], [hit[0]]] if hit else [])
            return self._json({'archived_snapshots': {'closest': {'available': True, 'status': '200', 'timestamp': hit[0], 'url': ''}} if hit else {}})
        m = re.match(r'/web/2/(.+)$', self.path)
        if m and FakeArchive.poison:
            self.send_response(404); self.end_headers(); return
        if m:
            hit = FakeArchive.captures.get(m.group(1))
            if not hit:
                self.send_response(404); self.end_headers(); return
            self.send_response(302); self.send_header('Location', f'/web/{hit[0]}/{m.group(1)}'); self.end_headers(); return
        m = re.match(r'/web/(\d{14})id_/(.+)$', self.path)
        if m:
            stamp, body = FakeArchive.captures[m.group(2)]
            if FakeArchive.mode == 'corrupt':
                body = body + b'!'
            self.send_response(200)
            if FakeArchive.mode == 'gzip':
                body = gzip.compress(body); self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()


class Threaded(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def start_gateway(**over):
    ia = Threaded(('127.0.0.1', 0), FakeArchive)
    threading.Thread(target=ia.serve_forever, daemon=True).start()
    env = {'GATEWAY_PORT': '0', 'GATEWAY_KEY': KEY, 'GATEWAY_PUBLIC': 'http://127.0.0.1:1', 'IA_BASE': f'http://127.0.0.1:{ia.server_address[1]}', 'IA_API_BASE': f'http://127.0.0.1:{ia.server_address[1]}',      # every archive address points at the stand-in: a test never touches the internet
          
           'GATEWAY_MIN_INTERVAL_S': '0', 'GATEWAY_POLL_S': '0.1', 'GATEWAY_CAPTURE_WAIT_S': '3', 'GATEWAY_ORIGINS': ORIGIN}
    env.update({k: str(v) for k, v in over.items()})
    cfg = gw.Config(env)
    srv, state = gw.serve(cfg)
    port = srv.server_address[1]
    cfg.public = f'http://127.0.0.1:{port}'        # the stand-in archive fetches the hosted page from here
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return cfg, state, port, ia, srv


def call(port, path, body=None, key=KEY, origin=None, method=None):
    headers = {}
    if key is not None:
        headers['Authorization'] = f'Bearer {key}'
    if origin:
        headers['Origin'] = origin
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=20)
        raw = r.read()
        return r.status, dict(r.headers), raw
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def events(raw):
    return [json.loads(l) for l in raw.decode().splitlines() if l.strip()]


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, cls.state, cls.port, cls.ia, cls.srv = start_gateway()

    def setUp(self):
        FakeArchive.mode = 'ok'; FakeArchive.captures.clear(); FakeArchive.saves.clear(); FakeArchive.poison = False; FakeArchive.index_lag = 0; FakeArchive.flaky = 0

    def test_health_and_unknown_paths(self):
        s, h, b = call(self.port, '/health', key=None)
        self.assertEqual(s, 200); self.assertTrue(json.loads(b)['ok'])
        self.assertEqual(call(self.port, '/nope', key=None)[0], 404)
        self.assertEqual(call(self.port, '/t/' + 'a' * 24, key=None)[0], 404)       # no such page

    def test_auth_check_does_not_start_a_capture(self):
        self.assertEqual(call(self.port, '/auth', key=KEY)[0], 200)
        self.assertEqual(call(self.port, '/auth', key='x' * 40)[0], 401)
        self.assertEqual(call(self.port, '/auth', key=None)[0], 401)
        self.assertEqual(FakeArchive.saves, [])

    def test_cors_only_for_listed_origins(self):
        s, h, _ = call(self.port, '/backup', origin=ORIGIN, method='OPTIONS', key=None)
        self.assertEqual(s, 204); self.assertEqual(h['Access-Control-Allow-Origin'], ORIGIN); self.assertIn('authorization', h['Access-Control-Allow-Headers'])
        s, h, _ = call(self.port, '/backup', origin='https://evil.example', method='OPTIONS', key=None)
        self.assertNotIn('Access-Control-Allow-Origin', h)

    def test_key_size_and_json_are_checked_before_anything_is_hosted(self):
        self.assertEqual(call(self.port, '/backup', {'text': 'x'}, key=None)[0], 401)
        self.assertEqual(call(self.port, '/backup', {'text': 'x'}, key='wrong' * 8)[0], 401)
        self.assertEqual(call(self.port, '/backup', b'not json')[0], 400)
        self.assertEqual(call(self.port, '/backup', {'text': ''})[0], 400)
        self.assertEqual(call(self.port, '/backup', {'text': 5})[0], 400)
        self.assertEqual(call(self.port, '/backup', {'text': 'x' * (self.cfg.max_bytes + 1)})[0], 413)
        self.assertEqual(FakeArchive.saves, [])                                      # nothing reached the archive

    def test_happy_path_sequence_and_exact_bytes(self):
        text = 'Sinä vaan lepäilet\r\nTityrus — 日本語 😀\n'
        s, h, raw = call(self.port, '/backup', {'text': text}, origin=ORIGIN)
        self.assertEqual(s, 200); self.assertEqual(h['Content-Type'], 'application/x-ndjson'); self.assertEqual(h['X-Accel-Buffering'], 'no')
        self.assertEqual(h['Access-Control-Allow-Origin'], ORIGIN)
        ev = events(raw); phases = [e['phase'] for e in ev]
        self.assertEqual(phases[0], 'hosting'); self.assertIn('capturing', phases); self.assertIn('verifying', phases); self.assertEqual(phases[-1], 'done')
        self.assertTrue(all('eta_s' in e for e in ev))
        cap = ev[-1]['capture']
        self.assertTrue(cap['verified']); self.assertTrue(cap['deleted']); self.assertEqual(cap['timestamp'], '20261124211621'); self.assertEqual(cap['bytes'], len(text.encode()))
        self.assertTrue(cap['url'].endswith('/web/20261124211621/' + cap['original'])); self.assertTrue(cap['raw'].endswith('id_/' + cap['original']))
        # what the archive was asked to save, politely and identified
        url, capture_all, ua = FakeArchive.saves[0]
        self.assertEqual(url, cap['original']); self.assertEqual(capture_all, 'on'); self.assertIn('archiveo-gateway', ua)
        # the archive saw exactly our bytes, and the page is gone afterwards
        self.assertEqual(FakeArchive.captures[cap['original']][1], text.encode())
        self.assertEqual(call(self.port, urllib.parse.urlparse(cap['original']).path, key=None)[0], 404)
        self.assertEqual(self.state.pages, {})

    def test_a_dropped_connection_while_waiting_does_not_abort_the_capture(self):
        FakeArchive.flaky = 3
        ev = events(call(self.port, '/backup', {'text': 'survives a flaky network'})[2])
        self.assertEqual(ev[-1]['phase'], 'done'); self.assertTrue(ev[-1]['capture']['verified'])
        self.assertTrue(any('network error' in e.get('message', '') for e in ev))
        self.assertEqual(self.state.pages, {})

    def test_a_network_that_never_comes_back_ends_in_an_error_and_deletes_the_page(self):
        FakeArchive.flaky = 1000
        ev = events(call(self.port, '/backup', {'text': 'archive unreachable'})[2])
        FakeArchive.flaky = 0
        self.assertEqual(ev[-1]['phase'], 'error'); self.assertIn('could not reach the archive', ev[-1]['message'])
        self.assertEqual(self.state.pages, {})

    def test_after_the_usual_time_the_eta_becomes_null_and_the_message_says_so(self):
        old = gw.EST_CAPTURE_S, gw.EST_VERIFY_S
        gw.EST_CAPTURE_S, gw.EST_VERIFY_S = 0.2, 0.0
        FakeArchive.mode = 'never'
        try:
            ev = events(call(self.port, '/backup', {'text': 'slow archive'})[2])
        finally:
            gw.EST_CAPTURE_S, gw.EST_VERIFY_S = old
        late = [e for e in ev if e['phase'] == 'waiting' and e['eta_s'] is None]
        self.assertTrue(late); self.assertIn('slower than usual', late[0]['message'])

    def test_a_poisoned_replay_cache_cannot_hide_a_capture(self):
        FakeArchive.poison = True                          # /web/2/<url> would say 'not archived' for ever
        ev = events(call(self.port, '/backup', {'text': 'poisoned cache'})[2])
        self.assertEqual(ev[-1]['phase'], 'done'); self.assertTrue(ev[-1]['capture']['verified'])

    def test_it_keeps_asking_while_the_index_lags_and_then_finds_the_capture(self):
        FakeArchive.index_lag = 4                          # the capture exists but the index says nothing for the first four lookups
        ev = events(call(self.port, '/backup', {'text': 'index lag'})[2])
        self.assertEqual(ev[-1]['phase'], 'done', ev[-1])
        self.assertGreaterEqual(len([e for e in ev if e['phase'] == 'waiting']), 3)

    def test_each_lookup_carries_a_throwaway_parameter_so_no_cache_can_answer_it(self):
        seen = []
        orig = FakeArchive.do_GET
        def spy(self):
            if self.path.startswith('/cdx/'):
                seen.append(urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('_', [''])[0])
            return orig(self)
        FakeArchive.do_GET = spy
        try:
            FakeArchive.index_lag = 3
            events(call(self.port, '/backup', {'text': 'cache busting'})[2])
        finally:
            FakeArchive.do_GET = orig
        self.assertGreaterEqual(len(seen), 3); self.assertEqual(len(set(seen)), len(seen)); self.assertTrue(all(len(x) == 8 for x in seen))

    def test_a_capture_found_after_the_usual_time_still_completes(self):
        # the bug that ended a real run: past the estimate eta() is None, and the 'verifying' step did arithmetic on it
        old = gw.EST_CAPTURE_S, gw.EST_VERIFY_S
        gw.EST_CAPTURE_S, gw.EST_VERIFY_S = 0.05, 0.0
        FakeArchive.index_lag = 3
        try:
            ev = events(call(self.port, '/backup', {'text': 'slow but successful'})[2])
        finally:
            gw.EST_CAPTURE_S, gw.EST_VERIFY_S = old
        self.assertEqual(ev[-1]['phase'], 'done'); self.assertTrue(ev[-1]['capture']['verified'])
        self.assertTrue(any(e['phase'] == 'verifying' and isinstance(e['eta_s'], (int, float)) for e in ev))

    def test_an_unexpected_exception_still_ends_with_an_error_event_and_deletes_the_page(self):
        orig = gw.verify_capture
        gw.verify_capture = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        try:
            ev = events(call(self.port, '/backup', {'text': 'bug inside'})[2])
        finally:
            gw.verify_capture = orig
        self.assertEqual(ev[-1]['phase'], 'error'); self.assertIn('RuntimeError', ev[-1]['message']); self.assertIn('deleted', ev[-1]['message'])
        self.assertEqual(self.state.pages, {}); self.assertEqual(self.state.active, 0)

    def test_a_gzip_replay_still_verifies(self):
        FakeArchive.mode = 'gzip'
        ev = events(call(self.port, '/backup', {'text': 'plain text'})[2])
        self.assertEqual(ev[-1]['phase'], 'done'); self.assertTrue(ev[-1]['capture']['verified'])

    def test_failures_end_in_an_error_event_and_the_page_is_deleted(self):
        for mode, needle in (('never', 'no capture appeared'), ('corrupt', 'not byte-identical'), ('reject', '429')):
            with self.subTest(mode=mode):
                FakeArchive.mode = mode
                ev = events(call(self.port, '/backup', {'text': 'will fail'})[2])
                self.assertEqual(ev[-1]['phase'], 'error'); self.assertIn(needle, ev[-1]['message'])
                self.assertEqual(self.state.pages, {}); self.assertEqual(self.state.active, 0)

    def test_temporary_page_headers(self):
        self.state.put('x' * 24, 'hello <b>world</b>'.encode())
        s, h, b = call(self.port, '/t/' + 'x' * 24, key=None)
        self.assertEqual(s, 200); self.assertEqual(b, b'hello <b>world</b>')
        self.assertEqual(h['Content-Type'], 'text/plain; charset=utf-8'); self.assertEqual(h['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(h['Cache-Control'], 'no-store'); self.assertIn('sandbox', h['Content-Security-Policy']); self.assertEqual(h['X-Robots-Tag'], 'noindex')
        s, h, b = call(self.port, '/t/' + 'x' * 24, key=None, method='HEAD')
        self.assertEqual((s, b), (200, b''))
        self.state.remove('x' * 24)

    def test_pages_expire_and_are_swept(self):
        self.state.pages['e' * 24] = (b'old', time.time() - 1)
        self.assertEqual(call(self.port, '/t/' + 'e' * 24, key=None)[0], 404)
        self.state.pages['f' * 24] = (b'old', time.time() - 1)
        self.state.sweep(); self.assertNotIn('f' * 24, self.state.pages)


class FilesModeTests(unittest.TestCase):
    """Temporary pages as files in a folder another web server publishes (nothing about that server changes)."""
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix='archiveo-files-')
        d = cls.dir

        class Static(http.server.BaseHTTPRequestHandler):          # stands in for nginx serving the folder
            def log_message(self, *a): pass
            def do_GET(self):
                name = self.path.rsplit('/', 1)[-1]
                try:
                    body = open(os.path.join(d, name), 'rb').read()
                except OSError:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header('Content-Type', 'text/plain'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        cls.static = Threaded(('127.0.0.1', 0), Static)
        threading.Thread(target=cls.static.serve_forever, daemon=True).start()
        cls.files_url = f'http://127.0.0.1:{cls.static.server_address[1]}/samples/_archiveo'
        open(os.path.join(d, 'a' * 24 + '.txt'), 'w').write('left over from a crash')     # ours: must be purged at start
        open(os.path.join(d, 'keep-me.txt'), 'w').write('somebody else\'s file')           # not ours: must survive
        cls.cfg, cls.state, cls.port, cls.ia, cls.srv = start_gateway(GATEWAY_FILES_DIR=d, GATEWAY_FILES_URL=cls.files_url, GATEWAY_PUBLIC='')

    def setUp(self):
        FakeArchive.mode = 'ok'; FakeArchive.captures.clear(); FakeArchive.saves.clear()

    def test_startup_purges_only_its_own_leftovers(self):
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'a' * 24 + '.txt')))
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'keep-me.txt')))

    def test_page_is_a_file_with_a_utf8_mark_and_is_gone_afterwards(self):
        text = 'Sinä vaan — 日本語\n'
        ev = events(call(self.port, '/backup', {'text': text})[2])
        self.assertEqual(ev[-1]['phase'], 'done'); cap = ev[-1]['capture']
        self.assertTrue(cap['original'].startswith(self.files_url + '/') and cap['original'].endswith('.txt'))
        seen = FakeArchive.captures[cap['original']][1]
        self.assertEqual(seen, b'\xef\xbb\xbf' + text.encode())                 # the archive saw the mark plus the text exactly
        self.assertEqual(cap['bytes'], len(text.encode()))                         # the count is the text, not the mark
        self.assertEqual(sorted(os.listdir(self.dir)), ['keep-me.txt'])           # nothing of ours left behind
        self.assertTrue(cap['deleted'])                                            # and the gateway checked, rather than assumed
        self.assertEqual(self.state.pages, {})

    def test_a_failed_capture_still_deletes_the_file(self):
        FakeArchive.mode = 'never'
        ev = events(call(self.port, '/backup', {'text': 'will fail'})[2])
        self.assertEqual(ev[-1]['phase'], 'error'); self.assertIn('temporary page has been deleted', ev[-1]['message'])
        self.assertEqual(sorted(os.listdir(self.dir)), ['keep-me.txt'])

    def test_the_gateway_does_not_serve_pages_itself_in_this_mode(self):
        self.state.put('b' * 24, b'x')
        self.assertEqual(call(self.port, '/t/' + 'b' * 24, key=None)[0], 404)
        self.state.remove('b' * 24)
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'b' * 24 + '.txt')))

    def test_expired_files_are_swept(self):
        self.state.put('c' * 24, b'old'); self.state.pages['c' * 24] = (b'old', time.time() - 1)
        self.state.sweep()
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'c' * 24 + '.txt')))

    def test_is_gone_checks_the_disk_not_just_memory(self):
        self.state.put('d' * 24, b'x')
        self.assertFalse(self.state.is_gone('d' * 24))
        self.state.pages.pop('d' * 24)                      # forget it in memory, but the file is still on disk
        self.assertFalse(self.state.is_gone('d' * 24))
        self.state.remove('d' * 24)
        self.assertTrue(self.state.is_gone('d' * 24))

    def test_config_needs_both_halves_of_files_mode(self):
        self.assertTrue(gw.Config({'GATEWAY_KEY': 'k' * 40, 'GATEWAY_FILES_DIR': '/x'}).problems())
        self.assertEqual(gw.Config({'GATEWAY_KEY': 'k' * 40, 'GATEWAY_FILES_DIR': '/x', 'GATEWAY_FILES_URL': 'https://watch.hyphae.social/samples/_archiveo'}).problems(), [])


class PolitenessTests(unittest.TestCase):
    def test_second_capture_too_soon_is_refused_with_a_retry_time(self):
        FakeArchive.mode = 'ok'; FakeArchive.captures.clear()
        cfg, state, port, ia, srv = start_gateway(GATEWAY_MIN_INTERVAL_S=30)
        self.assertEqual(events(call(port, '/backup', {'text': 'one'})[2])[-1]['phase'], 'done')
        s, h, b = call(port, '/backup', {'text': 'two'})
        self.assertEqual(s, 429); self.assertGreater(json.loads(b)['retry_after_s'], 0); self.assertIn('Retry-After', h)

    def test_startup_refuses_a_missing_or_short_key_and_a_missing_public_url(self):
        self.assertTrue(gw.Config({'GATEWAY_KEY': 'short', 'GATEWAY_PUBLIC': 'https://x.example'}).problems())
        self.assertTrue(gw.Config({'GATEWAY_KEY': 'k' * 40}).problems())
        self.assertEqual(gw.Config({'GATEWAY_KEY': 'k' * 40, 'GATEWAY_PUBLIC': 'https://hyphae.social/gateway/'}).problems(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
