"""Review regressions: real dispatch with inert external transports/tools."""
from email.message import Message
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import yaml
from pathlib import Path
import runpy
import urllib.request
import urllib.response

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('redirect', [
    'https://example.invalid/archive.tgz',
    'http://registry.npmjs.org/archive.tgz',
    'https://user:pass@registry.npmjs.org/archive.tgz',
    'https://registry.npmjs.org:443/archive.tgz',
    'https://registry.npmjs.org./archive.tgz',
    '//example.invalid/archive.tgz',
    'https://registry.npmjs.org/archive.tgz#ambiguous',
    '/different-primary-archive.tgz',
])
def test_archive_redirect_is_refused_before_second_transport_contact(tmp_path, monkeypatch, redirect):
    module = runpy.run_path(str(ROOT / 'tools/reticle/acquire.py'))
    primary = 'https://registry.npmjs.org/synthetic/-/synthetic-1.tgz'
    contacts = []
    payload = b'inert transport archive'
    class MemoryTransport(urllib.request.HTTPSHandler):
        handler_order = 100
        def https_open(self, request):
            contacts.append(request.full_url)
            headers = Message()
            code = 302 if len(contacts) == 1 else 200
            if code == 302:
                headers['Location'] = redirect
            response = urllib.response.addinfourl(io.BytesIO(payload), headers, request.full_url, code)
            response.msg = 'synthetic'
            return response
        http_open = https_open
    original = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, '_opener', None)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: original(MemoryTransport(), *handlers))
    target = tmp_path / 'archive.tgz'
    with pytest.raises((RuntimeError, urllib.error.HTTPError)):
        module['download'](primary, 'sha256', hashlib.sha256(payload).digest(), target)
    assert contacts == [primary], 'Refusal must happen before a redirect target is contacted'
    assert not target.exists()


@pytest.mark.parametrize('url', [
    'http://registry.npmjs.org/a.tgz', 'https://example.invalid/a.tgz',
    'https://user:pass@registry.npmjs.org/a.tgz',
    'https://registry.npmjs.org:443/a.tgz', 'https://registry.npmjs.org./a.tgz',
    ' https://registry.npmjs.org/a.tgz', 'https://registry.npmjs.org/a.tgz#fragment',
    'https://registry.npmjs.org/a.tgz?other=identity',
    'https://registry.npmjs.org/a\ntgz',
])
def test_noncanonical_primary_identity_never_opens_transport(tmp_path, monkeypatch, url):
    module = runpy.run_path(str(ROOT / 'tools/reticle/acquire.py'))
    calls = []
    class Transport:
        def open(self, *args, **kwargs):
            calls.append(args)
            raise RuntimeError('transport contacted')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *handlers: Transport())
    with pytest.raises(RuntimeError):
        module['download'](url, 'sha256', b'0' * 32, tmp_path / 'no-archive')
    assert not calls, 'Reject ambiguous URL identity before contacting transport'


@pytest.mark.parametrize('denial', ['home', 'writable', 'optimisation'])
def test_native_public_dispatch_denies_unisolated_inputs_before_extension_import(tmp_path, denial):
    source = tmp_path / 'source'
    for name in ['scripts/ci_runtime.py', 'tools/acceptance/guard.py', 'tools/reticle/setup.py',
                 'tools/acceptance/native-build.txt', 'uv.lock']:
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    shutil.copytree(ROOT / 'packages/core/ticks', source / 'packages/core/ticks',
                    ignore=shutil.ignore_patterns('target', '__pycache__'))
    cli = source / 'scripts/ci_runtime.py'
    inputs = source / 'inputs.json'
    result = subprocess.run([sys.executable, cli, 'native-inputs', '--output', inputs], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    env = dict(os.environ, HOME='/run/test/home')
    if denial == 'home':
        env['HOME'] = str(tmp_path / 'ambient-home')
    args = [sys.executable, *(['-O'] if denial == 'optimisation' else []), cli, 'native',
            '--expected', '.'.join(map(str, sys.version_info[:3])), '--inputs', inputs,
            '--wheel', source / 'missing.whl']
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    message = {'home': 'Authorised isolated runner required',
               'writable': 'Read-only native input required',
               'optimisation': 'Python optimisation refused'}[denial]
    assert message in result.stderr, result.stderr
    assert 'ModuleNotFoundError' not in result.stderr


def test_native_acceptance_workflow_uses_existing_readonly_constructor():
    jobs = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())['jobs']
    steps = jobs['python-invariants']['steps']
    prep = next(step for step in steps if step.get('name') == 'Build and import current tick_engine')
    command = prep['run']
    assert 'tools/acceptance/isolated.py' in command, 'Native acceptance currently bypasses the isolation constructor'
    assert 'git archive HEAD' in command
    assert '--label native-acceptance' in command
    assert '--source "$source"' in command
    assert '--state-root "$state"' in command
    assert '.ci-inputs/ticks-inputs.json' in command
    assert '--publish' not in command


@pytest.mark.parametrize('filename', ['test_ci_acceptance_connection.py', 'test_ci_runtime_selection.py'])
def test_posix_only_probes_have_explicit_ubuntu_scope(filename):
    import ast
    tree = ast.parse((ROOT / 'tests' / filename).read_text())
    violations = []
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef) or not function.name.startswith('test_'):
            continue
        body = ast.unparse(function)
        posix = any(value in body for value in ["'/bin/sh'", "'/bin/bash'", '.chmod('])
        if posix and not any('skipif' in ast.unparse(d) and "sys.platform != 'linux'" in ast.unparse(d) for d in function.decorator_list):
            violations.append(function.name)
    assert not violations, 'Unscoped POSIX controls: ' + ', '.join(violations)


