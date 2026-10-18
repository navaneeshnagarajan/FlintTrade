"""Fail-closed text protocol controls; execute only under run_isolated."""

import sys
from pathlib import Path
from paths import artifacts
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import json

from types import SimpleNamespace
import urllib.request

assert str(Path.home()) == '/run/test/home'
OUT = artifacts()
spec = importlib.util.spec_from_file_location('wire', str(Path(__file__).with_name('wire.py')))
wire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wire)
workspace = Path('/run/test/home/text-controls')
workspace.mkdir()
desk = SimpleNamespace(workspace=workspace, failures=[], allowed_ports=set())
wires = wire.Wires(desk, 'health-only')
try:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from urllib.error import URLError
    day = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    url = 'https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/' + day.isoformat() + '/transformed/nse_fo.csv'
    try:
        urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'FlintTrade/0.0.1 instrument-lot-excerpt'}), timeout=60)
    except URLError:
        pass
    else:
        raise AssertionError('Expected deliberate transport failure')
    assert not desk.failures, 'Authorised denial-only request must not be unregistered'
    refused = False
    try:
        urllib.request.urlopen(urllib.request.Request(wire.CSV_URL, method='POST'), timeout=60)
    except Exception:
        refused = True
    result = {'refused': refused, 'latched': list(desk.failures), 'rows': wires.rows}
    (OUT / 'text-controls.json').write_text(json.dumps(result, indent=2))
    assert refused and desk.failures, 'Dhan POST accepted: URL-only response matcher is permissive'
finally:
    wires.close()
