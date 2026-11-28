# Source-only normal-factory acceptance

Run these payloads **inside the authorised Linux disposable runtime**, with an
empty `/run/test/home`, private loopback-only networking, zero capabilities,
`NoNewPrivs`, no operator state, read-only sources and writable disposable output. The checkout
must have neither `.local` nor `graphify-out`. These scripts are not an isolation
launcher and must not be run against a personal workspace or service.

Install the repository's pinned dependencies before entering the offline runtime.
Reuse the public `tools/reticle` carrier; do not copy a cached application snapshot.
For the separate shared-core Reticle gate, reconstruct its qualified package from
the explicit public inputs in `tools/reticle/README.md`, including licence notices.
The installed policy and Paper commands need its shared source helpers, not its
compiled daemon. No real broker, provider, model or training job is contacted.

## Maintained commands

Set `FLINTTRADE_E2E_PYTHON` to the explicit qualified **Python 3.14.8** executable
visible inside the runtime, or pass `--python` to each execution command. Missing
or different versions fail before application startup. Current repository sources
are first on `PYTHONPATH`; an old editable application checkout is not a fallback.

```text
python tools/acceptance/tests/contracts.py
python tools/acceptance/run.py collect
python tools/acceptance/run.py infra
python tools/acceptance/run.py default
python tools/acceptance/run.py policy

python tools/acceptance/run.py paper
```

- `default` collects the complete public default Playwright inventory, then
  reconciles three disjoint native inclusion lists. The exact original no-app
  identities in `infra-cases.json` execute first under `playwright.infra.config.ts`,
  without Vite. This includes both registry self-tests and the decoded-read
  controls that own a test-scoped loopback listener. Ordinary app cases use Vite;
  the two unchanged `schema-csp` cases use a fresh production build and a
  test-scoped anonymous normal factory. Vite is stopped before the factory owns
  its port. No CSP cases are ignored/skipped and no private server path is needed.
  The parser companion never configures Zod; the installed entry must do so.
  The separate nonce-bearing external eval control still requires the real CSP
  violation/report and the unchanged registry's fatal rejection. Factory cleanup
  uses the existing request drain and complete lifecycle owner, not a subset of
  ad-hoc close calls. `e2e:default` dispatches this carrier, not bare Playwright.
  Infrastructure and Vite share the original 1,200-second execution budget;
  individual test budgets, one worker, zero retries and service-worker blocking
  remain unchanged. Missing, extra or duplicate infrastructure identities fail
  collection. Each body executes once. The two original automatic-teardown
  negative controls must remain failed, with their exact identity, annotation,
  original guard cause and fixture-evidence attachment; no other failed body is
  allowed. A passing negative control, unrelated failure or extra guard error
  is fatal. The current inventory includes the original 163 infrastructure rows
  plus 22 explicit additive controls: 185 infrastructure + 248 Vite + 2 CSP.
  No historical-inventory fallback is admitted. Native negative errors must bind
  ordered, exact owner frames and locations to their entire bounded code frame
  and rendered error; owner-name substrings and trailing unrelated errors fail.
  The fixture path must equal the launch checkout's absolute fixture path, and
  all three owner line/column pairs come from that source's unique call sites.
  `validate_report(..., fixture_root=...)` and `playwright_counts(...,
  fixture_root=...)` accept a caller-owned testDir for archived replay; never
  pass the report's self-declared `config.rootDir` as that authority. Omission
  binds the parser checkout, while real dispatch supplies its actual testDir.
  The public CLI uses the CI launcher's fixed `acceptance-source` sibling of
  `--state`; other launchers must pass `--browser-source` with their trusted
  checkout. That source must remain available. Missing context is unknown,
  not a fallback to a report path. These are bounded source checks, not proof
  of report authenticity; public `acceptance_verified` always remains false.
  Public projection schema 2 retains raw `failed` counts and separately reports
  `expected_failed` only for these verified controls. It requires the infrastructure
  report, exposes no raw evidence and still never claims acceptance verification.
- `policy` builds the current terminal and executes all **33 original cases** from
  both policy specs in one Chromium invocation, one worker, zero retries. Every
  case owns a normal-factory process/workspace; backend replacement stops and
  verifies the first genuine owner before starting the next. It retains exact
  body/phase ledgers, readiness, geometry, unavailable/native-freeze and drain
  assertions. The collection command verifies the literal title/file multiset.
- The policy/remaining union retains its original installed-only execution mode.
  Every existing optional Reticle predicate and hook remains unchanged; this
  carrier does not invent instrumented coverage for asset-bound replacement
  cases. The separate six-case/seven-window shared-core Reticle gate is required
  unchanged, not replaced by this installed union.
