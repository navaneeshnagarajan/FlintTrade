# Offline mapping verification contract

This executor-local verification aid is a prerequisite for the Dhan and Upstox mapping plans. It is not implemented or verified by this document. Until its requirements are satisfied, report mapping tests as unrun. Do not substitute ordinary repository pytest commands.

## Prerequisites

1. Use an existing Python 3.12 environment and installed pytest; install nothing. Launch with `-I -S` to disable environment/path injection and site startup hooks. The manifest must separately identify the reviewed installed pytest/dependency paths; load those without processing `.pth` files. Establish a network-disabled executor sandbox before Python; fail if unavailable. Use no broker credentials, SDK clients, account fixtures or connections.
2. Create `/tmp/ft-mapping-check/run.py` and `/tmp/ft-mapping-check/imports.json` locally. The runner is reusable for both brokers, is never added to production code, and introduces no runtime authority or readiness evidence.
3. Statically review the chosen mapping file and its complete import closure before execution. The manifest must map each allowed application module to its exact source file and SHA-256. Only independently reviewed pure dependencies qualify. The mapping's real `flinttrade_core.broker_read_port.BrokerReadResponseInvalid` and, for Upstox, real exception dependencies must be loaded from their actual source. If their closure requires runtime/provider/catalogue code, stop and report the unresolved prerequisite. Do not replace them with invented exception classes or dummy safety contracts.
4. Review the independent test file. It may use pytest, standard-library `SimpleNamespace` inputs, literal dictionaries and the loaded mapping module. It must not import `Order`, adapter catalogues, native adapters, SDKs, runtime dispatch or repository fixtures. Derive relevant assertions from existing tests by reading, never importing them.

## Runner interface and isolation

`run.py --root ABSOLUTE_CHECKOUT --broker {dhan,upstox} --tests REPOSITORY_RELATIVE_TEST_PATH --manifest /tmp/ft-mapping-check/imports.json`

The runner resolves paths under the checkout, verifies manifest hashes, and rejects unlisted application imports before executing their code. Use source-file loaders for the exact mapping/dependency modules. Empty package containers may provide Python namespaces, but must not execute production `__init__.py` files or emulate exported behaviour. They must not expose ambient package search paths. No project directory is added to ordinary `sys.path`.

Copy only the chosen independent test file into a fresh non-package temporary directory. Run pytest programmatically there with plugin autoload disabled, empty `PYTEST_ADDOPTS`/`PYTHONPATH`, `--noconftest`, `--import-mode=importlib`, `-c` pointing to an empty executor-local config and `--rootdir` pointing to that directory. Load no repository conftest, pyproject pytest configuration, third-party pytest plugins or production package initialisers. Tests import the mapping through its preloaded module name. Keep import restrictions active throughout collection and execution.

Before any product test, use executor-local sentinel fixtures to establish that a conftest and package-initialiser sentinel never execute; an unlisted application import fails before execution; and a network attempt is blocked by the sandbox. Failure is a runner failure, not a product test verdict. Do not make a test pass by mocking these boundaries away.

## Results

Exit 0 means all isolated mapping tests passed; exit 1 means test failure; exit 2 means an unmet isolation/import prerequisite. Emit the verified source/test hashes, broker, collected test count, pytest summary and isolation checks. A zero-test collection cannot pass. Never label a missing dependency, blocked import or unavailable sandbox as a successful test.

The normal `python scripts/ft.py test-fast ... --workers 0` commands and existing mapping suites remain unrun pending separate integration verification of their startup/import paths. Passing this aid establishes only pure mapping behaviour.
