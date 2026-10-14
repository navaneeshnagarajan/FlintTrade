"""Fresh-process adversaries and actual dependency import; no native bind."""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import json
import socket
from types import SimpleNamespace


def load(name):
    spec=importlib.util.spec_from_file_location(name, str(Path(__file__).with_name(name+'.py')))
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

case=sys.argv[1]
rows=[]; failures=[]
probe=load('probe').DenialProbe(failures, rows)
desk=SimpleNamespace(network=rows,failures=failures,allowed_ports=set())
load('network').install(desk)

def audit(event,args):
    probe.audit(event,args)
    if event in {'socket.bind','socket.connect','socket.getaddrinfo','urllib.Request'}:
        rows.append({'event':event,'expected_denial':False,'address':repr(args[1] if event.startswith('socket.') and event!='socket.getaddrinfo' else args)})
        failures.append(['unregistered',event])
        raise OSError('unregistered protocol refused before native operation')
sys.addaudithook(audit)

if case == 'unused':
    result=probe.complete()
    assert len(failures)==1 and result['expected_denials']==0
elif case == 'positive':
    import urllib3.util.connection as connection
    result=probe.complete()
    assert not failures, (failures,rows)
    assert connection.HAS_IPV6 is False and result['expected_denials']==1 and result['sockets_closed']
else:
    # A preexisting latch survives the later valid import; no clearing is used.
    if case == 'latched':
        failures.append(['prior-failure'])
    import urllib3.util.connection as connection
    if case == 'reload':
        import importlib
        importlib.reload(connection)
    elif case == 'repeat':
        assert connection._has_ipv6('::1') is False
    elif case == 'spoof-filename':
        ns={'socket':socket}
        exec(compile("def _has_ipv6(host):\n    with socket.socket(socket.AF_INET6) as s:\n        s.bind((host,0))\n",str(probe.path),'exec'),ns)
        try: ns['_has_ipv6']('::1')
        except OSError: pass
    elif case == 'latched':
        pass
    elif case == 'dns':
        try: socket.getaddrinfo('unregistered.invalid',443)
        except OSError: pass
    else:
        family=socket.AF_INET if case=='wrong-family' else socket.AF_INET6
        kind=socket.SOCK_DGRAM if case=='wrong-type' else socket.SOCK_STREAM
        protocol=socket.IPPROTO_TCP if case=='wrong-protocol' else 0
        with socket.socket(family,kind,protocol) as sock:
            address={'wrong-family':('127.0.0.1',0),'wrong-address':('::',0),
                     'wrong-port':('::1',5100),'wrong-shape':('::1',0,0,0)}.get(case,('::1',0))
            try:
                if case=='connect': sock.connect(('::1',5100))
                elif case=='listen': sock.listen(1)
                elif case=='accept': sock.accept()
                else: sock.bind(address)
            except OSError: pass
    result=probe.complete()
    assert result['expected_denials']==1 and len(failures)==1, (case,failures,rows)
    assert result['sockets_closed']
Path('/run/test/artifacts/probe-'+case+'.json').write_text(json.dumps({'case':case,'rows':rows,'failures':failures,'result':result},indent=2))
print('PROBE_CONTROL',case,'PASS')
