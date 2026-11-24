#!/usr/bin/env python3
"""Run the gateway against a stand-in archive on localhost, to try archiveo's page without touching archive.org.

    python3 gateway/dev.py [seconds the stand-in takes to "capture" (default 6)]

Gateway: http://localhost:8850   key: dev-key-dev-key-dev-key-dev-key-0000 (a throwaway; this mode never leaves your machine)
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server as gw           # noqa: E402
import test_server as ts      # noqa: E402

DELAY = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
KEY = 'dev-key-dev-key-dev-key-dev-key-0000'

orig_post = ts.FakeArchive.do_POST
def slow_post(self):
    time.sleep(0)               # the stand-in accepts at once, then "captures" after DELAY, like a busy archive
    orig_post(self)
ts.FakeArchive.do_POST = slow_post
orig_sleep = time.sleep

ia = ts.Threaded(('127.0.0.1', 8851), ts.FakeArchive)
threading.Thread(target=ia.serve_forever, daemon=True).start()
# make the stand-in's crawler wait DELAY seconds before the capture appears
import urllib.request
def crawl_later(url):
    orig_sleep(DELAY)
    with urllib.request.urlopen(url, timeout=5) as r:
        ts.FakeArchive.captures[url] = ('20261124211621', r.read())
class Slow(ts.FakeArchive):
    def do_POST(self):
        import urllib.parse
        n = int(self.headers.get('Content-Length', '0'))
        url = urllib.parse.parse_qs(self.rfile.read(n).decode()).get('url', [''])[0]
        threading.Thread(target=crawl_later, args=(url,), daemon=True).start()
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(b'<html>saving</html>')
ia.RequestHandlerClass = Slow

cfg = gw.Config({'GATEWAY_PORT': '8850', 'GATEWAY_KEY': KEY, 'GATEWAY_PUBLIC': 'http://127.0.0.1:8850', 'IA_BASE': 'http://127.0.0.1:8851',
                 'GATEWAY_MIN_INTERVAL_S': '3', 'GATEWAY_POLL_S': '1', 'GATEWAY_CAPTURE_WAIT_S': '60'})
srv, state = gw.serve(cfg)
print(f'dev gateway on http://localhost:8850  key {KEY}  stand-in archive takes {DELAY:g}s', flush=True)
srv.serve_forever()
