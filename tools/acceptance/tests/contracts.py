"""Synthetic report/dispatch boundary tests; no application or provider doubles."""
from copy import deepcopy
import ast
import importlib.util
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from executor_lifecycle import FixturePublication as FixturePublication

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('validate_results',ROOT/'tools/reticle/validate_results.py')
if spec is None or spec.loader is None:
    raise RuntimeError('Public validator missing')
validator=importlib.util.module_from_spec(spec);spec.loader.exec_module(validator)

class Reports(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.xml=self.root/'results.xml'
        self.report=ET.Element('testsuites',tests='6',failures='0',errors='0',skipped='0')
        suite=ET.SubElement(self.report,'testsuite',name='shared-core-integrated.spec.ts',tests='6',failures='0',errors='0',skipped='0')
        for title in validator.EXPECTED_CASES:
            ET.SubElement(suite,'testcase',classname='shared-core-integrated.spec.ts',name=title)
        self.windows=[]
        for i in range(7):
            path=self.root/'playwright'/f'case-{i}'/f'window-{i}-full-window.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'assessment':{'accepted':True}}))
            self.windows.append(path)
        self.write()

    def write(self):
        self.xml.write_bytes(ET.tostring(self.report,encoding='utf-8'))

    def test_healthy_exact_union(self):
        validator.validate_original(self.root)

    def test_reordered_exact_identities(self):
        suite=self.report[0];suite[:]=list(reversed(suite));self.write()
        validator.validate_original(self.root)

    def test_doctype_rejected_before_parser(self):
        self.xml.write_bytes(b'<!DOCTYPE testsuites>'+self.xml.read_bytes())
        with self.assertRaisesRegex(ValueError,'before XML parsing'):
            validator.validate_original(self.root)

    def test_entity_rejected_before_parser(self):
        self.xml.write_bytes(b'<!DOCTYPE testsuites [<!ENTITY harmless "unused">]>'+self.xml.read_bytes())
        with self.assertRaisesRegex(ValueError,'before XML parsing'):
            validator.validate_original(self.root)

    def test_utf16_declaration_cannot_bypass_guard(self):
        text='<!DOCTYPE testsuites>'+self.xml.read_text()
        self.xml.write_bytes(text.encode('utf-16'))
        with self.assertRaises((ValueError,UnicodeError)):
            validator.validate_original(self.root)

    def test_malformed_xml(self):
        self.xml.write_text('<testsuites>')
        with self.assertRaises(ET.ParseError):validator.validate_original(self.root)

    def test_missing_case(self):
        self.report[0].remove(self.report[0][-1]);self.write()
        with self.assertRaisesRegex(ValueError,'identities'):validator.validate_original(self.root)

    def test_duplicate_replaces_missing_case(self):
        self.report[0][-1].set('name',validator.EXPECTED_CASES[0]);self.write()
        with self.assertRaisesRegex(ValueError,'identities'):validator.validate_original(self.root)

    def test_foreign_case_same_count(self):
        self.report[0][-1].set('name','foreign same-count case');self.write()
        with self.assertRaisesRegex(ValueError,'identities'):validator.validate_original(self.root)

    def test_wrong_file_same_title(self):
        self.report[0][0].set('classname','another.spec.ts');self.write()
        with self.assertRaisesRegex(ValueError,'identities'):validator.validate_original(self.root)

    def test_root_outcome_and_totals(self):
        for field,value in [('tests','5'),('tests','6.0'),('failures','1'),('errors','1'),('skipped','1')]:
            with self.subTest(field=field):
                changed=deepcopy(self.report);changed.set(field,value)
                self.xml.write_bytes(ET.tostring(changed))
                with self.assertRaises(ValueError):validator.validate_original(self.root)

    def test_suite_declared_total_matches_contained_cases(self):
        for value in ['5', '7', '6.0']:
            with self.subTest(tests=value):
                changed=deepcopy(self.report);changed[0].set('tests',value)
                self.xml.write_bytes(ET.tostring(changed))
                with self.assertRaisesRegex(ValueError,'suite tests'):
                    validator.validate_original(self.root)

    def test_failed_errored_skipped_children_even_when_totals_lie(self):
        for tag in ['failure','error','skipped']:
            with self.subTest(tag=tag):
                changed=deepcopy(self.report);ET.SubElement(changed[0][0],tag)
                self.xml.write_bytes(ET.tostring(changed))
                with self.assertRaisesRegex(ValueError,'failed, errored or skipped'):
                    validator.validate_original(self.root)

    def test_nonboolean_window(self):
        for value in [1, 'true', 'yes', [True], {'truthy':True}, False, None]:
            with self.subTest(kind=type(value).__name__):
                self.windows[0].write_text(json.dumps({'assessment':{'accepted':value}}))
                with self.assertRaisesRegex(ValueError,'exactly boolean true'):
                    validator.validate_original(self.root)

    def test_missing_window_field(self):
        self.windows[0].write_text('{}')
        with self.assertRaises(ValueError):validator.validate_original(self.root)

    def test_missing_and_duplicate_window(self):
        with self.assertRaises(ValueError):validator.validate_windows(self.windows[:-1])
        with self.assertRaises(ValueError):validator.validate_windows(self.windows[:-1]+self.windows[:1])

    def test_initial_snapshot_does_not_count_as_final(self):
        path=self.windows.pop();path.rename(path.with_name('window-initial-full-window.json'))
        with self.assertRaisesRegex(ValueError,'Seven distinct'):validator.validate_original(self.root)

class RuntimeDispatch(unittest.TestCase):
    def test_missing_interpreter_refused(self):
        env=dict(os.environ);env.pop('FLINTTRADE_E2E_PYTHON',None)
        result=subprocess.run([sys.executable,ROOT/'tools/acceptance/run.py','policy'],env=env,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Explicit Python 3.14.8 interpreter required',result.stderr)

    def test_wrong_final_interpreter_refused(self):
        result=subprocess.run([sys.executable,ROOT/'tools/acceptance/run.py','paper','--python','/usr/bin/python3'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Current acceptance requires Python 3.14.8',result.stderr)

    def test_gate_refuses_selection(self):
        result=subprocess.run([sys.executable,ROOT/'tools/acceptance/run.py','paper','--case','required-positive'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('not permitted by a maintained full-union gate',result.stderr)

    def test_optimisation_refused_before_collection(self):
        result=subprocess.run([sys.executable,'-O',ROOT/'tools/acceptance/run.py','collect'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('optimisation refused',result.stderr)

class Registrations(unittest.TestCase):
    """Keep maintained command and complete-suite registrations executable."""
    def test_native_v2_generator_check_is_maintained(self) -> None:
        """Require read-only generation, including canonical fixture parity."""
        workflow = (ROOT / '.github/workflows/test.yml').read_text()
        python_job = workflow.split('\n  python-invariants:', 1)[1].split('\n  python-shards:', 1)[0]
        command = 'uv run --offline --no-sync python scripts/generate-native-autonomy-v2-contracts.py --check'
        self.assertIn('run: ' + command, [line.strip() for line in python_job.splitlines()],
                      'Missing maintained native-v2 generator --check')
        scripts = json.loads((ROOT / 'packages/apps/terminal/package.json').read_text())['scripts']
        self.assertEqual(shlex.split(scripts.get('contracts:native-v2:check', '')),
                         ['uv', 'run', '--offline', '--no-sync', '--project', '../../..', 'python',
                          '../../../scripts/generate-native-autonomy-v2-contracts.py', '--check'])

    def test_native_v2_generated_tests_are_in_normal_and_ci_selection(self) -> None:
        """Generated validators must execute in both enumerated Node gates."""
        scripts = json.loads((ROOT / 'packages/apps/terminal/package.json').read_text())['scripts']
        self.assertIn('src/generated', shlex.split(scripts['test:base']),
                      'Missing generated tests from normal test:base')
        workflow = (ROOT / '.github/workflows/test.yml').read_text()
        node_job = workflow.split('\n  node-core-tests:', 1)[1].split('\n  node-widget-tests-1:', 1)[0]
        selected = [line.strip()[5:] for line in node_job.splitlines()
                    if line.strip().startswith('run: ') and 'vitest run ' in line]
        self.assertEqual(len(selected), 1)
        self.assertIn('src/generated/', shlex.split(selected[0]),
                      'Missing generated tests from node-core-tests')

    def test_native_v2_risk_tests_retain_python_package_discovery(self) -> None:
        """Keep normal package discovery and the complete four-shard CI gate."""
        workflow = (ROOT / '.github/workflows/test.yml').read_text()
        job = workflow.split('\n  python-shards:', 1)[1].split('\n  python-tests:', 1)[0]
        selected = [line.strip()[5:] for line in job.splitlines()
                    if line.strip().startswith('run: ') and 'python -m pytest ' in line]
        self.assertEqual(len(selected), 1)
        argv = shlex.split(selected[0])
        self.assertIn('packages/*/*/tests/', argv)
        self.assertIn('--ft-shard-count=4', argv)
        self.assertIn('--timeout=60', argv)
        self.assertIn('--timeout-method=thread', argv)
        hidden = ('-k', '-m', '--keyword', '--markexpr', '--ignore', '--ignore-glob',
                  '--deselect', '--collect-only', '--co')
        test_argv = argv[argv.index('pytest') + 1:]
        self.assertFalse([arg for arg in test_argv if arg.split('=', 1)[0] in hidden or arg.startswith(("-k", "-m"))],
                         'Hidden selection can exclude new risk test modules')

    def test_native_v2_risk_discovery_rejects_hidden_selection(self) -> None:
        """Future risk modules remain in the broad package discovery gate."""
        target = ROOT / '.github/workflows/test.yml'
        original = Path.read_text
        for extra in ("-k 'not options'", '-m unit', '--ignore=packages/core/core/tests',
                      '--ignore-glob=*options*', '--deselect=options', '--collect-only',
                      "-ktest_keep", "-munit"):
            with self.subTest(selection=extra):
                def read(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    return text.replace('pytest packages/*/*/tests/ ',
                                        'pytest packages/*/*/tests/ ' + extra + ' ') if path == target else text
                with patch.object(Path, 'read_text', read):
                    with self.assertRaisesRegex(AssertionError, 'Hidden selection'):
                        self.test_native_v2_risk_tests_retain_python_package_discovery()

    def test_incident_registration_methods_meet_public_standards(self) -> None:
        """The two incident controls retain public annotations and purposes."""
        tree = ast.parse((ROOT / 'tools/acceptance/tests/contracts.py').read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Registrations')
        names = {'test_incident_protocol_control_inventory_and_runner',
                 'test_incident_protocol_registration_omissions_fail'}
        methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.assertEqual({node.name for node in methods}, names)
        for node in methods:
            with self.subTest(method=node.name):
                self.assertEqual(ast.dump(node.returns) if node.returns is not None else None,
                                 'Constant(value=None)', 'Missing public return annotation')
                self.assertTrue(ast.get_docstring(node), 'Missing public purpose docstring')

    def test_desk_spec_is_registered_for_typecheck(self) -> None:
        """Require the complete desk spec in the maintained compiler inventory."""
        source = ROOT / 'packages/apps/terminal/tsconfig.e2e-infra.json'
        self.assertIn('e2e/designer-desk-measure.spec.ts', json.loads(source.read_text())['include'],
                      'Missing desk typecheck registration')

    def test_desk_spec_is_registered_for_zero_warning_lint(self) -> None:
        """Require the complete desk spec in the maintained zero-warning lint."""
        source = ROOT / 'packages/apps/terminal/package.json'
        argv = shlex.split(json.loads(source.read_text())['scripts']['e2e:infra:lint'])
        self.assertIn('e2e/designer-desk-measure.spec.ts', argv, 'Missing desk lint registration')
        self.assertIn('--max-warnings=0', argv)

    def test_desk_typecheck_registration_omission_fails(self) -> None:
        """Detect a compiler omission independently of the lint inventory."""
        target = ROOT / 'packages/apps/terminal/tsconfig.e2e-infra.json'
        original = Path.read_text
        value = json.loads(original(target))
        value['include'].remove('e2e/designer-desk-measure.spec.ts')
        def read(path: Path, *args, **kwargs) -> str:
            return json.dumps(value) if path == target else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            self.test_desk_spec_is_registered_for_zero_warning_lint()
            with self.assertRaisesRegex(AssertionError, 'Missing desk typecheck registration'):
                self.test_desk_spec_is_registered_for_typecheck()

    def test_desk_lint_registration_omission_fails(self) -> None:
        """Detect a lint omission independently of the compiler inventory."""
        target = ROOT / 'packages/apps/terminal/package.json'
        original = Path.read_text
        value = json.loads(original(target))
        argv = shlex.split(value['scripts']['e2e:infra:lint'])
        argv.remove('e2e/designer-desk-measure.spec.ts')
        value['scripts']['e2e:infra:lint'] = shlex.join(argv)
        def read(path: Path, *args, **kwargs) -> str:
            return json.dumps(value) if path == target else original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            self.test_desk_spec_is_registered_for_typecheck()
            with self.assertRaisesRegex(AssertionError, 'Missing desk lint registration'):
                self.test_desk_spec_is_registered_for_zero_warning_lint()

    def test_executor_lifecycle_controls_are_registered(self) -> None:
        """Require the maintained lifecycle class in the complete package gate."""
        source = (ROOT / 'tools/acceptance/tests/contracts.py').read_text()
        self.assertIn('\nfrom executor_lifecycle import ExecutorLifecycle\n', source,
                      'Missing maintained executor lifecycle registration')
        controls = (ROOT / 'tools/acceptance/tests/executor_lifecycle.py').read_text()
        self.assertIn('class ExecutorLifecycle(unittest.TestCase):', controls)

    def test_executor_lifecycle_registration_omission_fails(self) -> None:
        """Reject an omitted lifecycle registration without weakening its oracle."""
        from unittest.mock import patch
        original = Path.read_text
        target = ROOT / 'tools/acceptance/tests/contracts.py'
        def omitted(path, *args, **kwargs):
            text = original(path, *args, **kwargs)
            return (
                text.replace('from executor_lifecycle import ExecutorLifecycle', '# omitted')
                if path == target else text
            )
        with patch.object(Path, 'read_text', omitted):
            with self.assertRaisesRegex(AssertionError, 'Missing maintained executor lifecycle registration'):
                self.test_executor_lifecycle_controls_are_registered()

    def test_incident_protocol_control_inventory_and_runner(self) -> None:
        """Require every incident control and its maintained execution gate."""
        terminal = ROOT / 'packages/apps/terminal'
        source = (terminal / 'e2e/incident-delivery-protocol.control.ts').read_text()
        match = re.search(r'const cases = (\[.*?\]) as const;', source)
        if match is None:
            self.fail('Missing explicit incident control inventory')
        scenarios = json.loads(match.group(1))
        expected = json.loads((ROOT / 'tools/reticle/incident-protocol-cases.json').read_text())
        self.assertEqual(len(scenarios), 29)
        self.assertEqual(sorted(expected), sorted('incident protocol ' + name for name in scenarios))
        self.assertEqual(len(set(expected)), len(expected))
        config = (terminal / 'playwright.incident-protocol.config.ts').read_text()
        self.assertIn('testMatch: "incident-delivery-protocol.control.ts"', config)
        self.assertIn('workers: 1, retries: 0, forbidOnly: true', config)
        self.assertIn('serviceWorkers: "block"', config)
        self.assertIn('"playwright.incident-protocol.config.ts"', (terminal / 'eslint.config.mjs').read_text())
        runner = ast.parse((ROOT / 'tools/reticle/run.py').read_text())
        def shape(source: str) -> str:
            """Compare executable expressions without formatting or comments."""
            return ast.dump(ast.parse(source, mode='eval').body, include_attributes=False)
        nodes = list(ast.walk(runner))
        self.assertIn(shape("terminal / 'playwright.incident-protocol.config.ts'"),
                      [ast.dump(node, include_attributes=False) for node in nodes])
        validation = [node for node in nodes if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == 'validate_cases'
                      and node.args and ast.dump(node.args[0], include_attributes=False)
                      == shape("OUT / 'incident-protocol-results.xml'")]
        self.assertEqual(len(validation), 1)
        controls = [node for node in nodes if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'run'
                    and len(node.args) >= 2
                    and [ast.dump(arg, include_attributes=False) for arg in node.args[:2]]
                    == [shape('controls'), shape("'incident-protocol-controls'")]]
        originals = [node for node in nodes if isinstance(node, ast.Assign)
                     and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                     and node.targets[0].id == 'code' and isinstance(node.value, ast.Call)
                     and isinstance(node.value.func, ast.Name) and node.value.func.id == 'run'
                     and len(node.value.args) >= 2
                     and [ast.dump(arg, include_attributes=False) for arg in node.value.args[:2]]
                     == [shape('cmd'), shape("'original'")]]
        self.assertEqual(len(controls), 1)
        self.assertEqual(len(originals), 1)
        self.assertLess(controls[0].lineno, originals[0].lineno)

    def test_incident_protocol_registration_omissions_fail(self) -> None:
        """Reject missing incident compiler, lint and runner registrations."""
        terminal = ROOT / 'packages/apps/terminal'
        original = Path.read_text
        files = [
            'e2e/incident-delivery-protocol.ts', 'e2e/incident-delivery-protocol.control.ts',
            'playwright.incident-protocol.config.ts',
        ]
        for inventory in ['tsconfig.e2e-infra.json', 'package.json']:
            for omitted in files:
                with self.subTest(inventory=inventory, omitted=omitted):
                    target = terminal / inventory
                    content = json.loads(original(target))
                    if inventory.startswith('tsconfig'):
                        content['include'].remove(omitted)
                    else:
                        content['scripts']['e2e:infra:lint'] = content['scripts']['e2e:infra:lint'].replace(
                            omitted + ' ', ''
                        )
                    def read(path, *args, **kwargs):
                        return json.dumps(content) if path == target else original(path, *args, **kwargs)
                    with patch.object(Path, 'read_text', read):
                        with self.assertRaisesRegex(
                            AssertionError, 'Missing (infra typecheck|zero-warning lint) registration'
                        ):
                            self.test_new_e2e_sources_are_in_typecheck_and_lint_inventories()
        for relative, before, after in [
            ('tools/reticle/run.py', "'playwright.incident-protocol.config.ts'", "'omitted.ts'"),
            ('tools/reticle/run.py', "'incident-protocol-results.xml'", "'omitted.xml'"),
            ('tools/reticle/run.py', "'incident-protocol-controls'", "'omitted-controls'"),
            ('tools/reticle/run.py', "'original'", "'omitted-original'"),
            ('packages/apps/terminal/eslint.config.mjs', '"playwright.incident-protocol.config.ts"', '"omitted.ts"'),
            ('tools/reticle/incident-protocol-cases.json', 'incident protocol positive', 'incident protocol omitted'),
        ]:
            with self.subTest(omitted=relative):
                target = ROOT / relative
                content = original(target).replace(before, after)
                self.assertNotEqual(content, original(target))
                def read_runner(path, *args, **kwargs):
                    return content if path == target else original(path, *args, **kwargs)
                with patch.object(Path, 'read_text', read_runner):
                    with self.assertRaises(AssertionError):
                        self.test_incident_protocol_control_inventory_and_runner()

    def test_ci_runs_the_synthetic_contract_subset(self) -> None:
        """Require the maintained isolated carrier and every required CI class."""
        workflow = (ROOT / '.github/workflows/test.yml').read_text()
        from ci_python_contracts import WORKFLOW_COMMAND, CI_CLASSES
        self.assertTrue(
            'run: ' + WORKFLOW_COMMAND in workflow, 'CI is missing the synthetic report/registration contract step'
        )
        self.assertTrue(
            {'Reports', 'Registrations', 'ExecutorLifecycle', 'PythonSandbox', 'PythonCarrier'} <= set(CI_CLASSES)
        )

    def test_new_e2e_sources_are_in_typecheck_and_lint_inventories(self):
        terminal = ROOT / 'packages/apps/terminal'
        def config(name):
            return json.loads(re.sub(r'(?m)^\s*//.*$', '', (terminal / name).read_text()))
        app = config('tsconfig.json')
        infra = config('tsconfig.e2e-infra.json')
        expected_app = {'e2e/incidents/fixture.tsx', 'e2e/service-oauth-handoff.fixture.tsx', 'e2e/service-oauth-handoff.entry.ts'}
        expected_infra = {'e2e/incident-delivery-protocol.ts','e2e/incident-delivery-protocol.control.ts','playwright.incident-protocol.config.ts', 'playwright.incidents.config.ts', 'playwright.policy.config.ts', 'playwright.reticle.config.ts', 'vite.reticle.config.ts', 'e2e/incidents/SystemIncidents.spec.ts', 'e2e/incidents/vite.config.ts', 'e2e/notification-disclosure.spec.ts', 'e2e/accessibility-overflow.spec.ts', 'e2e/structural-accessibility.spec.ts', 'e2e/structural-accessibility.ts', 'e2e/workspace-interactions.ts', 'e2e/observed-registry.ts', 'e2e/visual/help-placement.ts'}
        self.assertFalse(expected_app - set(app['include']), 'Missing app fixture typecheck registration: ' + str(expected_app - set(app['include'])))
        self.assertFalse(expected_infra - set(infra['include']), 'Missing infra typecheck registration: ' + str(expected_infra - set(infra['include'])))
        self.assertIs(app['compilerOptions']['allowImportingTsExtensions'], True)
        self.assertIs(infra['compilerOptions']['allowImportingTsExtensions'], True)
        scripts = json.loads((terminal / 'package.json').read_text())['scripts']
        lint = shlex.split(scripts['e2e:infra:lint'])
        required = expected_app | expected_infra | {'e2e/service-oauth-handoff.browser.mjs', 'e2e/about-versions.fixture.tsx'}
        self.assertFalse(required - set(lint), 'Missing zero-warning lint registration: ' + str(required - set(lint)))
        self.assertIn('--max-warnings=0', lint)

    def test_default_dispatch_executes_every_lane_and_stops_at_each_failure(self):
        scripts = json.loads((ROOT / 'packages/apps/terminal/package.json').read_text())['scripts']
        lanes = ['e2e:maintained:contracts', 'e2e:infra:typecheck', 'e2e:infra:lint', 'e2e:maintained:collect', 'e2e:reticle:collect', 'e2e:default', 'e2e:public-demo', 'e2e:incidents', 'e2e:oauth', 'e2e:reticle:controls', 'e2e:reticle', 'e2e:policy', 'e2e:paper']
        self.assertFalse(set(lanes) - scripts.keys(), 'Missing maintained default lanes: ' + str(set(lanes) - scripts.keys()))
        # Run the actual package script through the real shell. Only external
        # executables are inert; they record argv and inject one bounded failure.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            log = directory / 'calls.jsonl'
            shim = '#!' + sys.executable + '\n' + '''import json, os, sys
from pathlib import Path
name = Path(sys.argv[0]).name
with open(os.environ['DISPATCH_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
raise SystemExit(37 if name == 'npm' and len(sys.argv) > 2 and sys.argv[2] == os.environ.get('FAIL_LANE') else 0)
'''
            for tool in ['npm', 'mkdir', 'mv']:
                path = directory / tool
                path.write_text(shim)
                path.chmod(0o755)
            env = {'PATH': str(directory), 'HOME': '/run/test/home', 'FLINTTRADE_E2E_PYTHON': '/qualified/python', 'PLAYWRIGHT_BROWSERS_PATH': '/qualified/browsers', 'DISPATCH_LOG': str(log)}
            for fail in [None, *lanes]:
                with self.subTest(failing_lane=fail):
                    log.unlink(missing_ok=True)
                    result = subprocess.run(['/bin/sh', '-c', scripts['e2e']], cwd=ROOT / 'packages/apps/terminal', env={**env, 'FAIL_LANE': fail or ''}, capture_output=True, text=True)
                    calls = [json.loads(row) for row in log.read_text().splitlines()]
                    expected = lanes if fail is None else lanes[:lanes.index(fail) + 1]
                    self.assertEqual([row[2] for row in calls if row[0] == 'npm'], expected, result.stderr)
                    self.assertEqual(result.returncode, 0 if fail is None else 37)
                    completed = expected if fail is None else expected[:-1]
                    self.assertEqual([row[2] for row in calls if row[0] == 'mv'], ['/run/test/e2e-evidence/' + lane for lane in completed])

    def test_oauth_dispatch_refuses_a_missing_qualified_interpreter(self):
        scripts = json.loads((ROOT / 'packages/apps/terminal/package.json').read_text())['scripts']
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            tool = directory / 'python'
            marker = directory / 'called'
            tool.write_text('#!' + sys.executable + '\nfrom pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
            tool.chmod(0o755)
            result = subprocess.run(['/bin/sh', '-c', scripts['e2e:oauth']], env={'PATH':str(directory), 'PLAYWRIGHT_BROWSERS_PATH':'/qualified/browsers'}, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(marker.exists(), 'Ambient Python must not run the browser gate')

    def test_standalone_scripts_dispatch_exact_public_entrypoints(self):
        scripts = json.loads((ROOT / 'packages/apps/terminal/package.json').read_text())['scripts']
        expected = {
            'e2e:maintained:contracts': ['python', '../../../tools/acceptance/tests/contracts.py'],
            'e2e:maintained:collect': ['python', '../../../tools/acceptance/run.py', 'collect'],
            'e2e:policy': ['python', '../../../tools/acceptance/run.py', 'policy'],
            'e2e:paper': ['python', '../../../tools/acceptance/run.py', 'paper'],
            'e2e:reticle': ['python', '../../../tools/reticle/run.py', 'original', '--python', '/qualified/python'],
            'e2e:reticle:controls': ['python', '../../../tools/reticle/run.py', 'controls'],
            'e2e:reticle:collect': ['python', '../../../tools/reticle/run.py', 'collect'],
            'e2e:default': ['python', '../../../tools/acceptance/run.py', 'default'],
            'e2e:incidents': ['playwright', 'test', '--config=playwright.incidents.config.ts', '--workers=1', '--retries=0'],
            'e2e:oauth': ['python', '-m', 'pytest', '../../../packages/core/core/tests/test_service_oauth_browser.py', '-q', '-p', 'no:cacheprovider', '--junitxml=/run/test/artifacts/oauth.xml'],
        }
        self.assertFalse(expected.keys() - scripts.keys(), 'Missing standalone maintained commands')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            log = directory / 'argv.json'
            shim = '#!' + sys.executable + '\nimport json, os, sys\nfrom pathlib import Path\nPath(os.environ["DISPATCH_LOG"]).write_text(json.dumps([Path(sys.argv[0]).name, *sys.argv[1:]]))\nraise SystemExit(int(os.environ["FAIL_CODE"]))\n'
            for name in ['python', 'playwright']:
                tool = directory / name; tool.write_text(shim); tool.chmod(0o755)
            for name, argv in expected.items():
                for code in [0, 29]:
                    with self.subTest(script=name, code=code):
                        env = {'PATH': str(directory), 'DISPATCH_LOG': str(log), 'FLINTTRADE_E2E_PYTHON': str(directory / 'python') if name == 'e2e:oauth' else '/qualified/python', 'PLAYWRIGHT_BROWSERS_PATH': '/qualified/browsers', 'FAIL_CODE': str(code)}
                        result = subprocess.run(['/bin/sh', '-c', scripts[name]], env=env, cwd=ROOT / 'packages/apps/terminal', capture_output=True, text=True)
                        self.assertEqual(result.returncode, code, result.stderr)
                        self.assertEqual(json.loads(log.read_text()), argv)
                        self.assertNotIn('.local', scripts[name])
                        self.assertNotIn('diagnostic-', scripts[name])



class CspCarrier(unittest.TestCase):
    def load_carrier(self):
        source = ROOT/'tools/acceptance/csp.py'
        self.assertTrue(source.is_file(), 'Missing public CSP carrier')
        spec = importlib.util.spec_from_file_location('csp_carrier', source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_default_partition_preserves_every_identity_without_skips(self):
        module = self.load_carrier()
        cases = [{'file':'ordinary.spec.ts','title':'ordinary','project':'chromium'}, *module.CSP_CASES, *module.INFRA_CASES]
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            infra, generic, csp = module.partition(cases, out)
            self.assertEqual(infra, module.INFRA_CASES)
            self.assertEqual(generic, cases[:1])
            self.assertEqual(csp, module.CSP_CASES)
            self.assertEqual((out/'vite-test-list.txt').read_text(), '[chromium] › ordinary.spec.ts › ordinary\n')
            self.assertEqual((out/'csp-test-list.txt').read_text().splitlines(), [f"[chromium] › {row['file']} › {row['title']}" for row in csp])
            for bad in [cases[:2]+cases[3:], cases+[cases[1]], cases+[dict(cases[1],title='unexpected CSP case')]]:
                with self.assertRaisesRegex(ValueError,'CSP identities'):
                    module.partition(bad,out)

    def test_helper_definition_keeps_identity_but_selects_registration_file(self):
        module = self.load_carrier()
        helper = {'file':'structure.ts','title':'structure › keyboard','project':'chromium'}
        cases = [helper, *module.CSP_CASES, *module.INFRA_CASES]
        owners = {(r['file'],r['title'],r['project']):r['file'] for r in cases}
        owners[('structure.ts','structure › keyboard','chromium')] = 'structure.spec.ts'
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            infra, vite, csp = module.partition(cases, out, owners)
            self.assertEqual(vite, [helper])
            self.assertEqual((out/'vite-test-list.txt').read_text().splitlines(), [
                '[chromium] › structure.ts › structure › keyboard',
                '[chromium] › structure.spec.ts › structure › keyboard',
            ])
            self.assertEqual(module.identities(infra+vite+csp), module.identities(cases))

    def test_csp_report_requires_actual_successful_bodies(self):
        module = self.load_carrier()
        report = {'errors':[], 'suites':[{'specs':[{'file':row['file'],'title':row['title'],'tests':[{'projectName':row['project'],'expectedStatus':'passed','status':'expected','results':[{'status':'passed','retry':0}]}]} for row in module.CSP_CASES]}]}
        module.validate_report(report,module.CSP_CASES)
        for status in ['failed','skipped','timedOut','interrupted']:
            changed = deepcopy(report)
            changed['suites'][0]['specs'][0]['tests'][0]['results'][0]['status']=status
            with self.assertRaises(ValueError):module.validate_report(changed,module.CSP_CASES)
        changed=deepcopy(report);changed['suites'][0]['specs'][0]['tests'][0]['results']=[]
        with self.assertRaises(ValueError):module.validate_report(changed,module.CSP_CASES)
        changed=deepcopy(report);changed['suites'][0]['specs'][0]['tests'][0]['results']*=2
        with self.assertRaises(ValueError):module.validate_report(changed,module.CSP_CASES)

    def test_server_stop_and_eof_both_release_real_owners(self):
        import hashlib
        import socket
        import uuid
        python = os.environ.get('FLINTTRADE_E2E_PYTHON')
        self.assertTrue(python, 'Explicit selected interpreter required for isolated lifecycle controls')
        source = ROOT/'tools/acceptance/csp_server.py'
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), *map(str, ROOT.glob('packages/*/*/src'))]))
        for stop in ['STOP\n', '']:
            with self.subTest(protocol='STOP' if stop else 'EOF'):
                key=hashlib.sha256(uuid.uuid4().bytes).hexdigest()
                output=Path('/run/test/artifacts/playwright')/('lifecycle-'+key)/'normal-core'
                result=subprocess.run([python,str(source),'--case-key',key,'--output',str(output)],input=stop,capture_output=True,text=True,env=env,timeout=60)
                output.parent.mkdir(parents=True,exist_ok=True)
                (output.parent/'server.log').write_text(result.stdout+result.stderr)
                self.assertIn('R33_CORE_READY',result.stdout,result.stderr)
                self.assertEqual(result.returncode==0,bool(stop),result.stderr)
                if not stop:self.assertIn('ended without STOP',result.stderr)
                shutdown=json.loads((output/'shutdown.json').read_text())
                self.assertEqual(shutdown['remaining_threads'],[])
                for field in ['admission_drained','listener_stopped','listener_closed_probe','owners_released']:
                    self.assertIs(shutdown.get(field),True,field)
                self.assertEqual(shutdown['lifecycle'],'_DesktopShutdownRecoveryOwner.release')
                with socket.socket() as listener:
                    self.assertNotEqual(listener.connect_ex(('127.0.0.1',5173)),0)
                with socket.socket() as listener:
                    listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    listener.bind(('127.0.0.1',5173))

    def test_server_refuses_optimisation_before_factory_import(self):
        source=ROOT/'tools/acceptance/csp_server.py'
        self.assertTrue(source.is_file(),'Missing public normal factory server')
        result=subprocess.run([sys.executable,'-O',str(source)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('optimisation refused',result.stderr)

class BrowserRoles(unittest.TestCase):
    load_carrier = CspCarrier.load_carrier

    def setUp(self):
        from report_fixtures import infra_report
        self.module = self.load_carrier()
        self.report = infra_report(self.module)

    def test_known_negative_failures_are_required_not_converted_to_passes(self):
        self.module.validate_report(self.report, self.module.INFRA_CASES, role='infra')
        with self.assertRaises(ValueError):
            self.module.validate_report(self.report, self.module.INFRA_CASES)

    def test_negative_controls_bind_original_identity_and_exact_cause(self):
        for index, spec in enumerate(self.report['suites'][0]['specs']):
            if spec['tests'][0]['expectedStatus'] != 'failed':
                continue
            for mutation in ['pass', 'skip', 'timeout', 'retry', 'duplicate-result', 'no-result',
                             'wrong-error', 'extra-error', 'no-error', 'no-attachment', 'wrong-attachment',
                             'duplicate-attachment', 'wrong-origin', 'wrong-owner', 'wrong-annotation',
                             'extra-annotation', 'wrong-identity', 'wrong-project', 'missing-control',
                             'wrong-rendered-error']:
                with self.subTest(control=spec['title'], mutation=mutation):
                    changed = deepcopy(self.report)
                    item = changed['suites'][0]['specs'][index]
                    test = item['tests'][0]
                    result = test['results'][0]
                    if mutation == 'pass': result['status'] = 'passed'
                    elif mutation == 'skip': result['status'] = 'skipped'
                    elif mutation == 'timeout': result['status'] = 'timedOut'
                    elif mutation == 'retry': result['retry'] = 1
                    elif mutation == 'duplicate-result': test['results'] *= 2
                    elif mutation == 'no-result': test['results'] = []
                    elif mutation == 'wrong-error': result['error']['message'] = 'Error: EADDRINUSE'
                    elif mutation == 'extra-error': result['errors'].append({'message': 'extra guard failure'})
                    elif mutation == 'no-error': result['errors'] = []
                    elif mutation == 'no-attachment': result['attachments'] = []
                    elif mutation == 'wrong-attachment': result['attachments'][0]['body'] = 'd3Jvbmc='
                    elif mutation == 'duplicate-attachment': result['attachments'] *= 2
                    elif mutation == 'wrong-origin': result['error']['location']['file'] = '/wrong.ts'
                    elif mutation == 'wrong-owner': result['error']['stack'] = 'Error: not automatic teardown'
                    elif mutation == 'wrong-annotation': test['annotations'][0]['description'] = 'wrong cause'
                    elif mutation == 'extra-annotation': test['annotations'].append({'type':'fail','description':'extra'})
                    elif mutation == 'wrong-identity': item['title'] += ' unknown'
                    elif mutation == 'wrong-project': test['projectName'] = 'other'
                    elif mutation == 'missing-control': changed['suites'][0]['specs'].pop(index)
                    elif mutation == 'wrong-rendered-error': result['errors'][0]['message'] += '\nextra failure'
                    with self.assertRaises(ValueError):
                        self.module.validate_report(changed, self.module.INFRA_CASES, role='infra')

    def test_native_frame_and_rendered_error_correspondence(self):
        for index, spec in enumerate(self.report['suites'][0]['specs']):
            if spec['tests'][0]['expectedStatus'] != 'failed':
                continue
            for mutation in ['owner-substrings', 'extra-rendered-error', 'wrong-frame-path',
                             'wrong-frame-owner', 'reordered-frames', 'extra-frame',
                             'rendered-stack-mismatch', 'location-mismatch', 'snippet-suffix']:
                with self.subTest(control=spec['title'], mutation=mutation):
                    changed = deepcopy(self.report)
                    result = changed['suites'][0]['specs'][index]['tests'][0]['results'][0]
                    primary, rendered = result['error'], result['errors'][0]
                    if mutation == 'owner-substrings':
                        primary['stack'] = 'Not a stack: FailClosedSyntheticFixtureRegistry.disposeOnce Object.baseTest.extend.syntheticApi.auto'
                        rendered['message'] = primary['message']
                    elif mutation == 'extra-rendered-error': rendered['message'] += '\nUNEXPECTED EXTRA FAILURE'
                    elif mutation == 'wrong-frame-path': primary['stack'] = primary['stack'].replace(str(self.module.TERM / 'e2e'), '/unrelated')
                    elif mutation == 'wrong-frame-owner': primary['stack'] = primary['stack'].replace('at Object.', 'at ForgedObject.')
                    elif mutation == 'reordered-frames':
                        lines = primary['stack'].splitlines(); lines[-2:] = reversed(lines[-2:]); primary['stack'] = '\n'.join(lines)
                    elif mutation == 'extra-frame': primary['stack'] += '\n    at unrelated (/unrelated.ts:1:1)'
                    elif mutation == 'rendered-stack-mismatch': rendered['message'] = rendered['message'].replace(':597:33)', ':598:33)')
                    elif mutation == 'location-mismatch': rendered['location'] = dict(rendered['location'], line=640)
                    elif mutation == 'snippet-suffix':
                        primary['snippet'] += '\nUNEXPECTED EXTRA FAILURE'
                        rendered['message'] = primary['message'] + '\n\n' + primary['snippet'] + primary['stack'][len(primary['message']):]
                    with self.assertRaises(ValueError):
                        self.module.validate_report(changed, self.module.INFRA_CASES, role='infra')

    def test_native_fixture_paths_and_positions_bind_source_not_report(self):
        import re
        for mutation in ['foreign-path', 'foreign-root-and-path', 'teardown-position', 'auto-position']:
            with self.subTest(mutation=mutation):
                changed = deepcopy(self.report)
                for _, test in self.module.report_rows(changed):
                    if test['expectedStatus'] != 'failed':
                        continue
                    result = test['results'][0]
                    old = result['error']['location']['file']
                    for error in [result['error'], *result['errors']]:
                        if mutation.startswith('foreign'):
                            error['location']['file'] = '/foreign/e2e/fixture-registry.ts'
                            for key in ['stack', 'message']:
                                if key in error: error[key] = error[key].replace(old, '/foreign/e2e/fixture-registry.ts')
                        else:
                            owner = 'FailClosedSyntheticFixtureRegistry.disposeOnce' if mutation == 'teardown-position' else 'Object.baseTest.extend.syntheticApi.auto'
                            for key in ['stack', 'message']:
                                if key in error:
                                    error[key] = re.sub(r'(    at ' + re.escape(owner) + r' \([^\n]+):[0-9]+:[0-9]+\)', r'\1:1:1)', error[key])
                if mutation == 'foreign-root-and-path': changed['config'] = {'rootDir': '/foreign/e2e'}
                with self.assertRaises(ValueError):
                    self.module.validate_report(changed, self.module.INFRA_CASES, role='infra')

    def test_unknown_expected_failures_and_extra_controls_refused(self):
        changed = deepcopy(self.report)
        specs = changed['suites'][0]['specs']
        positive = next(s for s in specs if s['tests'][0]['expectedStatus'] == 'passed')
        negative = next(s for s in specs if s['tests'][0]['expectedStatus'] == 'failed')
        positive['tests'] = deepcopy(negative['tests'])
        with self.assertRaises(ValueError):
            self.module.validate_report(changed, self.module.INFRA_CASES, role='infra')
        changed = deepcopy(self.report)
        changed['suites'][0]['specs'].append(deepcopy(negative))
        with self.assertRaises(ValueError):
            self.module.validate_report(changed, self.module.INFRA_CASES, role='infra')

    def test_positive_infra_remains_pass_once_only(self):
        for value in ['failed','skipped','timedOut','interrupted']:
            with self.subTest(status=value):
                changed=deepcopy(self.report)
                changed['suites'][0]['specs'][0]['tests'][0]['results'][0]['status']=value
                with self.assertRaises(ValueError):
                    self.module.validate_report(changed,self.module.INFRA_CASES,role='infra')

    def test_infrastructure_inventory_cannot_drop_or_add_cases(self):
        module=self.module
        rows=[*module.INFRA_CASES,*module.CSP_CASES,{'file':'app.spec.ts','title':'app','project':'chromium'}]
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)
            roles=module.partition(rows,out)
            self.assertEqual(sum((module.identities(role) for role in roles), __import__('collections').Counter()), module.identities(rows))
            for changed in [rows[1:], rows+[rows[0]], [dict(rows[0],title='unknown'),*rows[1:]]]:
                with self.assertRaises(ValueError): module.partition(changed,out)

    def test_dispatch_shares_original_budget_and_stops_on_every_role_failure(self):
        from unittest.mock import patch
        module=self.module
        app=[{'file':'app.spec.ts','title':'app','project':'chromium'}]
        with tempfile.TemporaryDirectory() as temp, patch.object(module,'OUT',Path(temp)), patch.object(module,'require_free_port') as free:
            for failed in [None,'default-infra','default-vite']:
                calls=[]
                def execute(argv,name,timeout,env):
                    calls.append((argv,name,timeout))
                    if name==failed: return 37
                    report=self.report if name=='default-infra' else {'suites':[{'specs':[{'file':'app.spec.ts','title':'app','tests':[{'projectName':'chromium','expectedStatus':'passed','status':'expected','results':[{'status':'passed','retry':0}]}]}]}]}
                    Path(env['PLAYWRIGHT_JSON_OUTPUT_FILE']).write_text(json.dumps(report))
                    return 0
                with patch.object(module.time,'monotonic',side_effect=[10,12,110]):
                    if failed:
                        with self.assertRaises(RuntimeError): module.run_browser_roles({},execute,module.INFRA_CASES,app)
                    else: module.run_browser_roles({},execute,module.INFRA_CASES,app)
                self.assertEqual([c[1] for c in calls],['default-infra'] if failed=='default-infra' else ['default-infra','default-vite'])
                self.assertEqual([c[2] for c in calls],[1198] if failed=='default-infra' else [1198,1100])
                for argv,_,_ in calls:
                    self.assertIn('--workers=1',argv); self.assertIn('--retries=0',argv)
                self.assertIn('playwright.infra.config.ts',str(calls[0][0]))
            self.assertGreaterEqual(free.call_count,10)

    def test_role_collection_mismatch_stops_before_any_body(self):
        from unittest.mock import patch
        module=self.module
        all_report=deepcopy(self.report)
        for row in [*module.CSP_CASES,{'file':'app.spec.ts','title':'app','project':'chromium'}]:
            all_report['suites'][0]['specs'].append({'file':row['file'],'title':row['title'],'tests':[{'projectName':row['project']}]})
        # Native reports group definitions under their registering spec file.
        all_report['suites'] = [{'file': spec['file'], 'specs': [spec]}
                                for spec in all_report['suites'][0]['specs']]
        with tempfile.TemporaryDirectory() as temp, patch.object(module,'OUT',Path(temp)):
            calls=[]
            def execute(argv,name,timeout,env):
                calls.append(name)
                Path(env['PLAYWRIGHT_JSON_OUTPUT_FILE']).write_text(json.dumps(all_report))
                return 0
            with self.assertRaises(ValueError): module.collect({},execute)
            self.assertEqual(calls,['default-collection','default-infra-collection'])

# Both the normal package gate and the isolated CI carrier execute these bodies.
from executor_lifecycle import ExecutorLifecycle
from isolated_python import PythonSandbox, PythonCarrier

if __name__=='__main__':
    from ci_python_contracts import contract_main
    contract_main()
