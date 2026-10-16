"""Only a numeric, schema-checked projection may cross the raw-custody boundary."""
import json
from pathlib import Path
import subprocess
import sys
import runpy

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/ci_artifact_projection.py'
LANES = ['e2e:maintained:contracts', 'e2e:infra:typecheck', 'e2e:infra:lint',
         'e2e:maintained:collect', 'e2e:reticle:collect', 'e2e:default',
         'e2e:public-demo', 'e2e:incidents', 'e2e:oauth', 'e2e:reticle:controls',
         'e2e:reticle', 'e2e:policy', 'e2e:paper']
REPORTS = [('e2e:default', 'default-infra-results.json'), ('e2e:default', 'default-vite-results.json'), ('e2e:default', 'csp-results.json'),
           ('e2e:incidents', 'incidents/report.xml'), ('e2e:oauth', 'oauth.xml'),
           ('e2e:reticle', 'results.xml'), ('e2e:policy', 'results.xml')]
# Synthetic canaries, not operator material. Never copy these fields to output.
CANARY = 'private-canary:token-body-wire-url-operator-path'
CANARIES = [CANARY, 'Bearer synthetic-private-token', 'https://example.invalid/private-wire',
            '/' + '/'.join(['home', 'synthetic-operator', 'private-file']), 'raw-wire-body-canary']


def fixture(tmp_path, failed=False):
    state = tmp_path / 'state'
    run = state / 'flinttrade-maintained-acceptance-fixture'
    (state / 'runs').mkdir(parents=True)
    for lane in LANES:
        (run / 'e2e-evidence' / lane).mkdir(parents=True)
    (run / 'artifacts').mkdir()
    receipt = {'label': 'maintained-acceptance', 'exit_code': 19 if failed else 0,
               'isolation_guard_passed': True, 'run_directory': str(run),
               'command': [CANARY], 'error': CANARY, 'log': CANARY}
    (state / 'runs/maintained-acceptance-fixture.json').write_text(json.dumps(receipt))
    for lane, name in REPORTS:
        target = run / 'e2e-evidence' / lane / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if name == 'default-infra-results.json':
            from types import SimpleNamespace
            carrier = SimpleNamespace(**runpy.run_path(str(ROOT/'tools/acceptance/csp.py')))
            value = runpy.run_path(str(ROOT/'tools/acceptance/tests/report_fixtures.py'))['infra_report'](carrier)
            value['private'] = CANARIES
            target.write_text(json.dumps(value))
        elif name.endswith('.xml'):
            bad = '<failure message="' + CANARY + '">' + CANARY + '</failure>' if failed else ''
            target.write_text(f'<testsuites tests="1" failures="{int(failed)}" errors="0" skipped="0"><testsuite tests="1" failures="{int(failed)}" errors="0" skipped="0"><testcase classname="{CANARY}" name="{CANARY}">{bad}<system-out>{CANARY}</system-out></testcase></testsuite></testsuites>')
        else:
            target.write_text(json.dumps({'suites': [{'specs': [{'file': CANARY, 'title': CANARY,
                'tests': [{'status': 'unexpected' if failed else 'expected', 'results': [{'status': 'failed' if failed else 'passed', 'retry': 0, **({'error': CANARY} if failed else {}), 'attachments': [CANARY]}]}]}]}],
                'errors': [], 'stats': {'expected': 0 if failed else 1, 'unexpected': 1 if failed else 0, 'flaky': 0, 'skipped': 0},
                'data': {'urlRaw': CANARIES[2], 'token': CANARIES[1], 'body': CANARIES[4], 'trace': CANARIES[3]}}))
    head = tmp_path / 'head.txt'
    head.write_text('a' * 40 + '\n')
    return state, run, head


def invoke(state, head, tmp_path):
    assert SCRIPT.is_file(), 'Missing fail-closed public-artifact projection'
    output = tmp_path / 'public-summary.json'
    result = subprocess.run([sys.executable, SCRIPT, '--state', state, '--head', head, '--output', output, '--browser-source', ROOT], capture_output=True, text=True)
    assert output.is_file(), result.stderr
    raw = output.read_text()
    assert not any(value in raw + result.stdout + result.stderr for value in CANARIES)
    assert str(tmp_path) not in raw
    return result, json.loads(raw)


