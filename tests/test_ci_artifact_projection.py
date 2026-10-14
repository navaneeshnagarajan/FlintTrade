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
REPORTS = [('e2e:default', 'default-vite-results.json'), ('e2e:default', 'csp-results.json'),
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
        if name.endswith('.xml'):
            bad = '<failure message="' + CANARY + '">' + CANARY + '</failure>' if failed else ''
            target.write_text(f'<testsuites tests="1" failures="{int(failed)}" errors="0" skipped="0"><testsuite tests="1" failures="{int(failed)}" errors="0" skipped="0"><testcase classname="{CANARY}" name="{CANARY}">{bad}<system-out>{CANARY}</system-out></testcase></testsuite></testsuites>')
        else:
            target.write_text(json.dumps({'suites': [{'specs': [{'file': CANARY, 'title': CANARY,
                'tests': [{'status': 'unexpected' if failed else 'expected', 'results': [{'status': 'failed' if failed else 'passed', 'retry': 0, 'error': CANARY, 'attachments': [CANARY]}]}]}]}],
                'errors': [], 'stats': {'expected': 0 if failed else 1, 'unexpected': 1 if failed else 0, 'flaky': 0, 'skipped': 0},
                'data': {'urlRaw': CANARIES[2], 'token': CANARIES[1], 'body': CANARIES[4], 'trace': CANARIES[3]}}))
    head = tmp_path / 'head.txt'
    head.write_text('a' * 40 + '\n')
    return state, run, head


def invoke(state, head, tmp_path):
    assert SCRIPT.is_file(), 'Missing fail-closed public-artifact projection'
    output = tmp_path / 'public-summary.json'
    result = subprocess.run([sys.executable, SCRIPT, '--state', state, '--head', head, '--output', output], capture_output=True, text=True)
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
    assert all(row['counts']['tests'] == 1 for row in summary['reports'])
    assert all(row['counts']['failed'] == int(failed) for row in summary['reports'])
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
