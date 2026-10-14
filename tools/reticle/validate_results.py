"""Fail-closed local report admission; not a substitute for full evidence joins."""
from collections import Counter
import json
from pathlib import Path
import xml.etree.ElementTree as ET

EXPECTED_CASES = (
    'installed knowledge reads the normal-factory full catalogue',
    'manual and CSV Portfolio evidence roundtrips with incomplete provenance',
    'connection CRUD verifies exact item and collection revisions',
    'published history leases reach mounted backtest and immutable evidence',
    'nine actual app mounts retain layout and context with honest System and local help',
    'learning and training actions refuse without fabricated authority',
)

def require(condition, message):
    if not condition:
        raise ValueError(message)

def parse_junit(path):
    # UTF-8 only prevents NUL-interleaved UTF-16 declarations bypassing the
    # pre-parse check. No DTD or entity declaration reaches the stdlib parser.
    text = Path(path).read_bytes().decode('utf-8-sig')
    require('\x00' not in text and '<!DOCTYPE' not in text.upper() and '<!ENTITY' not in text.upper(),
            'DTD/entity declarations are forbidden before XML parsing')
    root = ET.fromstring(text)
    require(root.tag == 'testsuites', 'Expected the Playwright testsuites report')
    return root

def validate_cases(path, expected):
    root = parse_junit(path)
    cases = list(root.iter('testcase'))
    require(Counter((case.get('classname'), case.get('name')) for case in cases) == Counter(expected),
            'Exact original case identities/multiplicities required')
    for field, wanted in [('tests', len(cases)), ('failures', 0), ('errors', 0), ('skipped', 0)]:
        value = root.get(field, '0' if field == 'errors' else None)
        require(isinstance(value, str) and value.isdecimal() and int(value) == wanted,
                'JUnit root totals disagree: ' + field)
    require(not any(list(root.iter(tag)) for tag in ('failure', 'error', 'skipped')),
            'A failed, errored or skipped case is not acceptance')
    for suite in root.iter('testsuite'):
        declared = suite.get('tests')
        if declared is not None:
            require(declared.isdecimal() and int(declared) == len(list(suite.iter('testcase'))),
                    'JUnit suite tests total disagrees with contained cases')
        for field in ('failures', 'errors', 'skipped'):
            value = suite.get(field, '0')
            require(value.isdecimal() and int(value) == 0, 'Nonzero suite outcome: '+field)
    return cases

def validate_windows(paths):
    paths = list(paths)
    require(len(paths) == 7 and len({Path(p).resolve() for p in paths}) == 7, 'Seven distinct original windows required')
    for path in paths:
        packet = json.loads(Path(path).read_text())
        assessment = packet.get('assessment') if isinstance(packet, dict) else None
        require(isinstance(assessment, dict) and assessment.get('accepted') is True,
                'Window assessment.accepted must be exactly boolean true')

def validate_original(output):
    output = Path(output)
    validate_cases(output/'results.xml', [('shared-core-integrated.spec.ts', title) for title in EXPECTED_CASES])
    windows = [p for p in (output/'playwright').rglob('*-full-window.json') if not p.name.endswith('-initial-full-window.json')]
    validate_windows(windows)
