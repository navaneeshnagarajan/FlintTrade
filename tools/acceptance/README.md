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
  reconciles two disjoint positive native test lists. Ordinary cases use Vite;
  the two unchanged `schema-csp` cases use a fresh production build and a
  test-scoped anonymous normal factory. Vite is stopped before the factory owns
  its port. No CSP cases are ignored/skipped and no private server path is needed.
  The parser companion never configures Zod; the installed entry must do so.
  The separate nonce-bearing external eval control still requires the real CSP
  violation/report and the unchanged registry's fatal rejection. Factory cleanup
  uses the existing request drain and complete lifecycle owner, not a subset of
  ad-hoc close calls. `e2e:default` dispatches this carrier, not bare Playwright.
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