- `paper` registers all **25 original commands**: the exact text and IPv6-denial
  controls; helper/admission lint; constructor-lifetime faults; health/pin and
  quantity refusals; run-owned unavailable/model controls; the real worker entry,
  persisted monitor, explicit HTTP grant, nonempty retained duty, fixed SELL and
  flat readback; expiry/budget/revocation and genuinely foreign-position controls.
  Each command receives separate generated output and workspace directories.
  Required assertions are not replaced with guessed responses or fake core APIs.

Execution gates refuse narrowed case selection. Each command fails if its
child fails; runtime cases additionally require their original clean drain and
closed-listener probes. Outputs remain private under `/run/test/artifacts` and
must not be committed. Reticle admission rejects DTD/entity XML before parsing,
requires the exact original six identity/multiplicity pairs, refuses
failure/error/skip records, and requires exactly boolean `true` for all seven
accepted windows. It does **not** replace full body/geometry/native-scope/raw-window
joins, original endpoint checks or the parent's final source/runtime acceptance.

## Command lifetime and timeout receipts

Every maintained mode uses a fresh Linux subreaper for each command. Custody is
established before spawn; detached groups/sessions and double-forked children
remain descendants of that owner. Cleanup signals only its kernel-declared
children through generation-checked pidfds, then reaps adopted descendants until
`waitpid` reports no children. The caller is not a subreaper and unrelated
processes are never discovered by name, session, or a host-wide census.

Normal exits (including nonzero and signal exits), deadlines, cancellation and
controller EOF all drain owned descendants **before** the native port probes.
`TimeoutExpired` still propagates as failure. Each command is appended in
`finally`, even without a final browser JSON report. `*.ownership.json` records
native exit/signal, executor outcome, deadline, PID/start/group/session identities,
signals and reaps independently of the final `acceptance-execution.json`.

Owner startup consumes the supplied execution budget. Cleanup has a separate
five-second termination/reaping ceiling and one second for receipt delivery; it
does not grant additional execution time. Elapsed cleanup also consumes any
remaining shared browser budget (the existing 1,200-second deadline is unchanged).
Incomplete cleanup or missing custody fails closed. Killing the owner itself or
an unkillable kernel task cannot be reported as clean; outer isolation remains
containment, not proof of inner cleanup.

The normal `contracts.py` gate includes `ExecutorLifecycle` controls with real
ready listeners and an unrelated same-namespace process. CI now executes every
`Reports`, `Registrations` and `ExecutorLifecycle` body, plus the registered
`PythonSandbox` and `PythonCarrier` controls, through the Python prerequisite
profile below. Importing a class or collecting its names does not count as
execution: the carrier reconciles exact identities and setup/body/teardown
entry/return records, and refuses skips, failures, duplicates and omissions.

## Native-v2 / risk foundation registration

These gates require the installed **full** Python/Node environment. They are
not part of the stdlib-only CI projection and must not be passed to the
`python-tests` profile as substitutes for full qualification.

- `python-invariants` runs
  `uv run --offline --no-sync python scripts/generate-native-autonomy-v2-contracts.py --check`.
  The generator first compares the canonical Python fixture at
  `packages/core/core/tests/fixtures/native-autonomy-v2.json` with the projection
  at `packages/apps/terminal/src/generated/__tests__/fixtures/native-autonomy-v2.json`,
  then checks both generated artefacts without writing or repairing either.
- From the terminal package, `pnpm run contracts:native-v2:check` reaches the same
  generator in the workspace's selected Python environment. Run it inside the
  full authorised runtime for local verification.
- The normal `test:base` and CI `node-core-tests` enumerations both include
  `src/generated`; this retains the generated validator fixture and cold no-eval
  controls rather than merely compiling their imports.
- The unchanged four-way Python package shard selector `packages/*/*/tests/`
  discovers `test_native_risk_v2.py`, `test_native_autonomy_contracts_v2.py`,
  `test_native_autonomy_contracts_v2_generator.py` and
  `test_native_autonomy_contracts_v2_http.py`, along with newly added risk test
  modules such as the separately owned options-risk foundation. There is no
  filename allowlist, keyword/marker filter or ignored module in this selector.
  Normal root and package-local pytest invocations retain existing configuration;
  final composition must verify the new modules' actual collected identities.

Registration checks are not evidence of executed bodies. Retain native reports
for the real generator, Python and Node commands separately; local execution
never represents hosted required-context success or trading readiness.

## Python-only CI prerequisites

`isolated.py` defaults to **`--profile full`**. Its explicit assets, Node, pnpm,
installed dependency and optional browser requirements remain in effect; missing
inputs never select a different profile. **`--profile python-tests`** instead
requires `--source`, `--state-root`, `--uv` and an explicit `--python-root` matching
`source/.venv/bin/python`. It refuses full-profile assets/browser inputs, installed
venv site-packages, private/checkout metadata, escaping links and broad runtime
roots. The Python profile accepts only the selected Python command. It is a
prerequisite profile, not a claim that every non-Python `/usr` binary disappears.

