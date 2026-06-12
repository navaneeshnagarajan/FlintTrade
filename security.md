# Security Policy

Thank you for helping keep FlintTrade and its users safe.

## Supported versions

FlintTrade is pre-1.0. Only the latest minor release receives patches.

| Version | Supported |
|---------|-----------|
| 0.6.x   | Yes (latest, receives patches) |
| 0.5.x   | No                             |
| < 0.5   | No                             |

When 1.0 ships, this policy will expand to cover the previous minor for a defined window.

## Reporting an issue

Please report issues privately. Do **not** open a public GitHub issue with details.

**Primary channel:** [Open a private GitHub Security Advisory](https://github.com/navaneeshnagarajan/FlintTrade/security/advisories/new) for this repository. GitHub Security Advisories let maintainers triage, discuss, and coordinate a fix in private, then publish the advisory once a patch is available.

**Fallback channel:** If you cannot use Security Advisories, open a regular issue titled `[SECURITY]` with no technical detail, asking a maintainer to contact you privately. A maintainer will follow up.

## What to include in a report

- A description of the issue and the affected component or endpoint.
- Steps to reproduce, ideally with a minimal test case.
- The version of FlintTrade and the operating system you tested on.
- Whether the issue is reachable without authentication, or requires a logged-in session, or requires a specific mode (Explore / Practice / Live).
- Any logs or screenshots — please redact broker credentials, account identifiers, and order identifiers before sharing.

## Response timeline

| Stage | Target |
|-------|--------|
| Initial acknowledgement | Within 7 days |
| Triage outcome (accepted / declined / needs more info) | Within 14 days |
| Fix or status update | Within 30 days |
| Public disclosure | Up to 90 days from confirmed report |

If a report stalls or you have not heard back within these windows, please open a second Security Advisory referencing the first.

## Scope

Reports about the FlintTrade codebase itself are in scope. This includes everything under `packages/`, `scripts/`, the GitHub workflows under `.github/`, the build configuration (Docker, Makefile, `pyproject.toml`, `flint.toml`), and the documentation under `docs/` and the repo root.

The mode system (Explore / Practice / Live), the authentication layer (JWT plus API key), the order-safety proxy, the strategy sandbox executor, and any code that touches broker credentials or trade-execution paths are all in scope.

## Out of scope

- Issues in upstream projects FlintTrade depends on or talks to over the network — [OpenAlgo](https://github.com/marketcalls/openalgo), OpenClaw, or any third-party broker integration shipped by those projects. Report those to their respective maintainers.
- Issues in third-party Python or Node dependencies. Report those upstream (the corresponding `pyproject.toml` or `package.json` is the source of truth).
- Issues caused by user misconfiguration — for example, committing `.env` files with live credentials, exposing the FlintTrade backend port to the public internet, or running the broker gateway without TLS.
- Self-inflicted issues from running modified forks. We can only support unmodified FlintTrade.

## Recognition

If you'd like to be credited, we'll add your name (or chosen handle) to the next release's `changelog.md` under a "Security" subheading. If you'd rather stay anonymous, we'll respect that — just tell us in the report.

## Safe-harbour for researchers

We will not pursue legal action against anyone who:

- Reports an issue privately through the channels above,
- Acts in good faith and avoids privacy violations, service disruption, data destruction, and degradation of the user experience for others,
- Gives us reasonable time to fix the issue before any public discussion.

## Recent advisories

Once published, advisories live at: <https://github.com/navaneeshnagarajan/FlintTrade/security/advisories>.

Thank you for taking the time to report responsibly — it makes the platform better for every trader who depends on it.
