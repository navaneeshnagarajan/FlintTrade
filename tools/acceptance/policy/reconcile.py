"""Strict accounting for actual isolated R62 artifacts, no inferred passes."""

import sys
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
from collections import Counter
import hashlib
import json
from pathlib import Path
# Share the carrier's pre-parse DTD/entity denial, including encoding guards.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'reticle'))
from validate_results import parse_junit

OUT = Path('/run/test/artifacts')

def load(path):
    return json.loads(path.read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reconcile():
    report = load(OUT / 'results.json')
    cases = []
    def visit(suites):
        for suite in suites:
            for spec in suite.get('specs', []):
                for test in spec['tests']:
                    for result in test['results']:
                        cases.append({'name': spec['title'], 'file': spec['file'], 'expected': test['expectedStatus'],
                            'status': result['status'], 'retry': result['retry'], 'errors': result.get('errors', [])})
            visit(suite.get('suites', []))
    visit(report['suites'])
    xml = parse_junit(OUT / 'results.xml')
    nodes = list(xml.iter('testcase'))
    assert len(nodes) == len(cases) == int(xml.attrib['tests'])
    assert len(cases) == sum(report['stats'][key] for key in ('expected', 'unexpected', 'skipped', 'flaky'))
    failures = sum(n.find('failure') is not None for n in nodes)
    errors = sum(n.find('error') is not None for n in nodes)
    assert failures == int(xml.attrib['failures']) and errors == int(xml.attrib.get('errors', 0))
    assert all(c['retry'] == 0 for c in cases)
    keys = [(c['file'], c['name']) for c in cases]
    assert len(keys) == len(set(keys)), 'Duplicate registered cases'
    original = [c for c in cases if c['name'].startswith('R46 ')]
    required = [c['name'] for c in load(Path(__file__).with_name('original-cases.json'))['cases']]
    original_full = Counter(c['name'] for c in original) == Counter(required)
    result = {'count': len(cases), 'actual_statuses': dict(Counter(c['status'] for c in cases)),
        'expected_failures_actual': sum(c['expected'] == 'failed' and c['status'] == 'failed' for c in cases),
        'junit': xml.attrib, 'child_failures': failures, 'child_errors': errors, 'cases': cases,
        'original24_set_complete': original_full,
        'original24_all_pass': original_full and all(c['status'] == 'passed' for c in original),
        'retries': sum(c['retry'] for c in cases), 'stats': report['stats']}
    lifetimes, byte_reports, geometries, actions, workflows = [], [], [], set(), set()
    for case_dir in sorted((OUT / 'playwright').glob('*')):
        if not case_dir.is_dir():
            continue
        for start in [case_dir / 'normal-core/startup.json', case_dir / 'replacement-core/startup.json']:
            if not start.exists():
                continue
            shutdown_path = start.with_name('shutdown.json')
            shutdown = load(shutdown_path) if shutdown_path.exists() else None
            record = {'startup': load(start), 'shutdown': shutdown}
            if shutdown:
                record['clean'] = all(shutdown.get(k) is True for k in ('admission_drained', 'listener_stopped', 'listener_closed_probe')) and shutdown['remaining_threads'] == [] and all(v['closed'] for v in shutdown['owners'].values())
            lifetimes.append(record)
        path = case_dir / 'core-relay-ledger.json'
        if not path.exists():
            continue
        relay = load(path)
        native = []
        for root in ('normal-core', 'replacement-core'):
            ledger = case_dir / root / 'core-http-ledger.json'
            if ledger.exists():
                native.extend(load(ledger))
        def rk(row):
            return (row['method'], row['path'], row['bodySha256'], row['status'], row['responseSha256'])
        nc = Counter((r['method'], r['path'], r['body_sha256'], r['status'], r['response_sha256']) for r in native)
        rc = Counter(rk(r) for r in relay)
        core_missing = list((rc - nc).elements())
        browser = load(case_dir / 'browser-completed-bodies.json')
        completed = [r for r in browser if r['completed']]
        bc = Counter(rk(r) for r in completed)
        expected_browser = rc.copy()
        faults = []
        fault_path = case_dir / 'malformed-ack-fault.json'
        if fault_path.exists():
            fault = load(fault_path)
            assert fault['count'] == 1 and fault['originalSha256'] != fault['alteredSha256']
            assert sha(case_dir / 'malformed-ack-original.txt') == fault['originalSha256']
            assert sha(case_dir / 'malformed-ack-browser.txt') == fault['alteredSha256']
            matches = [r for r in relay if r['method'] == fault['method'] and r['path'] == fault['path']]
            assert len(matches) == 1 and matches[0]['responseSha256'] == fault['originalSha256']
            healthy = rk(matches[0]); altered = (*healthy[:-1], fault['alteredSha256'])
            expected_browser[healthy] -= 1; expected_browser[altered] += 1
            assert bc[altered] == 1
            faults.append(fault)
        extras = list((bc - expected_browser).elements())
        undelivered = list((expected_browser - bc).elements())
        console = load(case_dir / 'browser-console.json')
        from urllib.parse import urlsplit
        cancellations = Counter((r['method'], urlsplit(r['url']).path + ('?' + urlsplit(r['url']).query if urlsplit(r['url']).query else ''))
            for r in console if 'method' in r and r.get('failure', {}).get('errorText') == 'net::ERR_ABORTED')
        missing_requests = Counter((r[0], r[1]) for r in undelivered)
        cancellation_matched = not bool(missing_requests - cancellations)
        byte_reports.append({'case_directory': case_dir.name, 'relay': len(relay), 'native': len(native), 'browser_completed': len(completed),
            'core_missing': core_missing, 'browser_unmatched': extras, 'undelivered': undelivered, 'faults': faults, 'undelivered_native_cancellation_matched': cancellation_matched})
        for row in relay:
            if row['method'] == 'POST' and row['path'].endswith('/configuration/confirm') and row['status'] == 200:
                action = row['body']['action']; actions.add(action)
                workflows.add(action + (':' + row['body']['value']['subject'] if action == 'learning-rights' else ''))
        for path in case_dir.glob('*.literal-geometry.json'):
            observation = load(path)
            geometries.append({'path': str(path.relative_to(OUT)), 'sha256': sha(path), 'complete': observation['complete'],
                'painted': observation['painted'], 'visible': observation.get('visible'), 'literal': observation['literal']})
    result['lifetimes'] = lifetimes
    result['factory_process_count'] = len(lifetimes)
    result['all_lifetimes_clean'] = bool(lifetimes) and all(item.get('clean') for item in lifetimes)
    result['distinct_factory_pids'] = len({row['startup']['pid'] for row in lifetimes})
    result['distinct_workspaces'] = len({row['startup']['workspace'] for row in lifetimes})
    result['bytes'] = byte_reports
    result['relay_rows'] = sum(r['relay'] for r in byte_reports)
    result['completed_browser_rows'] = sum(r['browser_completed'] for r in byte_reports)
    result['healthy_core_correspondence'] = all(not r['core_missing'] for r in byte_reports)
    result['browser_correspondence_with_declared_fault'] = all(not r['browser_unmatched'] for r in byte_reports)
    result['intentional_corrupt_ack_count'] = sum(len(r['faults']) for r in byte_reports)
    result['configuration_actions'] = sorted(actions)
    result['configuration_workflows'] = sorted(workflows)
    result['strict_literal_geometry'] = geometries
    result['all_recorded_literal_geometry_pass'] = all(r['complete'] and r['painted'] and r['visible'] is not False for r in geometries)
    (OUT / 'r62-accounting.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ('cases', 'lifetimes', 'bytes', 'strict_literal_geometry')}, indent=2))
    if report['stats']['unexpected'] == 0 and lifetimes:
        assert result['all_lifetimes_clean'] and result['healthy_core_correspondence'] and result['browser_correspondence_with_declared_fault']
        assert all(r['undelivered_native_cancellation_matched'] for r in byte_reports)
        assert result['factory_process_count'] == result['distinct_factory_pids'] == result['distinct_workspaces']
        assert result['all_recorded_literal_geometry_pass']
        if original_full:
            assert result['original24_all_pass'] and len(actions) == 10 and len(workflows) == 11
    return result


if __name__ == '__main__':
    reconcile()