Both profiles use the **same** bubblewrap construction and pre-exec guard:
separate user/network/mount/PID namespaces, private loopback without external
routes, fresh HOME/XDG/tmp/state, cleared environment, hidden operator state,
read-only source/tools, all five capability sets zero and `NoNewPrivs`. The guard
records actual supplementary groups; it does not claim they are empty. Source
write-open must fail with `EROFS`. Existing timeouts and outer containment remain
unchanged. The application/Reticle guards are not weakened or replaced.

After the existing acquisition step (`uv sync --frozen`), the CI step runs:

```sh
uv run --offline --no-sync python -B -I -S tools/acceptance/ci_python_contracts.py --state-root "$RUNNER_TEMP/acceptance-python"
```

The carrier checks the **actual uv-selected Python 3.14.8**, not the setup action's
bootstrap label. Host preparation imports only the standard library (`-B -I -S`),
projects an explicit list of public test/helper and inert registration operands
from the real checkout, and creates a real `venv --without-pip` with that selected
interpreter. `-B` is explicit at every host Python startup: `-I` ignores the
`PYTHONDONTWRITEBYTECODE` environment setting and would otherwise permit stdlib
cache writes. It never copies a relocated venv, rewrites installer provenance,
imports a product/factory/conftest on the host, or acquires dependencies. Git
metadata, graph output, operator files and the original installed environment are
not mounted. The complete selected import closure is verified after isolated
execution against the selected stdlib and projected public tools.

Linux must already provide `/usr/bin/bwrap`, `/usr/sbin/ip`, `/usr/bin/readlink`,
`/etc/ld.so.cache`, usable unprivileged namespaces and the required kernel process
APIs. Missing prerequisites fail closed with retained diagnostics; this step does
not install packages, use sudo, change host policy or retry outside isolation.
Local parity is not proof that a hosted runner supplies these prerequisites.

`ci-receipt.json` links exact source and uv/interpreter bytes to the launcher
receipt and `contracts-execution.json` (including every executed identity, phase
and imported helper). `isolation.json` records the kernel boundary; native
lifecycle receipts retain real negative signals, nonzero status, unknown exits,
canary observations and cleanup results. Failed preparations and logs are kept
in the explicit disposable state root. They are private artefacts, not source.

The registered isolation tests use the real CLI for cold preflight/namespace
refusals and replay the *same* maintained guard for kernel tamper controls. A
second, nested user namespace is deliberately not a prerequisite: it may be
unavailable after the outer capability drop. The actual outer CI launch provides
the positive namespace witness; guard replays are labelled separately. The full
package-local gate still runs every original class and does not become the
smaller CI selection. Its factory/dependency requirements remain full-profile
requirements.

## Diagnostics and integration

`diagnostic-default --python PATH`, `diagnostic-policy --python PATH` and
`diagnostic-paper --python PATH` are explicit non-qualification commands for
carrier plumbing. `diagnostic-paper` accepts `--case NAME`; `diagnostic-default`
accepts only `--case csp` to exercise the original two-case union without claiming
the ordinary Vite bodies. They record the actual interpreter and `diagnostic_only: true`;
their success cannot qualify the maintained Python gate or substitute for the
whole union. SDK provenance, source-byte pins, protocol counts and all application
refusals remain active in diagnostics.

Register the maintained commands in the required no-egress CI jobs and the
terminal's aggregate e2e dispatch. Preserve its existing lanes and the shared-core
carrier registrations. Do not make default `pnpm e2e` green by ignoring/skipping
normal-factory specs. Collection, fixture unit tests and diagnostic results alone
are not acceptance of the final installed runtime.

### Bounded owner handoff

Request delivery shares the original absolute execution-plus-cleanup-plus-delivery
ceiling with every owner wait. Owner startup still consumes the execution budget;
the owner refuses native startup after that earlier deadline. Exec-valid large
environments remain supported. Cancellation closes the control channel (EOF),
rather than attempting another write behind a full request. Early cancellation
uses at most the existing cleanup/delivery remainder, not a renewed execution
window. No timeout, grace, retry or browser budget is added.

`run_owned` returns the real native exit or negative signal only for an ordinary
exit with complete custody. Its mutable `CommandRecord` separates `exit`,
`outcome` and `ownership`. If request delivery times out before the owner can
write a receipt, the public runner still writes a command failure record with
unknown native exit and no invented ownership, reaped children or cleanup proof.
A stopped or lost owner is not a clean drain, even if outer containment later
removes it. The maintained controls witness failure before exact owned rescue.
