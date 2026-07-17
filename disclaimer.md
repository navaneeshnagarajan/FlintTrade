# FlintTrade Disclaimer

FlintTrade `v0.6.0-beta.9` is a beta-stage open-source project. It is **not production ready**, not a registered investment advisory product, and not a managed trading service.

Use FlintTrade for learning, research, paper trading, local automation experiments, and contributor development first. Do not place live orders until you have reviewed the source, configured broker-side safeguards, verified the backend and terminal locally, and accepted the operational risk yourself.

## No Financial Advice

Nothing in this repository, the terminal UI, the public website, generated docs, MCP surfaces, AI outputs, sample strategies, screenshots, or example configuration is financial, investment, tax, legal, or regulatory advice. All signals, strategy templates, analytics, and AI commentary are educational software outputs.

## Trading Risk

Trading F&O, commodities, crypto, equities, and automated strategies can result in rapid and complete loss of capital. Backtests, paper trades, simulated fills, and demo data do not predict live execution quality or future returns. Broker outages, network delays, API changes, exchange halts, rate limits, incorrect configuration, and software defects can all create unexpected losses.

## Beta Software

FlintTrade currently changes quickly. Some modules use sample data, some integrations require external services, and live broker support depends on the configured native adapter or optional OpenAlgo-compatible server. Treat every release before `1.0.0` as experimental unless a release note explicitly says otherwise.

## User Responsibility

You are responsible for:

- using Explore and Practice modes before Live mode,
- reviewing and testing every strategy before enabling automation,
- keeping broker credentials, API keys, TOTP secrets, and account data private,
- complying with SEBI, exchange, broker, tax, and local regulatory requirements,
- maintaining audit logs where required,
- configuring broker-side limits, static IP allow-lists, and kill switches,
- monitoring live systems actively while orders can be placed.

## No Warranty

FlintTrade is provided under the AGPL-3.0 licence on an "as is" basis, without warranty of any kind. The maintainers and contributors are not liable for trading losses, missed orders, rejected orders, incorrect analytics, data loss, service interruptions, regulatory consequences, or any other damages arising from use of the software.

Read [security.md](security.md), [docs/ORDER_SAFETY.md](docs/ORDER_SAFETY.md), and [docs/USER_GUIDE.md](docs/USER_GUIDE.md) before connecting a broker account.
