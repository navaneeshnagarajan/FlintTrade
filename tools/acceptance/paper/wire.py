"""Owned bounded synthetic health wire; pins are parser inputs, not attestation."""
from __future__ import annotations

import sys
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')

import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import secrets
import threading
import urllib.request

REVISION = '55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851'
WEIGHT = '891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c'
CSV_URL = 'https://images.dhan.co/api-data/api-scrip-master.csv'
CSV = b'SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_TRADING_SYMBOL,SEM_INSTRUMENT_NAME\nNSE,E,2885,RELIANCE,EQUITY\n'


class TextRegistry:
    """Exact caller shapes; authorised failures never delegate to the network."""
    def __init__(self, desk, rows, original):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        self.desk, self.rows, self.original = desk, rows, original
        self.day = datetime.now(ZoneInfo('Asia/Kolkata')).date()
        self.urls = tuple('https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/'
                          + (self.day - timedelta(days=i)).isoformat() + '/transformed/nse_fo.csv' for i in range(7))
        self.counts = {}
        self.lock = threading.Lock()

    def __call__(self, request, *args, **kwargs):
        from urllib.error import URLError
        is_request = type(request) is urllib.request.Request
        url = request.full_url if is_request else request
        method = request.get_method() if is_request else 'GET'
        body = request.data if is_request else None
        headers = request.header_items() if is_request else []
        timeout = kwargs.get('timeout')
        master = is_request and method == 'GET' and body is None and headers == [
            ('User-agent', 'FlintTrade/0.0.1 instrument-lot-excerpt')]
        exact_timeout = type(timeout) is int and timeout == 60
        kind = None
        if not args and set(kwargs) == {'timeout'}:
            if exact_timeout and url == CSV_URL and master:
                kind = 'instrument-master-csv'
            elif exact_timeout and type(request) is str and url == CSV_URL:
                kind = 'sdk-scrip-csv'
            elif exact_timeout and master and url in self.urls:
                kind = 'denial-only-kotak'
            elif is_request and url == 'http://127.0.0.1:5177/health' and method == 'GET' and body is None and headers == [('Accept', 'application/json')] and type(timeout) is float and timeout == 0.5:
                kind = 'health-loopback'
        key = url if kind == 'denial-only-kotak' else kind
        with self.lock:
            count = self.counts.get(key, 0)
            limit = 40 if kind == 'health-loopback' else 1
            accepted = kind is not None and count < limit
            row = {'kind': kind or 'unregistered-text', 'url': str(url), 'method': method,
                   'headers': headers, 'body_base64': base64.b64encode(body if type(body) is bytes else b'').decode(),
                   'body_type': type(body).__name__,
                   'args': repr(args), 'kwargs': repr(kwargs), 'accepted': accepted,
                   'thread': threading.current_thread().name, 'bound_ist_day': self.day.isoformat()}
            self.rows.append(row)
            if not accepted:
                self.desk.failures.append(['unregistered-text-shape-or-overflow', str(url), method])
                raise RuntimeError('R84 unregistered text shape or overflow')
            self.counts[key] = count + 1
        if kind == 'denial-only-kotak':
            row['outcome'] = 'deliberate-URLError-before-DNS-socket'
            raise URLError('R84 authorised synthetic transport unavailable')
        if kind == 'health-loopback':
            return self.original(request, *args, **kwargs)
        row['response_base64'] = base64.b64encode(CSV).decode()
        return io.BytesIO(CSV)


class Wires:
    def __init__(self, desk, scenario):
        self.desk = desk
        self.scenario = scenario
        self.rows = []
        self.mode = scenario
        self.requests = 0
        self.original_urlopen = urllib.request.urlopen
        # Only external transport is replaced; actual downloaders/parsers stay real.
        self.text = TextRegistry(desk, self.rows, self.original_urlopen)
        urllib.request.urlopen = self.text
        key = desk.workspace / 'synthetic-attached-key'
        key.write_text(secrets.token_urlsafe(32)); key.chmod(0o600)
        os.environ['LAYA_HOST'] = '127.0.0.1'
        os.environ['LAYA_PORT'] = '5177'
        os.environ['LAYA_API_KEY_FILE'] = str(key)
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests += 1
                expected_headers = {'accept-encoding':'identity','host':'127.0.0.1:5177',
                                    'user-agent':'Python-urllib/3.14','accept':'application/json','connection':'close'}
                if self.path != '/health' or owner.requests > 40 or dict((k.lower(),v) for k,v in self.headers.items()) != expected_headers or len(self.headers) != len(expected_headers):
                    desk.failures.append(['unregistered-fixture-request', self.command, self.path])
                    self.send_error(500); return
                value = {'status': 'ok', 'loaded': ['english'], 'revisions': {'english': REVISION},
                         'sha256': WEIGHT, 'device': 'cpu', 'cpu_fallbacks': {'english': {'count': 0}}}
                if owner.mode == 'missing-pin':
                    value.pop('sha256')
                elif owner.mode == 'wrong-pin':
                    value['sha256'] = '0' * 64
                elif owner.mode == 'malformed-health':
                    value = {'status': 'ok', 'loaded': 3}
                elif owner.mode == 'health-down':
                    value = {'status': 'loading', 'loaded': []}
                body = json.dumps(value).encode()
                owner.rows.append({'kind': 'labelled-synthetic-health', 'method': self.command, 'path': self.path,
                                   'body_base64': '', 'response_base64': base64.b64encode(body).decode()})
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                desk.failures.append(['unexpected-systemone-or-chat', self.path])
                self.send_error(500)

            def __getattr__(self, name):
                if name.startswith('do_'):
                    return self.do_POST
                raise AttributeError(name)

            def log_message(self, format, *args):
                pass
        desk.allowed_ports.add(5177)
        self.server = HTTPServer(('127.0.0.1', 5177), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, name='r84-health-wire')
        self.thread.start()

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)
        assert not self.thread.is_alive()
        urllib.request.urlopen = self.original_urlopen
        (artifacts() / 'wire.json').write_text(json.dumps(self.rows, indent=2))
