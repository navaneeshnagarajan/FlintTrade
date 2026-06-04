# Contributing to FlintTrade

FlintTrade is an open-source Indian fintech project — a modular trading and investment platform for F&O, commodities, and crypto, with a native broker gateway contract plus optional [OpenAlgo](https://github.com/marketcalls/openalgo)-compatible integrations, licensed under AGPL-3.0. We're building it in the open because Indian retail traders deserve serious, transparent tooling, and because every contributor makes the platform sharper.

Whether you're fixing a typo, shipping a new broker adapter, translating the UI into Hindi, or rewriting an entire widget — you're welcome here. This guide tells you everything you need to start.

## Before you start

Please read these first. They're short:

- [`code-of-conduct.md`](code-of-conduct.md) — how we behave with one another.
- [`security.md`](security.md) — how to report a vulnerability privately.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the 10-minute tour of how FlintTrade fits together.

If you're filing a security issue, please do **not** open a public GitHub issue. Use the channels in `security.md`.

## Development setup

FlintTrade is developed on **any operating system** — Linux, macOS, and Windows
are all first-class. There is no single "blessed" machine and no
develop-here/test-there pipeline: CI and the contributor pool validate every
platform. Pick whatever you already run.

### Prerequisites (any OS)

| Tool | Version | How we manage it |
|---|---|---|
| **Python** | `>=3.12,<3.14` | [`uv`](https://docs.astral.sh/uv/) — one fast installer for the interpreter and all Python deps. |
| **Node.js** | `>=20` (22 recommended) | [`pnpm`](https://pnpm.io/) via Corepack — the repo pins the package manager. |
| **Rust** | stable (latest) | [`rustup`](https://rustup.rs/) — only needed to build the `core/ticks` PyO3 tick-engine. |

`uv` and `pnpm` install cleanly on Linux, macOS, and Windows; follow each tool's
own cross-platform instructions. Enable Corepack once so the pinned `pnpm`
version is used automatically:

```bash
corepack enable
```

### Install

```bash
git clone https://github.com/navaneeshnagarajan/FlintTrade.git
cd FlintTrade
cp .env.example .env             # non-secret infrastructure only — never commit .env
uv sync                          # Python interpreter + all Python package deps
pnpm install                     # JS/TS workspace deps (terminal, site, …)
```

To build the Rust tick-engine (optional unless you touch it):

```bash
cd packages/core/ticks && cargo build --release
```

User preferences live in `workspace.json` under your FlintTrade home, generated
from defaults on first run. A sanitised, fully-commented reference lives at
[`workspace.example.json`](workspace.example.json) — secrets there are shown as
`_ref` placeholders, never real values (mirror that discipline in your own).

Detailed, platform-specific walkthroughs live under [`docs/setup/`](docs/setup/):

- [`docs/setup/windows.md`](docs/setup/windows.md)
- [`docs/setup/macos.md`](docs/setup/macos.md)
- [`docs/setup/linux.md`](docs/setup/linux.md)
- [`docs/setup/QUICKSTART.md`](docs/setup/QUICKSTART.md) — the short version

OpenAlgo is optional for local development. See [`docs/setup/QUICKSTART.md`](docs/setup/QUICKSTART.md) for the helper that clones a local-dev OpenAlgo copy only when you want the OpenAlgo-compatible integration path.

## How to run tests

FlintTrade has a large Python and TypeScript test suite. Run it with:

```bash
make test                                        # all pytest tests
make test-fast                                   # stop on first failure
python -m pytest packages/core/core/tests/ -v --import-mode=importlib   # single package
cd packages/apps/terminal && npx vitest run                             # all Vitest tests
```

To run a single file or a single test by name:

```bash
python -m pytest packages/core/core/tests/test_foo.py -v --import-mode=importlib
python -m pytest packages/core/core/tests/test_foo.py::test_name -v --import-mode=importlib
cd packages/apps/terminal && npx vitest run src/widgets/orderpad/OrderPad.test.tsx
cd packages/apps/terminal && npx vitest run -t "places a market order"
```

`--import-mode=importlib` is required when you invoke `pytest` directly (the
flat-package layout needs it). The `make` targets set it for you, so prefer
`make test` unless you're iterating on a single file.

Lint and type-checks are part of CI too — run them locally before pushing:

```bash
make lint                                             # ruff over all Python packages
cd packages/apps/terminal && pnpm run typecheck       # tsc --noEmit, strict mode
```

## How to build

```bash
# Terminal (React + Vite)
cd packages/apps/terminal && npm run build

# Rust tick-engine (PyO3 bindings)
cd packages/core/ticks && cargo build --release
```

The terminal build runs `tsc --noEmit` followed by `vite build`. A clean build is required before any commit that touches `packages/apps/terminal/`.

## Continuous integration

CI runs on GitHub Actions. The full policy and per-workflow breakdown is in
[`docs/CI.md`](docs/CI.md) — read it before adding or editing any workflow. The
guardrails exist because a heavy, daily, multi-platform CI footprint once tripped
GitHub's over-usage protection and disabled Actions for the whole account. Keep
within them:

- **Per-push CI is Linux-only.** The essential quality gate (tests, lint,
  type-check) runs on Ubuntu for every push and non-draft PR. Contributors are
  multi-OS, so we *do* keep cross-platform coverage — but it does not run on
  push or pull-request.
- **macOS and Windows runners run weekly (cron) or on demand only** —
  `nightly-cross-platform.yml` plus `workflow_dispatch`, never on push / PR /
  daily. macOS minutes bill at 10x and Windows at 2x, so daily multi-platform
  matrices are exactly what the abuse heuristics flag.
- **Every job sets `timeout-minutes`.** A job with no timeout is the single
  biggest runaway-usage signal. Sensible values: lint ~10, tests ~30,
  cross-platform ~45.
- **Least-privilege permissions.** Workflows default to `contents: read`; a job
  adds only what it needs (e.g. `pull-requests: write` solely where it comments).
- **`concurrency` with `cancel-in-progress: true`** on push/PR workflows so a
  follow-up push cancels the superseded run.
- **`paths-ignore`** lets doc-only changes skip the heavy test matrix.

If you find yourself adding a daily cron or putting macOS/Windows on `push`,
stop — that is the regression these guardrails prevent.

## Branch and commit conventions

FlintTrade follows [Conventional Commits](https://www.conventionalcommits.org/). The shape is:

```
type(scope): short imperative summary

Optional body — explain the WHY, not just the WHAT.
Wrap at 72 characters. Reference issues with #123.
```

Allowed types and examples:

| Type | When to use it | Example |
|---|---|---|
| `feat` | New user-visible behaviour | `feat(terminal): add sector rotation widget` |
| `fix` | Bug fix | `fix(engine): rate limiter not resetting after market close` |
| `docs` | Documentation only | `docs: clarify OpenAlgo port mapping in architecture guide` |
| `test` | Tests added or refactored, no behaviour change | `test(screener): cover option chain Greeks edge cases` |
| `chore` | Tooling, dependencies, repo housekeeping | `chore: bump vite to 6.4.2` |
| `refactor` | Code restructure with no behaviour change | `refactor(ditto): extract margin calculator into its own module` |
| `perf` | Performance improvement | `perf(tick-engine): avoid allocating per-tick in hot path` |
| `ci` | CI configuration only | `ci: shard widget tests across four runners` |

Scopes are package names (`terminal`, `engine`, `gateway`, `screener`, …) or focus areas (`docs`, `ci`, `repo`).

**Pre-1.0 branching:** while FlintTrade is pre-1.0, contributors commit to `main` directly for trivial fixes (typos, doc tweaks, one-line bug fixes). Pull requests are welcome at any time and encouraged for anything larger than a tiny patch. After v1.0.0 this changes — feature branches and pull requests become mandatory.

Never use `git add -A` or `git add .`. Stage the files you actually changed.

**Never commit personal infrastructure or secrets.** This means no IP addresses,
hostnames, VPN configs or endpoints, broker account names or IDs, fund amounts,
order IDs, API keys, or `.env`. FlintTrade is personal-use open-source: anything
that points at *your* machine, network, or accounts stays out of the repo. Use
placeholders (`<YOUR_HOSTNAME>`, `<YOUR_SERVER_IP>`) in examples, keep real
values in your private, gitignored `.env`, and store secrets as keyring/env
`_ref` references — never plaintext. The `secrets-check` (gitleaks) CI job and a
pre-commit hook are backstops, not a substitute for not staging the file.

## Pull request flow

1. **Fork** the repository on GitHub.
2. **Create a branch** from `main`. Name it after what it does: `feat/terminal-sector-rotation`, `fix/engine-rate-limit-reset`.
3. **Make your change.** Keep commits focused; one logical change per commit.
4. **Run tests locally** before pushing. CI will catch failures but it's faster to find them yourself.
5. **Push** your branch and **open a pull request** against `main`.
6. **Fill in the checklist** in the PR template (tests added, docs updated, conventional commit format).
7. **Address reviewer feedback.** Push follow-up commits rather than force-pushing — it makes review diffs easier to read.
8. **Merge.** Maintainers will squash and merge once CI is green and review is approved.

Tiny doc fixes (typos, broken links) can skip the PR for now and go straight to `main` — but only while we're pre-1.0.

## Code style and lint

### Python

- Follow PEP 8. Lint with `ruff` — `make lint` must be clean before commit.
- Type hints on every public function and class attribute.
- Google-style docstrings (`Args:`, `Returns:`, `Raises:`).
- Absolute imports only — no `from .foo import bar`.
- Target Python 3.12. We use `StrEnum` and other 3.11+ features deliberately.

### TypeScript and React

- Strict mode is on and stays on. No `any`. No `@ts-ignore`. No `@ts-expect-error` without an issue link in the comment.
- All new code lives in `.ts` or `.tsx`. No new `.js` or `.jsx` files.
- Functional components and hooks only.
- Use `shadcn/ui` components and `lucide-react` icons. No raw HTML `<button>`, `<input>`, or `<dialog>`.
- Every widget is registered as a Dockview panel in `widgetFactory.tsx`.

### British English (prose, not code)

User-visible strings, error messages, ARIA labels, docstrings, comments, and documentation use **British English** spelling and idiom:

- behaviour, organise, prioritise, optimise, customise, analyse, recognise, summarise, normalise, serialise
- centred, colour, honour, favour, neighbour, defence, licence (noun) / license (verb)
- "while" (not "whilst" unless you really mean it)

**Exceptions** — code stays as it is, because code is not prose:

- Code identifiers, variable names, function names, class names: keep upstream spelling. `useColorScheme`, `normalize()`, `optimizer` if that's what the library exports.
- CSS class names and Tailwind utilities: American (Tailwind ships American spellings).
- Third-party APIs, library names, brand names: as the upstream spells them.
- **Indian market terminology overrides everywhere:** "expiry" is correct (never "expiration"), "lakh" and "crore" are correct, "scrip" is correct.

## Areas where help is wanted

Look at the [`good first issue`](https://github.com/navaneeshnagarajan/FlintTrade/labels/good%20first%20issue) label for entry points. Beyond that, here's where the project most needs hands:

- **Broker adapters** — especially crypto exchanges beyond Delta (CoinDCX, WazirX, Bybit, Binance India), and any broker not yet covered by the 32 OpenAlgo gateways.
- **Strategy templates** — we ship 94 backtest templates and want more. Mean reversion, momentum, options spreads, sector rotation, volatility plays.
- **AI prompt engineering** — improving the 30 trading skills under `packages/services/ai/skills/`, refining RAG retrieval, sharpening signal explanations.
- **Translations** — Hindi and Tamil first, then other Indian regional languages. The UI needs an i18n pass; we're looking for translators and engineers to set up the framework.
- **Accessibility** — WCAG AA is in place; AAA is the target. Screen-reader testing, keyboard-only flows, contrast audits, focus management.
- **Documentation** — user guides, walkthroughs, video scripts, API references. Every doc PR is a high-value PR.
- **Mobile** — the React Native / Expo app is greenfield. If you build mobile, talk to us.

## Good first issue pointers

If you're new to the project, start with the [`good first issue`](https://github.com/navaneeshnagarajan/FlintTrade/labels/good%20first%20issue) label. Look for:

- Issues tagged `docs` — usually self-contained and a good way to learn the codebase.
- Issues tagged `widget` with a clear screenshot — small, visual, satisfying.
- Issues tagged `test` — adding tests teaches you the module you're testing.

Comment on the issue before you start so we don't double-allocate work.

## Reporting bugs, requesting features, asking questions

We use GitHub issue templates. Pick the one that fits:

- [`.github/ISSUE_TEMPLATE/bug_report.md`](.github/ISSUE_TEMPLATE/bug_report.md) — something broken.
- [`.github/ISSUE_TEMPLATE/feature_request.md`](.github/ISSUE_TEMPLATE/feature_request.md) — something missing.
- Questions and discussion: please use [GitHub Discussions](https://github.com/navaneeshnagarajan/FlintTrade/discussions) rather than the issue tracker.

When reporting a bug, please include OS and version, Python and Node versions, the exact error message, and steps to reproduce. Please **never** include API keys, broker account names, fund balances, order IDs, personal IP addresses, or hostnames.

For security vulnerabilities, follow [`security.md`](security.md) — do not open a public issue.

## License notice

FlintTrade is licensed under the **GNU Affero General Public License v3.0** (AGPL-3.0). By contributing, you agree that your contributions will be licensed under the same terms.

What AGPL-3.0 means in practice:

- **Copyleft.** Any derivative work — fork, modification, or distribution — must also be licensed under AGPL-3.0 and must preserve the licence.
- **Network-use clause.** If you run a modified version of FlintTrade as a network service (a hosted SaaS, an API, a multi-tenant platform), you must offer the modified source code to every user of that service. This is the key difference between AGPL and GPL.
- **No warranty.** The software is provided as-is. See the full [`LICENSE`](LICENSE) for the legal text.

If AGPL-3.0 doesn't work for your use case, please open a discussion before forking — we're open to talking, but we cannot relicense contributed code without contributor consent.

Thank you for being here. Every commit, every issue, every translation, every README improvement makes FlintTrade better for the next person who walks in.