def test_locked_setup_composition_preserves_original_suites_and_selected_python():
    jobs = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())['jobs']
    for name in ['python-invariants', 'python-shards']:
        sync = next(s['run'] for s in jobs[name]['steps'] if s.get('run', '').startswith('uv sync '))
        assert '--python "${{ steps.runtime.outputs.python-path }}"' in sync
        assert '--frozen' in sync and '--extra migration' in sync
        if name == 'python-shards':
            assert '--extra ml' in sync
    steps = jobs['electron-desktop-tests']['steps']
    selected = [s for s in steps if s.get('id') == 'backend-python']
    assert len(selected) == 1, 'Electron normal-factory probe has no selected backend interpreter'
    assert "matrix.runtime == 'floor' && '3.12'" in selected[0]['with']['python-version']
    assert 'needs.changed-surfaces.outputs.python-current' in selected[0]['with']['python-version']
    prepare = next(s for s in steps if s.get('name') == 'Provision frozen Electron backend dependencies')
    assert '--python "${{ steps.backend-python.outputs.python-path }}" --frozen' in prepare['run']
    assert 'scripts/ci_runtime.py verify --tool python' in prepare['run']
    suite = next(s for s in steps if s.get('name') == 'Full Electron Vitest suite')
    assert steps.index(prepare) < steps.index(suite)
    assert suite['run'] == 'pnpm --filter @flinttrade/desktop test:electron'
    assert suite['env']['FLINTTRADE_TEST_PYTHON'] == '${{ github.workspace }}/.venv/bin/python'
    for command in ['pnpm --filter @flinttrade/desktop typecheck', 'pnpm --filter @flinttrade/desktop verify:package']:
        assert any(s.get('run') == command for s in steps)


@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu Actions native preparation shell; not native ABI proof')
@pytest.mark.parametrize('failure', ['', 'sync', 'build', 'pip', 'boundary'])
def test_native_workflow_public_shell_dispatch_stops_at_each_external_failure(tmp_path, failure):
    jobs = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())['jobs']
    step = next(s for s in jobs['python-invariants']['steps'] if s.get('name') == 'Build and import current tick_engine')
    command = step['run'].replace('${{ steps.runtime.outputs.python-path }}', sys.executable)
    command = command.replace("${{ matrix.runtime == 'floor' && '3.12' || needs.changed-surfaces.outputs.python-current }}", '.'.join(map(str, sys.version_info[:3])))
    seed = tmp_path / 'seed'
    for name in ['scripts/ci_runtime.py', 'uv.lock', 'tools/acceptance/native-build.txt']:
        dest = seed / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    shutil.copytree(ROOT / 'packages/core/ticks', seed / 'packages/core/ticks', ignore=shutil.ignore_patterns('target', '__pycache__'))
    # Public workflow and ci_runtime native-inputs are real. This inert external
    # constructor logs the eventual acceptance argv; it does NOT prove an ABI.
    (seed / 'tools/acceptance/isolated.py').write_text(
        "import json,os,sys\nfrom pathlib import Path\n"
        "with Path(os.environ['CALLS']).open('a') as f:f.write(json.dumps(['boundary',*sys.argv[1:]])+'\\n')\n"
        "sys.exit(37 if os.environ['FAIL']=='boundary' else 0)\n")
    shims = tmp_path / 'bin'
    shims.mkdir()
    tool = "#!" + sys.executable + "\n" + """import json,os,sys,tarfile
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
with Path(os.environ['CALLS']).open('a') as f:f.write(json.dumps([name,*args])+'\\n')
if name=='git':
    with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
        for p in Path(os.environ['SEED']).iterdir():archive.add(p,arcname=p.name)
elif name=='uv':
    if args[0]==os.environ['FAIL']:sys.exit(31)
    if args[0]=='sync':
        p=Path('.venv/bin');p.mkdir(parents=True);(p/'python').symlink_to(sys.executable)
    elif args[0]=='build':
        Path(args[args.index('--out-dir')+1],'inert.whl').write_bytes(b'not a native wheel')
"""
    for name in ['git', 'uv', 'pnpm', 'node']:
        (shims / name).write_text(tool)
        (shims / name).chmod(0o755)
    (shims / 'python').symlink_to(sys.executable)
    runner = tmp_path / 'runner'
    runner.mkdir()
    log = tmp_path / 'calls.jsonl'
    result = subprocess.run(['/bin/bash', '-euo', 'pipefail', '-c', command], cwd=seed,
                            env=dict(os.environ, RUNNER_TEMP=str(runner), PATH=str(shims) + os.pathsep + os.environ['PATH'],
                                     FAIL=failure, CALLS=str(log), SEED=str(seed)), capture_output=True, text=True)
    assert result.returncode == (37 if failure == 'boundary' else 31 if failure else 0), result.stdout + result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    stages = [row[1] for row in calls if row[0] == 'uv'] + ['boundary' for row in calls if row[0] == 'boundary']
    expected = ['sync', 'build', 'pip', 'boundary']
    assert stages == expected[:expected.index(failure) + 1] if failure else stages == expected
    if not failure or failure == 'boundary':
        boundary = next(row for row in calls if row[0] == 'boundary')
        assert boundary[boundary.index('--label') + 1] == 'native-acceptance'
        assert boundary[boundary.index('--source') + 1] == str(runner / 'native-source')
        assert boundary[boundary.index('--inputs') + 1] == str(runner / 'native-source/.ci-inputs/ticks-inputs.json')
        assert 'scripts/ci_runtime.py' in boundary and 'native' in boundary
