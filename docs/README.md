# FlintTrade Documentation

Welcome to the FlintTrade documentation. FlintTrade is a beta-stage,
open-source, modular trading and investment platform for Indian F&O,
commodities, and crypto, with its own backend, native sandbox, direct broker
gateway, and an optional OpenAlgo-compatible bridge. One application serves
three audiences from a single React workspace — **traders** (intraday F&O,
options analysis), **investors** (mutual funds, SIPs, net worth), and
**beginners** (guided learning, paper trading). FlintTrade is AGPL-3.0
licensed and is not production ready.

This folder is the single source of truth for everything outside the source
code itself. If you are reading FlintTrade for the first time, start with the
[User Guide](USER_GUIDE.md) (if you want to trade with it) or the
[Developer Guide](DEVELOPER_GUIDE.md) (if you want to extend it). Everything
else here is reference material you reach for when a specific question arises.

## Independence & attribution

FlintTrade is native-first and **independently built**: its backend, native
broker gateway contract, safety/gating layer, and most application code are
original work by the FlintTrade authors. It is **not a fork** of another trading
application — it interoperates with OpenAlgo only through an optional bridge
adapter rather than bundling OpenAlgo's source. Reference projects were studied
for inspiration; where a specific module was adapted from an open-source project
it carries an in-source `Adapted from:` header and its licence and attribution
are preserved in the repository's
[NOTICE](https://github.com/navaneeshnagarajan/FlintTrade/blob/main/notice) file
(see also [REFERENCES.md](REFERENCES.md)). Reducing the remaining adapted surface
to fully-original implementations is ongoing. FlintTrade is licensed under
[AGPL-3.0](https://github.com/navaneeshnagarajan/FlintTrade/blob/main/LICENSE).

## Index

| File | Audience | One-line description |
|---|---|---|
| [readme.md](../readme.md) | Everyone | Repository landing page. |
| [disclaimer.md](../disclaimer.md) | Everyone | Beta-stage, no-advice, trading-risk, and user-responsibility notice. |
| [INVENTORY.md](INVENTORY.md) | Everyone / Contributor | Build-status inventory — what is (a) built & working, (b) built but untested, (c) referenced but not built. |
| [USER_GUIDE.md](USER_GUIDE.md) | Trader / Investor | Install, connect a broker, walk through every workspace. |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Contributor | Repo layout, dev environment, tests, build, how to add a widget / strategy / broker. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Contributor | Component diagrams, data flow, mode system, package dependency graph. |
| [API.md](API.md) | Integrator | FlintTrade `/ft-api/v1/*` reference, broker/OpenAlgo-compatible bridge endpoints, WebSocket protocol, auth model. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | Trader / Contributor | Supported brokers, exchanges, operating systems, and Python / Node versions. |
| [SEBI_COMPLIANCE.md](SEBI_COMPLIANCE.md) | Trader / Operator | Audit logging, rate limits, retention, kill-switch design for SEBI alignment. |
| [CI.md](CI.md) | Contributor | How the GitHub Actions pipeline runs, what each job covers, and how to read CI failures. |
| [REFERENCES.md](REFERENCES.md) | Everyone | Public attribution and project influence notes. |
| [releases/](releases/) | Everyone | Per-version release notes (chronological). |
| [setup/](setup/) | Contributor / Operator | Platform setup plus static IP, email, backup, and multi-user notes. |
| [screenshots/](screenshots/) | Documentation | UI screenshots referenced from user-facing docs. |
| [superpowers/specs/](superpowers/specs/) | Contributor | Active design specs (brainstorming gate output) for in-flight work. |

## Two-column quick links

### For users (traders and investors)

- **[User Guide](USER_GUIDE.md)** — installation, first broker connection, first paper trade, first live trade, workspace tour, screener / Lab / Automate / AI / Ditto walkthroughs, settings reference, troubleshooting.
- **[Disclaimer](../disclaimer.md)** — required reading before connecting a broker, switching to Live mode, or enabling automation.
- **[API reference](API.md)** — only relevant if you want to script against FlintTrade from outside.
- **[Compatibility matrix](COMPATIBILITY.md)** — which broker, which exchange, which operating system, which Python and Node version.
- **[SEBI compliance notes](SEBI_COMPLIANCE.md)** — audit retention, rate limits, kill-switch behaviour.
- **[Release notes](releases/)** — what changed in each version, in plain English.

### For developers (contributors and integrators)

- **[Developer Guide](DEVELOPER_GUIDE.md)** — repo layout, dev environment setup, running tests, building, adding widgets / strategies / broker adapters, code style.
- **[Architecture](ARCHITECTURE.md)** — Mermaid diagrams, component map, data-flow model, mode-system state machine, WSGI prefix-strip explanation.
- **[CI and quality contract](CI.md)** — how the per-push pipeline is shaped, how to interpret failure logs, how the nightly cross-platform matrix works.
- **[Setup guides](setup/)** — pick the file that matches your operating system, follow it end-to-end, you should have a green test run inside an hour.
- **[Static IP](setup/static-ip-setup.md)**, **[Email](setup/email.md)**, **[Backup](setup/backup.md)**, and **[Multi-user](setup/multi-user.md)** — operator notes for the parts that touch broker access, recovery email, local data, and trust boundaries.
- **[References](REFERENCES.md)** — public credit and attribution notes.
- **[Specs](superpowers/specs/)** — design documents for in-flight work. If you are about to start a feature, check whether a spec already covers it.

## Conventions used in this folder

- **British English** throughout (Indian standard). The codebase target audience
  is primarily Indian retail traders.
- **Relative links** between docs files. No absolute GitHub URLs unless the
  link genuinely points to an external resource.
- **Code blocks** use language hints (`bash`, `python`, `typescript`, `json`)
  so syntax highlighting renders correctly on GitHub and on most editors.
- **No personal information** — no hostnames, IPs, hardware specs, broker
  account numbers, fund amounts, or order IDs appear in committed docs.
  Anything that smells personal lives in `.local/` (gitignored).

## Where the source code lives

The repository is a monorepo with 18 package surfaces: 13 Python packages,
3 applications (`packages/apps/terminal`, `packages/apps/desktop`, and
`packages/apps/site`), 1 shared TypeScript design-system package, and 1
Rust/PyO3 package (`packages/core/ticks`). See
[ARCHITECTURE.md](ARCHITECTURE.md) for the package dependency graph and
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) for the package-by-package map.

## Contributing to the docs

The documentation is treated as a first-class deliverable: docs ship in the
same pull request as the feature or fix they describe. If you change a public
API surface (a `/ft-api/v1/*` endpoint, a widget contract, a strategy template
interface), the matching section of [API.md](API.md) or
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) must be updated in the same commit.

If you spot a typo, a stale code sample, or a broken link, open a pull request
with the fix — small docs PRs are very welcome and merge fast.