@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu raw lane directories contain colons; schema controls run on every platform')
@pytest.mark.parametrize('failed', [False, True])
def test_projection_keeps_truthful_outcomes_but_never_raw_fields(tmp_path, failed):
    state, run, head = fixture(tmp_path, failed)
    before = {p.relative_to(state).as_posix(): p.read_bytes() for p in state.rglob('*') if p.is_file()}
    result, summary = invoke(state, head, tmp_path)
    assert result.returncode == 0
    assert summary['exit_code'] == (19 if failed else 0)
    assert summary['projection_valid'] is True
    assert summary['acceptance_verified'] is False
    assert len(summary['reports']) == len(REPORTS)
    infra = next(row for row in summary['reports'] if row['report'] == 'default-infra')
    assert infra['counts'] == {'tests':185, 'passed':183, 'failed':2, 'expected_failed':2, 'errors':0, 'skipped':0}
    assert all(row['counts']['tests'] == 1 for row in summary['reports'] if row != infra)
    assert all(row['counts']['failed'] == int(failed) for row in summary['reports'] if row != infra)
    assert before == {p.relative_to(state).as_posix(): p.read_bytes() for p in state.rglob('*') if p.is_file()}


@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu raw lane directories contain colons; schema controls run on every platform')
@pytest.mark.parametrize('mutant', ['missing', 'totals', 'invalid-json', 'invalid-xml', 'receipt', 'head', 'symlink', 'scalar-spec', 'numeric-canary'])
def test_missing_or_inconsistent_evidence_cannot_be_reported_as_zero(tmp_path, mutant):
    state, run, head = fixture(tmp_path)
    target = run / 'e2e-evidence/e2e:policy/results.xml'
    if mutant == 'missing':
        target.unlink()
    elif mutant == 'totals':
        target.write_text(target.read_text().replace('tests="1"', 'tests="2"'))
    elif mutant == 'invalid-json':
        (run / 'e2e-evidence/e2e:default/csp-results.json').write_text('{bad')
    elif mutant in {'scalar-spec', 'numeric-canary'}:
        report = run / 'e2e-evidence/e2e:default/csp-results.json'
        value = json.loads(report.read_text())
        if mutant == 'scalar-spec':
            value['suites'][0]['specs'] = [CANARY]
        else:
            value['stats']['expected'] = CANARY
        report.write_text(json.dumps(value))
    elif mutant == 'invalid-xml':
        target.write_text('<!DOCTYPE x [<!ENTITY bad "raw">]><testsuites/>')
    elif mutant == 'receipt':
        (state / 'runs/maintained-acceptance-fixture.json').unlink()
    elif mutant == 'head':
        head.write_text(CANARY)
    else:
        target.unlink()
        try:
            target.symlink_to(head)
        except OSError:
            pytest.skip('OS does not grant symlink creation; other path controls still execute')
    result, summary = invoke(state, head, tmp_path)
    assert result.returncode != 0
    assert summary['projection_valid'] is False
    if mutant in {'missing', 'totals', 'invalid-json', 'invalid-xml', 'symlink'}:
        assert any(row['counts'] is None and row['status'] in {'missing', 'invalid'} for row in summary['reports'])
    if mutant == 'receipt':
        assert summary['exit_code'] is None


def test_colon_fixture_consumers_keep_exact_linux_scope():
    """The CLI consumes literal Ubuntu lane paths, not portable aliases."""
    import ast
    tree = ast.parse(Path(__file__).read_text())
    consumers = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name.startswith('test_') and any(
                     isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                     and call.func.id == 'fixture' for call in ast.walk(node))]
    assert len(consumers) == 3
    for node in consumers:
        assert any(isinstance(mark, ast.Call) and isinstance(mark.func, ast.Attribute)
                   and mark.func.attr == 'skipif' and mark.args
                   and ast.unparse(mark.args[0]) == "sys.platform != 'linux'"
                   for mark in node.decorator_list), node.name


@pytest.mark.parametrize('mutation', ['foreign-path', 'self-declared-root', 'teardown-position', 'auto-position'])
def test_native_negative_provenance_uses_independent_source_context(mutation):
    import re
    from types import SimpleNamespace
    carrier = SimpleNamespace(**runpy.run_path(str(ROOT/'tools/acceptance/csp.py')))
    report = runpy.run_path(str(ROOT/'tools/acceptance/tests/report_fixtures.py'))['infra_report'](carrier)
    for spec in report['suites'][0]['specs']:
        test = spec['tests'][0]
        if test['expectedStatus'] != 'failed':
            continue
        result = test['results'][0]
        old = result['error']['location']['file']
        for error in [result['error'], *result['errors']]:
            if mutation in {'foreign-path', 'self-declared-root'}:
                error['location']['file'] = '/foreign/e2e/fixture-registry.ts'
                for key in ['message', 'stack']:
                    if key in error:
                        error[key] = error[key].replace(old, '/foreign/e2e/fixture-registry.ts')
            else:
                owner = 'FailClosedSyntheticFixtureRegistry.disposeOnce' if mutation == 'teardown-position' else 'Object.baseTest.extend.syntheticApi.auto'
                for key in ['message', 'stack']:
                    if key in error:
                        error[key] = re.sub(
                            r'(    at ' + re.escape(owner) + r' \([^\n]+):[0-9]+:[0-9]+\)',
                            r'\1:1:1)',
                            error[key],
                        )
    if mutation == 'self-declared-root':
        report['config']['rootDir'] = '/foreign/e2e'
    with pytest.raises(ValueError):
        runpy.run_path(str(SCRIPT))['playwright_counts'](report, infrastructure=True)


