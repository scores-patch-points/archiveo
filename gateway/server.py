#!/usr/bin/env python3
"""archiveo gateway.

Hosts a page for a moment, asks the Wayback Machine to capture it, checks the capture is
readable and byte-identical, deletes the page, and reports progress as it goes so a page can
show a countdown. Nothing needs an archive.org account: Save Page Now takes an anonymous POST.

    POST /backup   Authorization: Bearer <key>   {"text": "..."}   -> NDJSON progress, ends in "done"
    GET  /auth     Authorization: Bearer <key>   -> 200 if the key is right (no capture)
    GET  /t/<id>   the temporary page (it exists only while a backup is running)
    GET  /health

It keeps the page in memory only while the capture runs, and logs phases and status codes,
never content and never the key. Python 3 standard library only.
"""
import gzip
import hmac
import http.server
import json
import os
import re
import secrets
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = '0.1'
# Measured on 2026-11-24 (three real captures): the crawler fetched the page 4 s, 4 s and about 57 s after submission, and when asked the right way
# the capture was listed within about 3 s. The archive queues anonymous saves, so the typical time is a guess, and past it the countdown says so.
EST_CAPTURE_S = 15.0
EST_VERIFY_S = 3.0
MAX_POLL_ERRORS = 6     # consecutive network errors while polling before giving up (one hiccup must not abort a capture)


class Config:
    def __init__(self, environ=None):
        e = os.environ if environ is None else environ
        self.host = e.get('GATEWAY_HOST', '127.0.0.1')
        self.port = int(e.get('GATEWAY_PORT', '8850'))
        self.public = e.get('GATEWAY_PUBLIC', '').rstrip('/')                    # where archive.org will fetch /t/<id> from (memory mode)
        # Files mode: write each temporary page as <id>.txt into a folder some web server already publishes, and give its public base URL.
        # Nothing about that web server's own configuration has to change, and this service need not be reachable from the internet at all.
        self.files_dir = e.get('GATEWAY_FILES_DIR', '').rstrip('/')
        self.files_url = e.get('GATEWAY_FILES_URL', '').rstrip('/')
        self.bom = e.get('GATEWAY_FILES_BOM', '1') != '0'                       # a UTF-8 mark, because a static server sends text/plain with no charset
        self.ia = e.get('IA_BASE', 'https://web.archive.org').rstrip('/')
        self.api = e.get('IA_API_BASE', 'https://archive.org').rstrip('/')       # the availability API lives on archive.org, not web.archive.org
        self.max_bytes = int(e.get('GATEWAY_MAX_BYTES', str(256 * 1024)))
        self.ttl = int(e.get('GATEWAY_TTL_S', '900'))                            # backstop: a page is never kept longer than this, whatever happens
        self.min_interval = float(e.get('GATEWAY_MIN_INTERVAL_S', '10'))         # politeness to archive.org: one capture per interval
        self.max_active = int(e.get('GATEWAY_MAX_ACTIVE', '2'))
        self.wait_s = float(e.get('GATEWAY_CAPTURE_WAIT_S', '600'))             # the capture is made in seconds but can take minutes to become readable
        self.poll_s = float(e.get('GATEWAY_POLL_S', '4'))
        self.origins = [o.strip() for o in e.get('GATEWAY_ORIGINS',
                        'https://scores-patch-points.github.io,http://localhost:8962,http://127.0.0.1:8962').split(',') if o.strip()]
        key = e.get('GATEWAY_KEY', '')
        key_file = e.get('GATEWAY_KEY_FILE', '')
        if not key and key_file:
            with open(key_file, encoding='utf8') as f:
                key = f.read().strip()
        self.key = key
        self.ua = e.get('GATEWAY_UA', f'archiveo-gateway/{VERSION} (+https://github.com/scores-patch-points/archiveo)')

    def problems(self):
        out = []
        if len(self.key) < 24:
            out.append('GATEWAY_KEY (or GATEWAY_KEY_FILE) must hold a secret of at least 24 characters')
        if self.files_dir or self.files_url:
            if not (self.files_dir and re.match(r'^https?://', self.files_url)):      # regex-ok: URL scheme
                out.append('GATEWAY_FILES_DIR and GATEWAY_FILES_URL go together (the URL must start with https://)')
        elif not re.match(r'^https?://', self.public):                              # regex-ok: URL scheme
            out.append('set GATEWAY_PUBLIC (this service reachable from the internet) or GATEWAY_FILES_DIR + GATEWAY_FILES_URL')
        return out


