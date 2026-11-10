# FlintTrade Documentation

Welcome to the FlintTrade documentation. FlintTrade is a beta-stage trading
workspace with evidence-gated native broker contracts and a local Practice sandbox.

This folder is the single source of truth for everything outside the source
code itself. If you are reading FlintTrade for the first time, start with the
[User Guide](USER_GUIDE.md) to run it locally as trading software or the
[Developer Guide](DEVELOPER_GUIDE.md) to extend it. Everything else here is
reference material you reach for when a specific question arises.

## Independence & attribution

FlintTrade owns its backend and gateway. Attribution for adapted modules remains
in the repository notice and source headers.

## Index

| File | Audience | One-line description |
|---|---|---|
| [readme.md](../readme.md) | Everyone | Repository landing page. |
| [disclaimer.md](../disclaimer.md) | Everyone | Beta-stage, no-advice, trading-risk, and user-responsibility notice. |
| [INVENTORY.md](INVENTORY.md) | Everyone / Contributor | Build-status inventory — what is (a) built & working, (b) built but untested, (c) referenced but not built. |
| [DESKTOP.md](DESKTOP.md) | User / Operator | End-user desktop app install, uninstall, configuration, and local build guide. |
| [USER_GUIDE.md](USER_GUIDE.md) | User / Operator | Install, configure local integrations, and walk through every workspace. |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | Contributor | Repo layout, dev environment, tests, build, how to add a widget / strategy / broker. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Contributor | Component diagrams, data flow, mode system, package dependency graph. |
| [TECH_STACK.md](TECH_STACK.md) | Everyone / Contributor | Dependency purposes, version sources, and the in-app build information. |
| [API.md](API.md) | Integrator | FlintTrade `/ft-api/v1/*` reference, native broker contracts, auth model. |
| [COMPATIBILITY.md](COMPATIBILITY.md) | Operator / Contributor | Supported brokers, exchanges, operating systems, and Python / Node versions. |
| [ORDER_SAFETY.md](ORDER_SAFETY.md) | Operator / Contributor | Audit logging, rate limits, retention, and kill-switch design notes. |
| [CI.md](CI.md) | Contributor | How the GitHub Actions pipeline runs, what each job covers, and how to read CI failures. |
| [REFERENCES.md](REFERENCES.md) | Everyone | Public attribution and project influence notes. |
| [releases/](releases/) | Everyone | Per-version release notes (chronological). |
| [setup/](setup/) | Contributor / Operator | Platform setup plus static IP, email, and backup notes. |
| [GLOSSARY.md](GLOSSARY.md) | Everyone | Shared product vocabulary. |
| [product-modes.mdx](product-modes.mdx) | User / Contributor | Practice and Live are Modes. Connected (read) is a broker status. Example is sample data, versus Sample / Unavailable / Live / Stale provenance, and Home versus Trade ownership. |
| [screenshots/](screenshots/) | Documentation | UI screenshots referenced from user-facing docs. |

## Two-column quick links

### For users and operators

- **[User Guide](USER_GUIDE.md)** — installation, optional broker connection, sandbox workflow, Live-mode safeguard verification, workspace tour, settings reference, and troubleshooting.
- **[Desktop App](DESKTOP.md)** — native app download, install, uninstall, workspace configuration, and local build instructions.
- **[Disclaimer](../disclaimer.md)** — required reading before connecting a broker, switching to Live mode, or enabling order-capable automation.
- **[API reference](API.md)** — only relevant if you want to script against FlintTrade from outside.
- **[Compatibility matrix](COMPATIBILITY.md)** — broker adapters, exchange segments, operating systems, and Python / Node versions.
- **[Order safety notes](ORDER_SAFETY.md)** — audit retention, rate limits, kill-switch behaviour.
- **[Release notes](releases/)** — what changed in each version, in plain English.

### For developers (contributors and integrators)

- **[Developer Guide](DEVELOPER_GUIDE.md)** — repo layout, dev environment setup, running tests, building, adding widgets / strategies / broker adapters, code style.
- **[Architecture](ARCHITECTURE.md)** — Mermaid diagrams, component map, data-flow model, mode-system state machine, WSGI prefix-strip explanation.
- **[Technology stack](TECH_STACK.md)** — what each major dependency does, where its version is recorded, and how dependency updates are reviewed.
- **[CI and quality contract](CI.md)** — how the per-push pipeline is shaped, how to interpret failure logs, how the nightly cross-platform matrix works.
- **[Setup guides](setup/)** — pick the file that matches your operating system, follow it end-to-end, you should have a green test run inside an hour.
- **[Static IP](setup/static-ip-setup.md)**, **[Email](setup/email.md)**, and **[Backup](setup/backup.md)** — operator notes for broker access, recovery email, and ordinary bhavcopy archives.
- **[Glossary](GLOSSARY.md)** — shared product vocabulary.
- **[References](REFERENCES.md)** — public credit and attribution notes.
- **[Roadmap](../ROADMAP.md)** — what works today, what is in progress, and what comes next.

## Conventions used in this folder

- **British English** throughout (Indian standard).
- **Relative links** between docs files. No absolute GitHub URLs unless the
  link genuinely points to an external resource.
- **Code blocks** use language hints (`bash`, `python`, `typescript`, `json`)
  so syntax highlighting renders correctly on GitHub and on most editors.
- **No personal information** — no hostnames, IPs, hardware specs, broker
  account numbers, fund amounts, or order IDs appear in committed docs.

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
