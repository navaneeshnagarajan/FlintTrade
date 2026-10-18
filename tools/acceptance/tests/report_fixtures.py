"""Explicit synthetic native-report shapes for validator tests, not runtime proof."""
import base64
from types import ModuleType, SimpleNamespace
from typing import Any


def infra_report(module: ModuleType | SimpleNamespace) -> dict[str, Any]:
    """Build explicitly synthetic reports with native error/rendered shapes.

    Args:
        module: Carrier exposing the literal inventory and negative controls.

    Returns:
        A complete synthetic infrastructure report, never runtime evidence.
    """
    specs = []
    fixture_path, positions = module.fixture_origin()
    for row in module.INFRA_CASES:
        identity = (row['file'], row['title'], row['project'])
        test = {'projectName': row['project'], 'expectedStatus': 'passed', 'status': 'expected',
                'annotations': [], 'results': [{'status': 'passed', 'retry': 0, 'errors': []}]}
        if identity in module.NEGATIVE_CONTROLS:
            annotation, detail = module.NEGATIVE_CONTROLS[identity]
            evidence = f'[fail-closed registry "{row["file"]} > {row["title"]}"] 1 failure(s):\n1. {detail}'
            message = 'Error: ' + evidence
            annotations = [{'type': 'fail', 'description': annotation}]
            location = {'file': str(fixture_path), 'line': 639, 'column': 12}
            frames = '\n'.join([
                f'    at {owner} ({fixture_path}:{line}:{column})'
                for owner, (line, column) in zip([
                    'FailClosedSyntheticFixtureRegistry.buildAssertionError',
                    'FailClosedSyntheticFixtureRegistry.disposeOnce',
                    'Object.baseTest.extend.syntheticApi.auto'], positions, strict=True)
            ])
            snippet = ('   at fixture-registry.ts:639\n\n'
                       '  637 |     }\n  638 |\n> 639 |     return new Error(\n'
                       '      |            ^\n'
                       '  640 |       `[fail-closed registry "${this.name}"] ${evidence.length} failure(s):\\n` +\n'
                       '  641 |         evidence.map((item, index) => `${index + 1}. ${item}`).join("\\n"),\n'
                       '  642 |     );')
            test.update(expectedStatus='failed', annotations=annotations)
            test['results'] = [{'status': 'failed', 'retry': 0, 'annotations': annotations,
                'error': {'message': message, 'location': location, 'snippet': snippet,
                    'stack': message + '\n' + frames},
                'errors': [{'message': message + '\n\n' + snippet + '\n' + frames, 'location': location}],
                'attachments': [{'name': 'fail-closed-fixture-evidence', 'contentType': 'text/plain',
                    'body': base64.b64encode(evidence.encode()).decode()}]}]
        specs.append({'file': row['file'], 'title': row['title'], 'tests': [test]})
    return {'config': {'rootDir': str(fixture_path.parent)}, 'errors': [], 'suites': [{'specs': specs}],
            'stats': {'expected': len(specs), 'unexpected': 0, 'flaky': 0, 'skipped': 0}}
