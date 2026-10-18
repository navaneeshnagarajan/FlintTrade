"""Isolated exact text matrix, separate fresh latched registries per control."""

import sys
from pathlib import Path
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
from datetime import timedelta
import json
from types import SimpleNamespace
from urllib.error import URLError
import urllib.request

assert str(Path.home()) == '/run/test/home'
spec = importlib.util.spec_from_file_location('wire', str(Path(__file__).with_name('wire.py')))
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)
rows = []
network = []
def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'urllib.Request'}:
        network.append(event)
        raise AssertionError('No network call is permitted in text controls')
sys.addaudithook(audit)
def request(url, method='GET', data=None, headers=None):
    return urllib.request.Request(url, method=method, data=data, headers=headers if headers is not None else {'User-Agent': 'FlintTrade/0.0.1 instrument-lot-excerpt'})
def transport():
    desk = SimpleNamespace(failures=[])
    def never(*a, **k):
        raise AssertionError('External text must never reach delegated transport')
    return desk, wire.TextRegistry(desk, [], never)
def deny(name, value, *args, **kwargs):
    desk, registry = transport()
    try:
        registry(value(registry) if callable(value) else value, *args, **kwargs)
    except RuntimeError:
        pass
    else:
        raise AssertionError(name + ' did not refuse')
    assert len(desk.failures) == 1 and len(registry.rows) == 1
    assert registry.counts == {}
    rows.append({'control': name, 'failures': desk.failures, 'rows': registry.rows})

# Actual downloader shapes, real date binding, no fake HTTP data for Kotak.
desk, registry = transport()
for url in registry.urls:
    try:
        registry(request(url), timeout=60)
    except URLError:
        pass
    else:
        raise AssertionError('Registered denial returned data')
assert not desk.failures and len(registry.counts) == 7
for value in [request(wire.CSV_URL), wire.CSV_URL]:
    with registry(value, timeout=60) as response:
        assert response.read() == wire.CSV
assert not desk.failures
for value in [request(registry.urls[0]), request(wire.CSV_URL), wire.CSV_URL]:
    try:
        registry(value, timeout=60)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Duplicate protocol use accepted')
assert len(desk.failures) == 3
rows.append({'control': 'seven-denials-two-csv-shapes-three-duplicates', 'rows': registry.rows, 'failures': desk.failures})
for kind in ('kotak','dhan'):
    url = lambda r: r.urls[0] if kind == 'kotak' else wire.CSV_URL
    deny(kind+'-post', lambda r: request(url(r), 'POST'), timeout=60)
    deny(kind+'-body', lambda r: request(url(r), data=b'x'), timeout=60)
    deny(kind+'-string-body', lambda r: request(url(r), data='x'), timeout=60)
    deny(kind+'-empty-body', lambda r: request(url(r), data=b''), timeout=60)
    deny(kind+'-timeout', lambda r: request(url(r)), timeout=59)
    deny(kind+'-extra-argument', lambda r: request(url(r)), None, timeout=60)
    deny(kind+'-extra-kwarg', lambda r: request(url(r)), timeout=60, context=None)
    deny(kind+'-header', lambda r: request(url(r), headers={'User-Agent':'wrong'}), timeout=60)
    deny(kind+'-extra-header', lambda r: request(url(r), headers={'User-Agent':'FlintTrade/0.0.1 instrument-lot-excerpt','Accept':'text/csv'}), timeout=60)
    deny(kind+'-host', lambda r: request(url(r).replace('https://','https://wrong.')), timeout=60)
    deny(kind+'-path', lambda r: request(url(r)+'?extra=1'), timeout=60)
deny('day-window', lambda r: request(r.urls[-1].replace((r.day-timedelta(days=6)).isoformat(),(r.day-timedelta(days=7)).isoformat())), timeout=60)
deny('future-day', lambda r: request(r.urls[0].replace(r.day.isoformat(),(r.day+timedelta(days=1)).isoformat())), timeout=60)
deny('bse-unauthorised', lambda r: request(r.urls[0].replace('nse_fo','bse_fo')), timeout=60)
deny('kotak-string-not-master-shape', lambda r:r.urls[0], timeout=60)
deny('dhan-sdk-body-positional', wire.CSV_URL, b'x', timeout=60)
deny('dhan-sdk-timeout', wire.CSV_URL, timeout=60.0)
assert network == []
(artifacts() / 'text-matrix.json').write_text(json.dumps({'controls':rows,'control_count':len(rows),'network':network},indent=2))
print('TEXT_MATRIX_OK',len(rows))
