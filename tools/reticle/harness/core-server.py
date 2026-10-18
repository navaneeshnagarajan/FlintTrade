"""Normal factory and owned Waitress listener; only external I/O is inert."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import uuid

OUT = Path('/run/test/artifacts')


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def redact(value):
    if isinstance(value, dict):
        return {k: '<redacted-synthetic>' if k.lower() in {'credential', 'authorization', 'token', 'password', 'api_key'} else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


class CoreServer:
    def __init__(self, port: int):
        assert str(Path.home()) == '/run/test/home'
        self.port = port
        self.rows = []
        self.wires = []
        self.lock = threading.Lock()
        self.initial_threads = {t.ident for t in threading.enumerate()}
        import sys
        self.network_attempts = []
        def network_audit(event, args):
            if event == 'socket.connect':
                address = args[1]
                allowed = isinstance(address, tuple) and address[0] == '127.0.0.1' and address[1] == self.port
                self.network_attempts.append({'event': event, 'address': list(address) if isinstance(address, tuple) else str(address), 'allowed': allowed})
                (OUT / 'python-network-attempts.json').write_text(json.dumps(self.network_attempts, indent=2))
                if not allowed:
                    raise RuntimeError('Non-owned external transport attempted')
        sys.addaudithook(network_audit)
        case_key = os.environ['R24_CASE_KEY']
        assert len(case_key) == 64 and all(c in '0123456789abcdef' for c in case_key)
        os.environ['FLINTTRADE_WORKSPACE_DIR'] = '/run/test/home/workspaces/' + case_key
        os.environ['FLINTTRADE_API_KEY'] = secrets.token_urlsafe(32)
        os.environ['FLINTTRADE_FRONTEND_DIST'] = '/run/test/artifacts/installed-dist'
        workspace = Path(os.environ['FLINTTRADE_WORKSPACE_DIR'])
        workspace.mkdir(mode=0o700, parents=True)
        master = workspace / 'master_password'
        master.write_text(secrets.token_urlsafe(48))
        master.chmod(0o600)
        from flinttrade_core.app import create_flask_app, _run_flask_server
        from flinttrade_core import auth_routes
        import httpx
        from flask import request

        self.app = app = create_flask_app()
        source_root = Path(os.environ.get('FLINTTRADE_E2E_SOURCE_ROOT', Path(__file__).resolve().parents[3])).resolve()
        origins = {name: str(getattr(mod, '__file__', '')) for name, mod in sys.modules.items() if name.startswith(('flinttrade_', 'packages.')) and getattr(mod, '__file__', None)}
        (OUT / 'python-source-origins.json').write_text(json.dumps(origins, indent=2))
        if any(path.endswith('.py') and not Path(path).resolve().is_relative_to(source_root) for path in origins.values()):
            raise RuntimeError('Python source escaped the current application inventory')
        # No fake safety, ready account, scope resolver or auth verifier.
        assert not app.config['BACKEND_LEASE_READY']
        assert app.config['DATA_RUNTIME'].active_sources == 0
        assert 'SERVICE_TASK_DISPATCHER' not in app.config
        app.config['AUTH_SERVICE'].setup_account('synthetic-operator', 'synthetic@example.invalid', secrets.token_urlsafe(32))
        with app.app_context():
            token = auth_routes._create_token('synthetic-operator')
            expiry = auth_routes._next_8am_ist().isoformat() + '+00:00' if auth_routes._next_8am_ist().tzinfo is None else auth_routes._next_8am_ist().isoformat()
        self.token = token
        self.credential = secrets.token_urlsafe(32)

        @app.after_request
        def record(response):
            if not request.path.startswith(('/v1/', '/api/', '/health')):
                return response
            body = request.get_data(cache=True)
            response_body = response.get_data() if not response.is_streamed else b''
            row = {'method': request.method, 'path': request.full_path.removesuffix('?'),
                   'body_sha256': digest(body), 'body': redact(request.get_json(silent=True)),
                   'authorization_sha256': digest(request.headers.get('Authorization', '').encode()),
                   'if_match': request.headers.get('If-Match'), 'idempotency_key': request.headers.get('Idempotency-Key'),
                   'status': response.status_code, 'response_sha256': digest(response_body),
                   'response': redact(response.get_json(silent=True)) if not response.is_streamed else None,
                   'etag': response.headers.get('ETag'), 'trial': response.headers.get('X-Trial-Id'), 'experiment': response.headers.get('X-Experiment-Id')}
            with self.lock:
                self.rows.append(row)
                (OUT / 'core-http-ledger.json').write_text(json.dumps(self.rows, indent=2))
            return response

        def external_transport(request):
            assert request.method == 'POST'
            assert str(request.url) == 'https://openrouter.ai/api/v1/chat/completions'
            assert request.headers['authorization'] == 'Bearer ' + self.credential
            body = json.loads(request.content)
            assert body['model'] == 'test-model-v1'
            assert body['max_tokens'] == 256
            assert body['provider']['allow_fallbacks'] is False
            assert 'tools' not in body
            assert body['messages'][0]['content'].endswith(self.procedure)
            self.wires.append({'method': request.method, 'url': str(request.url), 'body': body, 'body_sha256': digest(request.content), 'credential_matched': True})
            (OUT / 'external-transport-ledger.json').write_text(json.dumps(self.wires, indent=2))
            return httpx.Response(200, json={'id': 'synthetic-inert-result', 'model': 'test-model-v1',
                'choices': [{'message': {'content': 'Synthetic external transport: procedure received; no model ran.'}, 'finish_reason': 'stop'}],
                'provider': 'approved-upstream', 'usage': {'prompt_tokens': 12, 'completion_tokens': 5}})

        app.config['SERVICE_TASK_TRANSPORT'] = httpx.MockTransport(external_transport)
        # Publish through the app-owned pipeline with the actual verified scope.
        from packages.core.historical.tests.test_history_manifest import history_input
        identity, _, policy, contributors = history_input()
        with app.test_request_context(headers={'Authorization': 'Bearer ' + token}):
            scope = app.config['DATA_SCOPE_RESOLVER']()
        self.manifest = app.config['HISTORY_PIPELINE'].publish_history(identity=identity, scope=scope, policy=policy, contributors=contributors)
        (OUT / 'published-history.json').write_text(json.dumps(self.manifest, indent=2))
        self.owner = _run_flask_server(app, port=port, host='127.0.0.1')
        client = httpx.Client(base_url=f'http://127.0.0.1:{port}', headers={'Authorization': 'Bearer ' + token}, trust_env=False, timeout=20)
        self.client = client
        assert client.get('/api/v1/data/datasets').status_code == 200
        native_refusal = client.post('/api/v1/native/accounts', json={
            'adapter_id': 'dhan', 'account_id': 'synthetic-unavailable', 'credentials': {}})
        assert native_refusal.status_code == 503
        assert native_refusal.json() == {'error': 'broker_account_cutover_unavailable'}
        assert native_refusal.headers['cache-control'] == 'no-store'
        (OUT / 'native-cutover-control.json').write_text(json.dumps({'kind': 'fixture-setup real HTTP control, not a UI click',
            'status': native_refusal.status_code, 'body': native_refusal.json(), 'native_credentials_supplied': False}, indent=2))
        base = '/v1/services/connections'
        revision = client.get(base).headers['etag']
        created = client.post(base, headers={'If-Match': revision, 'Idempotency-Key': str(uuid.uuid4())}, json={
            'provider_id': 'llm:openrouter', 'model': 'test-model-v1', 'label': 'Synthetic inert task destination',
            'auth_mode': 'api_key', 'credential': self.credential})
        assert created.status_code == 201, created.text
        self.connection_id = created.json()['connection_id']
        from packages.core.core.tests.test_service_tasks import policy as task_policy
        value = task_policy(created.headers['etag'])
        value['reservation']['input_tokens'] = 8192  # full bundled body and actual provider envelope, synthetic only
        value['reservation']['currency_micros'] = 1000  # conservatively tariff-covered synthetic reservation
        now = datetime.now(UTC)
        end = now + timedelta(hours=1)
        value['entitlement']['expires_at'] = end.isoformat()
        value['tariff'].update(effective_from=now.isoformat(), effective_until=end.isoformat())
        value['budget'].update(window_start=now.isoformat(), window_end=end.isoformat())
        group = client.put(base + '/quota-groups/synthetic-shared-account', headers={'If-Match': '"0"'}, json=value['budget'])
        assert group.status_code == 200, group.text
        configured = client.put(base + '/' + self.connection_id + '/admission', headers={'If-Match': '"0"'}, json=value)
        assert configured.status_code == 200, configured.text
        procedure = client.get('/v1/knowledge/skills/risk_management')
        assert procedure.status_code == 200, procedure.text
        self.procedure = procedure.json()['body']
        assert self.wires == []
        bootstrap = {'session': {'token': token, 'username': 'synthetic-operator', 'expiresAt': expiry},
                     'connection_id': self.connection_id, 'snapshot_id': self.manifest['snapshot_id'],
                     'baseURL': f'http://127.0.0.1:{port}'}
        state = Path(os.environ['FLINTTRADE_E2E_CORE_STATE'])
        state.write_text(json.dumps(bootstrap))
        state.chmod(0o600)
        (OUT / 'startup.json').write_text(json.dumps({'factory': 'flinttrade_core.app.create_flask_app', 'listener': 'owned Waitress',
            'full_operator_session': True, 'backend_broker_lease_ready': app.config['BACKEND_LEASE_READY'],
            'provider_calls_during_startup': len(self.wires), 'no_real_accounts': True,
            'configuration': redact(value), 'scope': scope, 'listener_port': port,
            'case_key': case_key, 'pid': os.getpid(), 'workspace': str(workspace),
            'http_limiter_enabled': app.config.get('RATELIMIT_ENABLED', True)}, indent=2))

    def close(self):
        from flinttrade_core.app import _close_runtime_request_admission
        tracker = _close_runtime_request_admission(self.app)
        drained = tracker.wait_for_idle(timeout=10) if hasattr(tracker, 'wait_for_idle') else None
        if hasattr(self, 'client'):
            self.client.close()
        stopped = self.owner.stop(timeout=10) if hasattr(self, 'owner') else True
        result = {'admission_drained': drained, 'listener_stopped': stopped, 'owners': {}}
        for key in ('EXECUTION_SESSION_MANAGER', 'MODEL_RUN_SERVICES', 'DATA_RUNTIME', 'LEARNING_CONSENT_LEDGER', 'KNOWLEDGE_RUNTIME', 'SERVICE_TASK_DISPATCHER'):
            owner = self.app.config.get(key)
            if owner is not None:
                try:
                    answer = owner.close()
                    result['owners'][key] = {'closed': answer is not False}
                except Exception as exc:
                    result['owners'][key] = {'closed': False, 'error': type(exc).__name__}
        result['remaining_threads'] = [t.name for t in threading.enumerate() if t.ident not in self.initial_threads]
        with socket.socket() as check:
            result['listener_closed_probe'] = check.connect_ex(('127.0.0.1', self.port)) != 0
        (OUT / 'shutdown.json').write_text(json.dumps(result, indent=2))
        assert result['admission_drained'] and result['listener_stopped'] and result['listener_closed_probe']
        assert not result['remaining_threads'], result
        assert all(row['closed'] for row in result['owners'].values()), result
        return result


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, required=True, choices=[5100, 5173])
    parser.add_argument('--case-key', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.output.is_relative_to('/run/test/artifacts/playwright')
    OUT = args.output
    OUT.mkdir(parents=True, exist_ok=False)
    os.environ['R24_CASE_KEY'] = args.case_key
    with socket.socket() as check:
        # Permit only the previous owned listener's TIME_WAIT sockets, never a
        # concurrently listening process (SO_REUSEPORT remains disabled).
        check.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        check.bind(('127.0.0.1', args.port))
    server = CoreServer.__new__(CoreServer)
    try:
        server.__init__(args.port)
        print('R24_CORE_READY', flush=True)
        assert sys.stdin.readline().strip() == 'STOP', 'owned fixture ended without STOP'
    finally:
        if hasattr(server, 'app'):
            server.close()