def test_workflow_upload_is_one_explicit_projection_not_a_raw_directory():
    steps = yaml.safe_load((ROOT / '.github/workflows/test.yml').read_text())['jobs']['terminal-e2e-infra-self-tests']['steps']
    upload = next(s for s in steps if s.get('name') == 'Upload maintained acceptance evidence')
    assert upload['with']['path'] == '${{ runner.temp }}/public-evidence/maintained-summary.json'
    project = next(s for s in steps if s.get('name') == 'Project publishable acceptance summary')
    assert project['if'] == "always() && matrix.runtime == 'current'"
    assert 'ci_artifact_projection.py' in project['run']
    assert 'continue-on-error' not in project


def test_pytest_junit_root_without_aggregate_attributes_keeps_child_counts():
    module = runpy.run_path(str(SCRIPT))
    raw = '<testsuites><testsuite tests="3" failures="1" errors="1" skipped="0"><testcase/><testcase><failure>private</failure></testcase><testcase><error>private</error></testcase></testsuite></testsuites>'
    assert module['junit_counts'](raw) == {'tests': 3, 'passed': 1, 'failed': 1, 'errors': 1, 'skipped': 0}


@pytest.mark.parametrize('infrastructure', [False, True])
@pytest.mark.parametrize('field', ['error', 'errors', 'both'])
def test_ordinary_pass_errors_are_never_projected_as_zero(infrastructure, field):
    from types import SimpleNamespace
    carrier = SimpleNamespace(**runpy.run_path(str(ROOT/'tools/acceptance/csp.py')))
    report = runpy.run_path(str(ROOT/'tools/acceptance/tests/report_fixtures.py'))['infra_report'](carrier)
    if not infrastructure:
        report['suites'][0]['specs'] = [s for s in report['suites'][0]['specs'] if s['tests'][0]['expectedStatus'] == 'passed']
        report['stats']['expected'] = len(report['suites'][0]['specs'])
    test = next(s['tests'][0] for s in report['suites'][0]['specs'] if s['tests'][0]['expectedStatus'] == 'passed')
    if field in {'error', 'both'}:
        test['results'][0]['error'] = {'message': CANARY}
    if field in {'errors', 'both'}:
        test['results'][0]['errors'] = [{'message': CANARY}]
    with pytest.raises(ValueError):
        runpy.run_path(str(SCRIPT))['playwright_counts'](report, infrastructure=infrastructure)


@pytest.mark.skipif(sys.platform != 'linux', reason='Ubuntu raw lane directories contain colons; schema controls run on every platform')
@pytest.mark.parametrize('mutation', ['missing', 'unknown-control', 'wrong-cause', 'extra-error', 'unexpected-pass', 'missing-attachment', 'duplicate', 'ordinary-failure', 'app-expected-failure'])
def test_expected_infrastructure_failures_are_not_a_general_failure_allowance(tmp_path, mutation):
    state, run, head = fixture(tmp_path)
    path = run/'e2e-evidence/e2e:default/default-infra-results.json'
    report = json.loads(path.read_text())
    specs = report['suites'][0]['specs']
    negative = next(s for s in specs if s['tests'][0]['expectedStatus'] == 'failed')
    test = negative['tests'][0]
    result = test['results'][0]
    if mutation == 'missing':
        path.unlink()
    elif mutation == 'unknown-control':
        negative['title'] += ' unknown'
    elif mutation == 'wrong-cause':
        result['error']['message'] = 'Error: EADDRINUSE'
    elif mutation == 'extra-error':
        result['errors'].append({'message': CANARY})
    elif mutation == 'unexpected-pass':
        result['status'] = 'passed'
    elif mutation == 'missing-attachment':
        result['attachments'] = []
    elif mutation == 'duplicate':
        specs.append(negative)
        report['stats']['expected'] += 1
    elif mutation == 'ordinary-failure':
        test = next(s for s in specs if s['tests'][0]['expectedStatus'] == 'passed')['tests'][0]
        test.update(status='unexpected')
        test['results'][0]['status'] = 'failed'
        report['stats']['expected'] -= 1
        report['stats']['unexpected'] += 1
    elif mutation == 'app-expected-failure':
        app = run / 'e2e-evidence/e2e:default/default-vite-results.json'
        value = json.loads(app.read_text())
        value['suites'][0]['specs'][0]['tests'] = [test]
        app.write_text(json.dumps(value))
    if mutation != 'missing':
        path.write_text(json.dumps(report))
    result, summary = invoke(state, head, tmp_path)
    assert result.returncode != 0
    assert summary['projection_valid'] is False
    assert summary['acceptance_verified'] is False
