"""R62 additions over the unchanged original real-owner bootstrap."""

import sys
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location('original_r46_bootstrap', str(Path(__file__).with_name('base-bootstrap.py')))
original = importlib.util.module_from_spec(spec)
spec.loader.exec_module(original)
HeldSessionClock = original.HeldSessionClock
drain = original.drain


def bootstrap(server, output):
    original.bootstrap(server, output)
    scenario = os.environ.get('R46_SCENARIO', '')
    if not scenario.startswith('R62'):
        return
    from flinttrade_core.auth_routes import _create_token, decode_token, verify_operator_session_token
    path = Path('/run/test/bootstrap.json')
    state = json.loads(path.read_text())
    with server.app.app_context():
        replacement = _create_token('synthetic-operator')
        assert verify_operator_session_token(replacement).actor_ref == verify_operator_session_token(server.token).actor_ref
        try:
            verify_operator_session_token('demo-user')
        except Exception:
            refused = True
        else:
            refused = False
        assert refused, 'Preview must remain outside full-operator authority'
        claims = [decode_token(token) for token in (server.token, replacement)]
        assert len({claim['jti'] for claim in claims}) == 2
    state['replacement_session'] = {**state['session'], 'token': replacement}
    state['preview_session'] = {**state['session'], 'token': 'demo-user', 'username': 'Guest'}
    if 'protection requires canonical owned entry' in scenario:
        import asyncio
        owner = server.r46_registry.owners['r46-paper-a']
        before = {'positions': owner.sandbox.get_positions(), 'orders': owner.sandbox.get_all_orders(), 'trades': owner.sandbox.get_trades()}
        result = asyncio.run(owner.run.adapter.place_order(symbol='RELIANCE', exchange='NSE', product='MIS', action='BUY', quantity=1))
        after = {'positions': owner.sandbox.get_positions(), 'orders': owner.sandbox.get_all_orders(), 'trades': owner.sandbox.get_trades()}
        assert result['status'] == 'error', 'This diagnostic must not invent a successful owned position'
        assert before == after and not before['positions'] and not before['trades']
        assert not server.wires
        (output / 'r62-protection-precondition.json').write_text(json.dumps({'caller': 'actual held PracticeAgentSupervisor.run.adapter.place_order',
            'result': result, 'before': before, 'after': after, 'provider_calls': len(server.wires),
            'entries_armed': server.r46_registry.status(server.r46_registry.scope('r46-paper-a', state['runs'][0]['actor']))['entries_armed'],
            'qualification': 'Negative only. Approved-position grant/revoke/expiry/fixed reduction still missing; no raw sandbox fill or fabricated receipt.'}, indent=2))
    path.write_text(json.dumps(state))
    (output / 'r62-session-setup.json').write_text(json.dumps({
        'real_issuer': 'auth_routes._create_token', 'distinct_jtis': True,
        'replacement_same_actor': True, 'preview_refused_by_unchanged_verifier': refused,
        'preview': 'Existing demo-user presentation sentinel; not a signed session or authority',
        'modes': [claim['mode'] for claim in claims], 'provider_calls': len(server.wires),
    }, indent=2))