class State:
    """The temporary pages, and the little bookkeeping that keeps this polite."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.pages = {}                       # id -> (bytes, expires_at)
        self.lock = threading.Lock()
        self.last_start = 0.0
        self.active = 0

    def _path(self, page_id):
        return os.path.join(self.cfg.files_dir, page_id + '.txt')

    def url(self, page_id):
        c = self.cfg
        return f'{c.files_url}/{page_id}.txt' if c.files_dir else f'{c.public}/t/{page_id}'

    def put(self, page_id, data):
        """Hosts the page and returns the exact bytes a visitor will receive."""
        stored = (b'\xef\xbb\xbf' if self.cfg.files_dir and self.cfg.bom else b'') + data
        if self.cfg.files_dir:
            tmp = os.path.join(self.cfg.files_dir, '.tmp-' + page_id)
            with open(tmp, 'wb') as f:
                f.write(stored)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self._path(page_id))                # appears whole or not at all
        with self.lock:
            self.pages[page_id] = (stored, time.time() + self.cfg.ttl)
        return stored

    def _unlink(self, page_id):
        if self.cfg.files_dir:
            try:
                os.unlink(self._path(page_id))
            except FileNotFoundError:
                pass

    def purge_files(self):
        """Delete leftovers of ours (a crash mid-capture): only names this service could have made."""
        if not self.cfg.files_dir:
            return
        for name in os.listdir(self.cfg.files_dir):
            if re.fullmatch(r'([A-Za-z0-9_-]{24}\.txt|\.tmp-[A-Za-z0-9_-]{24})', name):         # regex-ok: our own file names
                try:
                    os.unlink(os.path.join(self.cfg.files_dir, name))
                except OSError:
                    pass

    def get(self, page_id):
        if self.cfg.files_dir:
            return None                                          # in files mode the other web server serves them, not us
        with self.lock:
            hit = self.pages.get(page_id)
            if not hit:
                return None
            if hit[1] < time.time():
                del self.pages[page_id]
                return None
            return hit[0]

    def remove(self, page_id):
        with self.lock:
            self.pages.pop(page_id, None)
        self._unlink(page_id)

    def is_gone(self, page_id):
        """True only if the page is neither in memory nor on disk (checked, not assumed)."""
        with self.lock:
            if page_id in self.pages:
                return False
        return not (self.cfg.files_dir and os.path.exists(self._path(page_id)))

    def sweep(self):
        now = time.time()
        with self.lock:
            gone = [k for k, (_, exp) in self.pages.items() if exp < now]
            for k in gone:
                del self.pages[k]
        for k in gone:
            self._unlink(k)

    def admit(self):
        """Returns (ok, retry_after_s). A capture may start if none is too recent and few are running."""
        with self.lock:
            now = time.time()
            wait = self.last_start + self.cfg.min_interval - now
            if wait > 0:
                return False, wait
            if self.active >= self.cfg.max_active:
                return False, 5.0
            self.last_start = now
            self.active += 1
            return True, 0.0

    def done(self):
        with self.lock:
            self.active = max(0, self.active - 1)


class Failure(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_OPEN_FOLLOW = urllib.request.build_opener()                 # built once: building one per call re-detects proxies every time
_OPEN_STOP = urllib.request.build_opener(_NoRedirect)


def ia_call(cfg, url, method='GET', data=None, headers=None, follow=False, timeout=40):
    req = urllib.request.Request(url, data=data, method=method, headers={'User-Agent': cfg.ua, **(headers or {})})
    opener = _OPEN_FOLLOW if follow else _OPEN_STOP
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as err:                # a refused redirect and an error status both land here
        return err.code, dict(err.headers), err.read()
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise Failure(f'could not reach the archive: {err}')


def submit_capture(cfg, url):
    body = urllib.parse.urlencode({'url': url, 'capture_all': 'on'}).encode()
    status, _, _ = ia_call(cfg, cfg.ia + '/save', 'POST', body, {'Content-Type': 'application/x-www-form-urlencoded'}, follow=True)
    if status == 429:
        raise Failure('the Wayback Machine is limiting saves right now (HTTP 429)')
    if status >= 400:
        raise Failure(f'the Wayback Machine refused the save (HTTP {status})')


def _stamp_from(status, body, key):
    """A 14-digit capture timestamp from a CDX row list or an availability answer, or None."""
    if status != 200:
        return None
    try:
        data = json.loads(body or b'null')
    except ValueError:
        return None
    if key == 'cdx':
        stamp = data[1][0] if isinstance(data, list) and len(data) > 1 and data[1] else None
    else:
        snap = ((data or {}).get('archived_snapshots') or {}).get('closest') if isinstance(data, dict) else None
        stamp = snap.get('timestamp') if isinstance(snap, dict) and snap.get('available') else None
    return stamp if isinstance(stamp, str) and re.fullmatch(r'\d{14}', stamp) else None      # regex-ok: archive timestamp shape


def find_capture(cfg, url, attempt=1):
    """The 14-digit timestamp of the capture of exactly this URL, or None while it is not listed yet.

    Asks the CDX index (and every other round the availability API), each time with a throwaway parameter so no cached answer can be
    reused. The replay endpoint /web/2/<url> caches 'not there yet' for minutes; polling it hid a capture that had existed since second four."""
    q, nonce = urllib.parse.quote(url, safe=''), secrets.token_hex(4)
    status, _, body = ia_call(cfg, f'{cfg.ia}/cdx/search/cdx?output=json&limit=1&fl=timestamp&url={q}&_={nonce}', follow=True)
    stamp = _stamp_from(status, body, 'cdx')
    if not stamp and attempt % 2 == 0:
        status, _, body = ia_call(cfg, f'{cfg.api}/wayback/available?url={q}&_={nonce}', follow=True)
        stamp = _stamp_from(status, body, 'available')
    return stamp


def verify_capture(cfg, stamp, url, expected):
    for tries in range(4):                                # the index can list a capture a moment before it can be replayed
        status, headers, body = ia_call(cfg, f'{cfg.ia}/web/{stamp}id_/{url}', headers={'Accept-Encoding': 'gzip, identity'}, follow=True)
        if status == 200:
            break
        time.sleep(cfg.poll_s * 0.75)
    if status != 200:
        raise Failure(f'the capture is listed but could not be read back (HTTP {status})')
    if any(k.lower() == 'content-encoding' and 'gzip' in v.lower() for k, v in headers.items()):
        body = gzip.decompress(body)
    if body != expected:
        raise Failure('the capture is not byte-identical to what was sent')


def run_backup(cfg, state, content, emit):
    """Host, capture, verify, delete. Always deletes. emit() is told each step."""
    started = time.time()
    page_id = secrets.token_urlsafe(18)
    url = state.url(page_id)
    stored = state.put(page_id, content)
    def eta(floor=2.0):                                   # None once the usual time has passed: the page then says it is taking longer
        left = EST_CAPTURE_S + EST_VERIFY_S - (time.time() - started)
        return round(max(floor, left), 1) if left > 0 else None
    try:
        emit(phase='hosting', eta_s=eta(), message='Hosting the page')
        submit_capture(cfg, url)
        emit(phase='capturing', eta_s=eta(), message='The Wayback Machine is capturing it')
        stamp, attempt, errors = None, 0, 0
        while time.time() - started < cfg.wait_s:
            attempt += 1
            try:
                stamp = find_capture(cfg, url, attempt)
                errors = 0
            except Failure as err:                        # a dropped connection to the archive is not the end of the capture
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise
                emit(phase='waiting', attempt=attempt, eta_s=eta(3.0), message='Waiting for the capture (retrying after a network error)')
            if stamp:
                break
            if not errors:
                late = eta(3.0) is None
                emit(phase='waiting', attempt=attempt, eta_s=eta(3.0),
                     message='Still waiting: the Wayback Machine is slower than usual' if late else 'Waiting for the capture to appear')
            ramp = (0.4, 0.5, 0.5, 0.75, 0.75, 1.0)[min(attempt - 1, 5)]       # quick at first, which is when it usually appears
            time.sleep(min(cfg.poll_s * ramp * (1 + attempt // 12), 10))        # then gentler the longer it takes
        if not stamp:
            raise Failure(f'no capture appeared within {int(cfg.wait_s)} seconds')
        left = eta()                                       # None once the usual time has passed
        emit(phase='verifying', eta_s=EST_VERIFY_S if left is None else min(left, EST_VERIFY_S), message='Reading the capture back to check it')
        verify_capture(cfg, stamp, url, stored)
    finally:
        state.remove(page_id)                              # the page leaves the disk as soon as the capture is available, and on any failure
    emit(phase='done', eta_s=0, message='Available', capture={
        'url': f'{cfg.ia}/web/{stamp}/{url}', 'raw': f'{cfg.ia}/web/{stamp}id_/{url}', 'timestamp': stamp,
        'original': url, 'bytes': len(content), 'verified': True, 'deleted': state.is_gone(page_id), 'seconds': round(time.time() - started, 1)})


def make_handler(cfg, state):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = f'archiveo-gateway/{VERSION}'

        def log_message(self, fmt, *args):                 # request line and status only; no bodies, no headers
            sys.stderr.write('%s %s\n' % (self.log_date_time_string(), fmt % args))

        def _cors(self):
            origin = self.headers.get('Origin', '')
            if origin in cfg.origins:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Headers', 'authorization, content-type')
                self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
                self.send_header('Access-Control-Max-Age', '600')

        def _json(self, status, obj, extra=None):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _authed(self):
            auth = self.headers.get('Authorization', '')
            return auth.startswith('Bearer ') and hmac.compare_digest(auth[7:].encode(), cfg.key.encode())

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.send_header('Content-Length', '0')
            self.end_headers()

        def _serve_page(self, head_only):
            m = re.fullmatch(r'/t/([A-Za-z0-9_-]{16,64})', self.path.split('?')[0])      # regex-ok: our own id shape
            data = state.get(m.group(1)) if m else None
            if data is None:
                return self._json(404, {'error': 'not found'})
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')               # never HTML: this is somebody's text on our domain
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Robots-Tag', 'noindex')
            self.send_header('Content-Security-Policy', "sandbox; default-src 'none'")
            self.end_headers()
            if not head_only:
                self.wfile.write(data)

        def do_HEAD(self):
            if self.path.startswith('/t/'):
                return self._serve_page(True)
            self._json(404, {'error': 'not found'})

        def do_GET(self):
            path = self.path.split('?')[0]
            if path.startswith('/t/'):
                return self._serve_page(False)
            if path == '/auth':                                       # lets a page check its key without starting a capture
                return self._json(200, {'ok': True}) if self._authed() else self._json(401, {'error': 'missing or wrong key'})
            if path in ('/', '/health'):
                return self._json(200, {'ok': True, 'service': 'archiveo-gateway', 'version': VERSION, 'maxBytes': cfg.max_bytes})
            self._json(404, {'error': 'not found'})

        def do_POST(self):
            if self.path.split('?')[0] != '/backup':
                return self._json(404, {'error': 'not found'})
            if not self._authed():
                return self._json(401, {'error': 'missing or wrong key'})
            try:
                n = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                n = -1
            if n < 0 or n > cfg.max_bytes * 2 + 4096:
                return self._json(413, {'error': f'too large (limit {cfg.max_bytes} bytes of text)'})
            try:
                text = json.loads(self.rfile.read(n) or b'{}').get('text')
            except (ValueError, AttributeError):
                return self._json(400, {'error': 'send JSON like {"text": "..."}'})
            if not isinstance(text, str) or not text:
                return self._json(400, {'error': 'send JSON like {"text": "..."}'})
            content = text.encode('utf-8')
            if len(content) > cfg.max_bytes:
                return self._json(413, {'error': f'too large (limit {cfg.max_bytes} bytes of text)'})
            ok, retry = state.admit()
            if not ok:
                return self._json(429, {'error': 'one capture at a time, and not too often', 'retry_after_s': round(retry, 1)},
                                  {'Retry-After': str(int(retry) + 1)})
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Accel-Buffering', 'no')                # nginx must not hold the progress lines back
                self._cors()
                self.end_headers()
                gone = []

                def emit(**event):
                    if gone:
                        return
                    try:
                        self.wfile.write((json.dumps(event) + '\n').encode())
                        self.wfile.flush()
                    except OSError:
                        gone.append(True)                                   # the caller left; finish and delete anyway

                try:
                    run_backup(cfg, state, content, emit)
                except Failure as err:
                    self.log_message('backup failed: %s', err)
                    emit(phase='error', message=f'{err}. The temporary page has been deleted.')
                except Exception as err:                                       # a bug of ours must still end the stream with an answer
                    self.log_message('backup crashed: %s: %s', type(err).__name__, err)
                    emit(phase='error', message=f'The gateway hit an unexpected error ({type(err).__name__}). The temporary page has been deleted.')
            finally:
                state.done()

    return Handler


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(cfg):
    state = State(cfg)
    if cfg.files_dir:
        os.makedirs(cfg.files_dir, exist_ok=True)
        state.purge_files()
    srv = Server((cfg.host, cfg.port), make_handler(cfg, state))

    def sweeper():
        while True:
            time.sleep(30)
            state.sweep()
    threading.Thread(target=sweeper, daemon=True).start()
    return srv, state


def main():
    cfg = Config()
    bad = cfg.problems()
    if bad:
        sys.exit('archiveo-gateway: ' + '; '.join(bad))
    srv, _ = serve(cfg)
    where = f'files in {cfg.files_dir} published at {cfg.files_url}' if cfg.files_dir else f'public base {cfg.public}'
    print(f'archiveo-gateway {VERSION} on {cfg.host}:{cfg.port}, {where}, origins {len(cfg.origins)}', flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
