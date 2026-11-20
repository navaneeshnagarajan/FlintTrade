# FlintTrade roadmap

FlintTrade `v0.0.1` is self-hosted trading software for manual, automated, algorithmic, and AI-assisted workflows on Indian markets. This page states what works today, what is in progress, and what comes next. Shipped detail lives in [changelog.md](changelog.md).

Broker connections use six native adapters: Dhan, Upstox, Kotak Neo, INDmoney, Groww, and Delta Exchange. A broker session cannot be started from the terminal today. Practice mode and example data work without a broker. Broker writes return 503 and broker reads return 409. Live order placement stays disabled unless it is explicitly unlocked and every safety layer passes.

## Done

- Server-enforced Explore, Practice, and Live modes. Practice orders fill in the local sandbox.
- A five-layer safety check on every reachable live order, then the broker router. There is no separate ungated order path.
- Operator sign-in, mode-scoped sessions, and a PIN that re-authenticates an existing session.
- Encrypted broker credential storage, credential replay, and an OAuth connect flow. Those HTTP routes return 503 for writes and 409 for reads.
- A trade journal, option-chain analytics, indicators, and the terminal workspace.
- An Electron desktop shell that builds the application from a managed local source checkout. Installers are published only as a complete set with a checksum manifest.
- When an LLM is configured, Chat may use Practice fills and native live-read feeds for analysis. Suggest stays labelled illustrative. Chat never shows green Connected without a real LLM. Measure later: profitable alphas are not a release criterion. Live order placement stays disabled unless it is explicitly unlocked and every safety layer passes.

## In progress

- Broker sessions inside the terminal. Practice mode and example data already work without a broker.
- Live order placement, which stays disabled until it is explicitly unlocked and every safety layer passes.
- Desktop installer publication, including distribution signing.
- A full Practice-day run of the automated signal, order, journal, and learning loop.

## Next

- Broker sessions that an operator can start from the terminal, with reads and writes going through the safety gate.
- A published desktop installer set: four installers and `SHA256SUMS.txt` together.
- The Practice-day automation loop, with Live placement still blocked unless explicitly unlocked.

## Constraints

- Development and automated checks use Explore and Practice. Live placement is an explicit operator action for that session.
- New order paths use the same safety gate and broker router as manual orders.
- FlintTrade ships order rate limits, broker sign-in, daily session refresh, and the AGPL-3.0 licence. It is not a compliance product.
