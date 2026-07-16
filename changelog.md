# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

## [0.6.0-beta.4](https://github.com/navaneeshnagarajan/FlintTrade/compare/v0.6.0-beta.3...v0.6.0-beta.4) (2026-07-16)


### Added

* **desktop:** thin-shell installers with first-run payload bootstrap ([fc6c716](https://github.com/navaneeshnagarajan/FlintTrade/commit/fc6c716ec1238d0f7126dd1883f19792be539ab1))


### Fixed

* **ci:** seal macOS bundles, guard installer sizes, drop sidecar stubs ([4539607](https://github.com/navaneeshnagarajan/FlintTrade/commit/4539607679945123d7095e146a268c4298ce3a0a))
* **release,site:** case-correct readme guard path and complete the fallback shape ([370319f](https://github.com/navaneeshnagarajan/FlintTrade/commit/370319f3366dd0b4e58669f8b6b4505cc9ece3b7))
* **site:** tag-agnostic download fallback and thin-shell copy ([38f8008](https://github.com/navaneeshnagarajan/FlintTrade/commit/38f800896f414ac297026bb52540052d71b2a042))


### Changed

* **terminal:** route the last hardcoded /ft-api fetches through getBase ([a6ee786](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6ee786e721b316fe0a130a6ff860873ba52d6d4))

## [0.6.0-beta.3](https://github.com/navaneeshnagarajan/FlintTrade/compare/v0.6.0-beta.2...v0.6.0-beta.3) (2026-07-16)


### Fixed

* **ci:** arch-qualify the macOS updater bundle before publishing ([b513941](https://github.com/navaneeshnagarajan/FlintTrade/commit/b513941ccc3d2ec455bdb2015d077028ae1bb904))
* **ci:** unblock installer rebuilds for the current release tag ([5d9b66c](https://github.com/navaneeshnagarajan/FlintTrade/commit/5d9b66c50234761fbc17abd9d83d227b81aa1a5e))
* **release:** keep uv.lock and NOTICE in step with version propagation ([3f8721a](https://github.com/navaneeshnagarajan/FlintTrade/commit/3f8721a84911473a2f5a38289065f2b2b5c7f64f))

## [0.6.0-beta.2](https://github.com/navaneeshnagarajan/FlintTrade/compare/v0.6.0-beta.1...v0.6.0-beta.2) (2026-07-16)


### Added

* **ai,settings:** persist LLM config from the UI ([a7cd620](https://github.com/navaneeshnagarajan/FlintTrade/commit/a7cd620e5a839d137fa194819879dbfd272c1ab0))
* **ai:** make the componentised RAG pipeline canonical ([850ad29](https://github.com/navaneeshnagarajan/FlintTrade/commit/850ad298e2de389cf7de0b94ec9b25a4c906fa2b))
* **ai:** preserve legacy advisor refinements ([548e56e](https://github.com/navaneeshnagarajan/FlintTrade/commit/548e56e7222a49053c719c6005dc26103ea437d4))
* **ai:** replace OpenClaw with a 6-backend AI layer (Cerebras, Claude API/OAuth, Codex streaming, Hermes/Antigravity catalogued) ([951043b](https://github.com/navaneeshnagarajan/FlintTrade/commit/951043bbe4ba8438d7da60fa903077e49f934124))
* **ai:** secure canonical signal models ([3b0a5d3](https://github.com/navaneeshnagarajan/FlintTrade/commit/3b0a5d3d1f730f469f539567d4953257e52d39d6))
* **ai:** stream configurable team analyses ([8d49cc0](https://github.com/navaneeshnagarajan/FlintTrade/commit/8d49cc06cc019799a490a49515b92542cb1a8f78))
* **ai:** stream Hermes (ACP) + Antigravity (agy) agent runtimes (Wave B2) ([3051f56](https://github.com/navaneeshnagarajan/FlintTrade/commit/3051f5660c80a796aa3ae9c5487345d0c7591ba5))
* **ai:** unify live and ML signal feeds ([df8e79f](https://github.com/navaneeshnagarajan/FlintTrade/commit/df8e79f4fb0432d7a7b7d71ea612867a443d8554))
* **ai:** unify market news ingestion ([3da1ba1](https://github.com/navaneeshnagarajan/FlintTrade/commit/3da1ba10cac3ac1e4ec308890f9be40764e633d5))
* **ai:** unify single and batch trade reflection ([aa96d1d](https://github.com/navaneeshnagarajan/FlintTrade/commit/aa96d1dcd40f9063e08c05c30bd9b0501c20fe30))
* **ai:** unify team orchestration modes ([9d0468d](https://github.com/navaneeshnagarajan/FlintTrade/commit/9d0468d0fef7050b5a49bce0dbd47fb5e4739bd8))
* **ai:** unify tiered memory backends ([1a21c6d](https://github.com/navaneeshnagarajan/FlintTrade/commit/1a21c6dd248d62b5354e05a648b4a591ba60d554))
* **ai:** wire canonical signal retraining ([1e0c87e](https://github.com/navaneeshnagarajan/FlintTrade/commit/1e0c87ec6b76546dd3386a4c3e9bfe74d2e079bb))
* **ai:** wire structured market sentiment ([3697c38](https://github.com/navaneeshnagarajan/FlintTrade/commit/3697c3886922a7643bf690e60bb866464adf0f39))
* **app:** consolidate the daily-driver runtime ([dff61a7](https://github.com/navaneeshnagarajan/FlintTrade/commit/dff61a7ebaa4478bec445945ff58b866cbd54b9d))
* **auth:** close the Phase 1 auth seams — G5/G7/G9/G10 + session-bound PIN ([f10f0ae](https://github.com/navaneeshnagarajan/FlintTrade/commit/f10f0ae1cd24648eb73a59b7eb7fa65be1cfe425))
* **automation:** native Telegram bot — reachable kill switch, no python-telegram-bot (G30) ([3f30f75](https://github.com/navaneeshnagarajan/FlintTrade/commit/3f30f750c29fc0d01fe363b366f0e9096cffaa3b))
* **brokers:** activate Upstox + Kotak Neo native adapters (SDK pins + licence) ([67fc12e](https://github.com/navaneeshnagarajan/FlintTrade/commit/67fc12ec72aee624ae3acb2545228835f61674f1))
* **brokers:** add disabled Groww native adapter ([d7381ac](https://github.com/navaneeshnagarajan/FlintTrade/commit/d7381acad115ba11eba7d7e4296a9a1149545d39))
* **brokers:** add Groww to redacted live probe ([c5f1449](https://github.com/navaneeshnagarajan/FlintTrade/commit/c5f1449adbce87590d72f3887ef746f92659b324))
* **brokers:** catalogue arrow and TradeSmart bridge brokers (P12) ([929dff2](https://github.com/navaneeshnagarajan/FlintTrade/commit/929dff207e2a911d10268d805152a2e3d70e85af))
* **brokers:** catalogue OpenAlgo's self-hosted MCP as the first-preference entry ([7271f07](https://github.com/navaneeshnagarajan/FlintTrade/commit/7271f074e80e7426b11b0843e0032fc0ff1f8b93))
* **brokers:** consolidate native trading workflows ([46939e5](https://github.com/navaneeshnagarajan/FlintTrade/commit/46939e53d35aae3a0052882371ed826baaaacd82))
* **brokers:** enrich hosted MCP setup metadata ([de175d5](https://github.com/navaneeshnagarajan/FlintTrade/commit/de175d58ffb3fe9a554372e848378a53acaf815c))
* **brokers:** expose broker mcp client setup snippets ([b1213d4](https://github.com/navaneeshnagarajan/FlintTrade/commit/b1213d4e74af28c02b1b00e370e5456fa69942b6))
* **brokers:** in-app broker connect UI + per-broker auth-method catalogue ([c19882c](https://github.com/navaneeshnagarajan/FlintTrade/commit/c19882cdb7b908bf53899c9183735a17b89a4c42))
* **brokers:** surface native SDK readiness ([74ac701](https://github.com/navaneeshnagarajan/FlintTrade/commit/74ac70155512b6299112395bad00be61fec3bf1e))
* **ci:** automate version bumps and releases with release-please ([2dc1e3d](https://github.com/navaneeshnagarajan/FlintTrade/commit/2dc1e3dc2a91495d28f1d06eddf87bc1691ae73b))
* **ci:** publish the frozen backend as a hash-verified payload asset ([51e0901](https://github.com/navaneeshnagarajan/FlintTrade/commit/51e0901b69726f2a6101b213d76686ced466f957))
* **ci:** sign, notarise, and emit updater artifacts when secrets exist ([44627aa](https://github.com/navaneeshnagarajan/FlintTrade/commit/44627aa658f867395a02457bad3e6ccf9ad44964))
* **core:** first-class web surface with a fail-closed remote bind ([43ca26c](https://github.com/navaneeshnagarajan/FlintTrade/commit/43ca26cef35d3a76138a0e0b937f4cea8336078e))
* **core:** stream captured ticks into live signals ([64bb985](https://github.com/navaneeshnagarajan/FlintTrade/commit/64bb985652e70c27e521904fc23ce0a897110cae))
* **data:** authenticated gated-audit PDF/CSV export + summary (G37 A3) ([2bd443c](https://github.com/navaneeshnagarajan/FlintTrade/commit/2bd443c6a687457e55e6d8f1440e945e2b70f4a8))
* **data:** make the audit log a real tamper-evident hash chain (G26) ([acca656](https://github.com/navaneeshnagarajan/FlintTrade/commit/acca656d158c1c41d83508605e08af7fb5e06676))
* **data:** scheduled EOD delta-sync + tick capture mode config ([21e821c](https://github.com/navaneeshnagarajan/FlintTrade/commit/21e821cfa07671fd1c63c12d9827173b0fad43be))
* **data:** tick-capture status/query/watchlist API + configurable capture list ([3ea07fb](https://github.com/navaneeshnagarajan/FlintTrade/commit/3ea07fba671442a39488a8b0c06b926c65efe287))
* **deps:** declare and install the full ML/AI stack — 68 skipped tests now run ([4f92cf0](https://github.com/navaneeshnagarajan/FlintTrade/commit/4f92cf09dcfd89583f3398e55423a29210e265ca))
* **desktop:** background runtime — close-to-tray, tray, hotkey, native notifications ([7cfd407](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cfd407359f19a253e627511e445cf43d6bddc19))
* **desktop:** install and update from release assets ([87e69a5](https://github.com/navaneeshnagarajan/FlintTrade/commit/87e69a558c4e665885b271d3f978971247bdfaf5))
* **desktop:** manage the backend payload like the Ollama runtime ([08344ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/08344ef56deffb8947707c8ab4d82f4fb747814a))
* **desktop:** one-click native updates via tauri-plugin-updater ([5eb43c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/5eb43c81f7a1d27305c7acc92405d0ea9274a625))
* **desktop:** sidecar watchdog, OAuth opener, in-app update-by-rebuild ([74760c3](https://github.com/navaneeshnagarajan/FlintTrade/commit/74760c39681b3e690fb508c3c9420d8cf0ce615e))
* **engine:** gated bracket orders — every leg through gate_order -&gt; BrokerRouter ([8128b4f](https://github.com/navaneeshnagarajan/FlintTrade/commit/8128b4fff2996ef056ec1519ccc295112036f2bb))
* **engine:** route basket/split orders through the gate, wire them live (G13) ([9114fde](https://github.com/navaneeshnagarajan/FlintTrade/commit/9114fde4a33b4bb4b6301687ec84bfb89d73ba8d))
* **gateway:** native broker credential-replay login + capture (Phase 1 G3/G4) ([dd29fd9](https://github.com/navaneeshnagarajan/FlintTrade/commit/dd29fd94ad85ee425f7a5a16779ebfd051da8131))
* **gateway:** native broker OAuth connect flow (Phase 1 G4) ([89fcb74](https://github.com/navaneeshnagarajan/FlintTrade/commit/89fcb744485214ae9a9535b3a4b2c6968f2fc32f))
* **gateway:** support Groww TOTP token login ([85f96c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/85f96c8188134c2e742a3cdaf0149f2d4690c8a6))
* **groww:** expose OHLC and expiry reads ([d63458a](https://github.com/navaneeshnagarajan/FlintTrade/commit/d63458ab3b1e06057c128d8b723ec7447c55dfcb))
* **historical:** NSE bhavcopy downloader + local-store browse API ([e20c559](https://github.com/navaneeshnagarajan/FlintTrade/commit/e20c55939ff12e5485dcef8b55af821e29e4b0d6))
* **install:** fetch release metadata from GitHub release URLs ([fd3d6cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd3d6cf98eac978c0df31b9799de96db121dd8e8))
* **invest:** value-visibility (hide amounts) toggle (P7) ([8df16f5](https://github.com/navaneeshnagarajan/FlintTrade/commit/8df16f59c72ed35136580cdca943c4c7f90e1cd5))
* **journal:** port TradeJournal to SQLite + FTS5 with full-text search (G31) ([57c3b12](https://github.com/navaneeshnagarajan/FlintTrade/commit/57c3b12ee22c4712786abb9b65ae752fee2a2f1d))
* **journal:** wire the Trade Journal REST API + fix the migration (G31) ([c37f76e](https://github.com/navaneeshnagarajan/FlintTrade/commit/c37f76e9b386b7115bfd68d9fb7d94adbc6733fc))
* **native:** expose broker-specific read surfaces ([e4b0198](https://github.com/navaneeshnagarajan/FlintTrade/commit/e4b0198e10ceb7043d6919751062a4e304bc53d4))
* **orders:** enforce HTTP rate limiting on the reachable order routes ([d35e0fc](https://github.com/navaneeshnagarajan/FlintTrade/commit/d35e0fc5f507fb02b2e202dacc04f7a2033a20a6))
* **screener,scalper:** one lot-size table + Scalper bracket legs ([5b76333](https://github.com/navaneeshnagarajan/FlintTrade/commit/5b76333f44287ffe714279c88a646a1e3ac646c7))
* **screener:** candlestick pattern detection (W4) ([f5893ea](https://github.com/navaneeshnagarajan/FlintTrade/commit/f5893ea876016da9eebfb7c4724ace122ebe1e9d))
* **screener:** cash-future & cross-exchange arbitrage scanner (DP3) ([e296b50](https://github.com/navaneeshnagarajan/FlintTrade/commit/e296b50ed43c58fe8494ec87e8d5d7446b0d5a79))
* **screener:** FII long/short ratio surface (DP1) ([4300c4e](https://github.com/navaneeshnagarajan/FlintTrade/commit/4300c4ea2a422a3a5b6a1534b8e008b87e26aa12))
* **screener:** gamma density analytics surface (DP2) ([e87bb4d](https://github.com/navaneeshnagarajan/FlintTrade/commit/e87bb4d8ec9c9cedeff269cb3c2c513a18876829))
* **screener:** index contribution panel (W7) ([81c11ab](https://github.com/navaneeshnagarajan/FlintTrade/commit/81c11abc168548dd2bd542dc3ddf075cd9cfbc22))
* **site,scripts:** one-command build-on-device installers + /download page ([56636e3](https://github.com/navaneeshnagarajan/FlintTrade/commit/56636e3863d7777955472951be61f83e8b329f68))
* **terminal:** add configurable AI team runs ([5bf61d9](https://github.com/navaneeshnagarajan/FlintTrade/commit/5bf61d935e534a7e00ebeb4d938b618d6ccc999f))
* **terminal:** add watchlist column controls ([a82ce16](https://github.com/navaneeshnagarajan/FlintTrade/commit/a82ce1638d8154d2732c96884cc45d05161d7543))
* **terminal:** AI Backends widget + Cerebras/Claude-OAuth in Settings (replaces OpenClaw) ([425ebb2](https://github.com/navaneeshnagarajan/FlintTrade/commit/425ebb2980b7c4d7a294c879b1de541cb5829271))
* **terminal:** daily-driver trade loop — live wiring, reconciliation, honest errors ([f795a71](https://github.com/navaneeshnagarajan/FlintTrade/commit/f795a71c9f8419cd131f103dae3fecd48aa27114))
* **terminal:** Local Data panel (tick capture + store + bhavcopy) & CI shard fix ([4b26cc8](https://github.com/navaneeshnagarajan/FlintTrade/commit/4b26cc8a9c5d3fe39d1a339b8ffaa30f8028aa84))
* **terminal:** Time & Sales tape widget (W3) ([90b567a](https://github.com/navaneeshnagarajan/FlintTrade/commit/90b567acaafbc288cf1c7e6eb2495c794b460427))
* **terminal:** Trade Journal widget — searchable annotated journal UI (G31) ([bbb1fd1](https://github.com/navaneeshnagarajan/FlintTrade/commit/bbb1fd11ea3ba51f6b1ec7fb8f188735e0c046d7))
* **ticks:** re-export the full compiled tick-engine surface (G29) ([8c5f875](https://github.com/navaneeshnagarajan/FlintTrade/commit/8c5f8755efdaec47c6fb6e330ae7a4c8ba12fdcf))
* **watchlist:** row-hover quick Buy/Sell → prefilled gated ticket (W2) ([98b5c3e](https://github.com/navaneeshnagarajan/FlintTrade/commit/98b5c3ef5308a71521d810c65b85d90737d4c7de))
* **watchlist:** user-defined formula builder (W1) ([64ec8eb](https://github.com/navaneeshnagarajan/FlintTrade/commit/64ec8eb4681558f9918c5029553737feab074732))
* **webhooks:** GoCharting alert webhook source (B2) ([6f739f6](https://github.com/navaneeshnagarajan/FlintTrade/commit/6f739f66d2d8d457cda34683fe2cc7bfe4167802))
* **webhooks:** wire encrypted named webhook secrets ([b891b8c](https://github.com/navaneeshnagarajan/FlintTrade/commit/b891b8cd495174cdf65be2516cf216e4043712b6))


### Fixed

* **ai,terminal:** harden unified signal feed ([c35c310](https://github.com/navaneeshnagarajan/FlintTrade/commit/c35c31054ce7939849ad6792815726ce05bfef6d))
* **ai:** bind agents and training to market sessions ([e5962c4](https://github.com/navaneeshnagarajan/FlintTrade/commit/e5962c486773bed1c0dec99cbaf2191111d4f8ba))
* **ai:** bound Antigravity stdout retention + broaden env-secret scrub (B2 audit) ([a995875](https://github.com/navaneeshnagarajan/FlintTrade/commit/a995875622f14fe236be85f78766ae4680ee8324))
* **ai:** fail closed before starting an autonomous agent on a defaulted target ([39699f1](https://github.com/navaneeshnagarajan/FlintTrade/commit/39699f114a3f39c9cad00b22fdf2bacc852e5fa7))
* **ai:** harden canonical RSS compatibility ([f4ff126](https://github.com/navaneeshnagarajan/FlintTrade/commit/f4ff12698a166e336a234999d8ecaeee40a42978))
* **ai:** harden Codex streaming (64KiB frames, leaks, honest cancel) + OAuth token hygiene ([bf33317](https://github.com/navaneeshnagarajan/FlintTrade/commit/bf33317a876c290aa0798d2e78eda9f6b950d6e5))
* **ai:** harden legacy signal compatibility ([91d7f48](https://github.com/navaneeshnagarajan/FlintTrade/commit/91d7f48cac8afaed3f550ce36daf3c28bfe5e605))
* **ai:** harden live signal replay and filtering ([593b787](https://github.com/navaneeshnagarajan/FlintTrade/commit/593b7870f80461f3fde62fd42e0701344b5176c3))
* **ai:** harden live signal state ([c30bd3a](https://github.com/navaneeshnagarajan/FlintTrade/commit/c30bd3a98a4a353e0be13c74aea980db3e26cb84))
* **ai:** make signal model publication atomic ([07eb94d](https://github.com/navaneeshnagarajan/FlintTrade/commit/07eb94d1da64ece88b863aeed5b6680f89ca07ce))
* **ai:** preserve pre-entry agent stops ([7d6fed2](https://github.com/navaneeshnagarajan/FlintTrade/commit/7d6fed27fcfa885d0e1fd176ed5036c41ca39a0b))
* **ai:** preserve retraining policy and guards ([7501acd](https://github.com/navaneeshnagarajan/FlintTrade/commit/7501acd6046b19192cd6b7344c3fa9e70c8d005d))
* **ai:** preserve signal model integrity migration ([61fc5e5](https://github.com/navaneeshnagarajan/FlintTrade/commit/61fc5e59572f34222f903b5e88f6551cfb395604))
* **ai:** preserve source-time market semantics ([101db87](https://github.com/navaneeshnagarajan/FlintTrade/commit/101db87585da00e098303302f5a51d35ca192308))
* **ai:** preserve source-time signal integrity ([97250fa](https://github.com/navaneeshnagarajan/FlintTrade/commit/97250fa644cc2759d25b3c9c6bdb998bd6efc489))
* **ai:** preserve trustworthy signal state ([594111f](https://github.com/navaneeshnagarajan/FlintTrade/commit/594111f1584f0ed657667c8f718d9e7687b3b90c))
* **ai:** qualify live signal identities ([aa51dab](https://github.com/navaneeshnagarajan/FlintTrade/commit/aa51dabb4b72d5f2db662b73277b4888e20c5a96))
* **ai:** respect exchange lifecycle ownership ([debeb3c](https://github.com/navaneeshnagarajan/FlintTrade/commit/debeb3cac961c04dd40ce41409ae6b1b49135b44))
* **ai:** respect instrument market hours ([193275d](https://github.com/navaneeshnagarajan/FlintTrade/commit/193275dab76a39176c71f2e41f3a6eccc367636f))
* **ai:** route signal history through core OpenAlgo client ([45e2699](https://github.com/navaneeshnagarajan/FlintTrade/commit/45e26997393c206cc8c34370c5cc40b124d55dbd))
* **ai:** scrub operator provider secrets from the Antigravity subprocess env ([515e73d](https://github.com/navaneeshnagarajan/FlintTrade/commit/515e73d87a6f6b5078171ac2ba2ba8b24050e935))
* **ai:** serialise autonomous agent startup ([3416187](https://github.com/navaneeshnagarajan/FlintTrade/commit/34161877e9fb7c669cab42dedd74797b9a83e98c))
* **ai:** synchronise scheduled signal rosters ([244ba85](https://github.com/navaneeshnagarajan/FlintTrade/commit/244ba857f9e04212aaa724052da10b58a9a1998e))
* **ai:** train only on closed market data ([c863673](https://github.com/navaneeshnagarajan/FlintTrade/commit/c863673f97f4110c53b8ce6cf89dc1d02d72c2af))
* **auth,brokers:** set-PIN-later, setup mode transition, fail-closed demotion, Codex-wave follow-ups ([b111e84](https://github.com/navaneeshnagarajan/FlintTrade/commit/b111e84964824bf122e332471e65ffb2cdc82879))
* **auth:** actually enforce the login/PIN/setup brute-force rate limits ([3becb4d](https://github.com/navaneeshnagarajan/FlintTrade/commit/3becb4d11ecc0b9e34ac69a9f897f68030ef7340))
* **auth:** make Practice mode reachable and PIN unlock mode-preserving ([8113810](https://github.com/navaneeshnagarajan/FlintTrade/commit/81138102af888674df87c2ae7989732ffac505aa))
* **auth:** resolve 10 residuals from the re-audit of the fix commit ([dff95b6](https://github.com/navaneeshnagarajan/FlintTrade/commit/dff95b6f330a939f28b70a7f264d23355b5903db))
* **auth:** resolve 24 findings from the Phase 1 auth-seams audit ([d35bde9](https://github.com/navaneeshnagarajan/FlintTrade/commit/d35bde95e46f33f0e494eb4b65dda116fb2d8feb))
* **auth:** transactional connect rollback + cross-stack transient probe ([a052446](https://github.com/navaneeshnagarajan/FlintTrade/commit/a052446ca83ba1acc7221b37617facdd98c99d3f))
* **automation:** retain live calendar references ([da2014f](https://github.com/navaneeshnagarajan/FlintTrade/commit/da2014f78987cb9a0afdbf16d0706b766647a56b))
* **brokers:** activate Dhan resolver for native routes ([82786f7](https://github.com/navaneeshnagarajan/FlintTrade/commit/82786f7140d583e78faa327bf830b3a43d51678b))
* **brokers:** align broker verification surfaces ([ac2cc07](https://github.com/navaneeshnagarajan/FlintTrade/commit/ac2cc0715c4a858e69865622c9b5b619fb106ee4))
* **brokers:** align dashboard token reset expiry ([d697d04](https://github.com/navaneeshnagarajan/FlintTrade/commit/d697d0464480b3197c2b958718708d0883834ad4))
* **brokers:** align gateway primary eligibility ([5ae5553](https://github.com/navaneeshnagarajan/FlintTrade/commit/5ae555375e6ae1a6d4359bae1ef85747a96172d2))
* **brokers:** align Groww live probe reads ([ae145b9](https://github.com/navaneeshnagarajan/FlintTrade/commit/ae145b95feba74cbd7703d1b748a1e529908fce0))
* **brokers:** align live probe auth-method help ([4430d76](https://github.com/navaneeshnagarajan/FlintTrade/commit/4430d7626ca1161fd2999033ebaba35258056b0f))
* **brokers:** align MCP setup and Kotak token prompts ([6fcc0d1](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fcc0d1aff794de853c26c8896a61c61c124ddf0))
* **brokers:** close fast-follow gaps from the wave review ([3ff9d60](https://github.com/navaneeshnagarajan/FlintTrade/commit/3ff9d6094e6a2d81910e107fdcf4ac3e2d5c7b38))
* **brokers:** demote read-only native connect primaries ([fb88773](https://github.com/navaneeshnagarajan/FlintTrade/commit/fb88773857180cd7b370580767ced6396203744b))
* **brokers:** expose native connect blockers ([8c3c43c](https://github.com/navaneeshnagarajan/FlintTrade/commit/8c3c43cbb9cc44c2e9fca90e4ced80e7f59406a4))
* **brokers:** expose native ltp reads ([df9f234](https://github.com/navaneeshnagarajan/FlintTrade/commit/df9f234e5696710a61dd2d2a781110495f560284))
* **brokers:** extend live-order fail-closed to smart-route + drop legacy active id ([28fb00e](https://github.com/navaneeshnagarajan/FlintTrade/commit/28fb00e3aeb8b6fe23f7f750364f2a9fe30906d9))
* **brokers:** gate market-depth readiness honestly ([c6a2931](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6a2931708384ba8100f2c1271bb2fbf97e7a2c4))
* **brokers:** harden native connect surface after wave review ([44f8fab](https://github.com/navaneeshnagarajan/FlintTrade/commit/44f8fabd58d2ce17b657c942b7e90699c22c1feb))
* **brokers:** keep live probe handoff lists canonical ([b99799c](https://github.com/navaneeshnagarajan/FlintTrade/commit/b99799cbcb13b3b891320c3968d4e7b00bae0049))
* **brokers:** key gateway account removal by source, not the bare id ([7bce000](https://github.com/navaneeshnagarajan/FlintTrade/commit/7bce0007def72d26a6d92cf8cbe572ae546e9589))
* **brokers:** preflight native SDK readiness ([9cd6376](https://github.com/navaneeshnagarajan/FlintTrade/commit/9cd63763ecc402f6c28973e7c255fffdf17cf79c))
* **brokers:** refresh MCP setup and Kotak stream limits ([bdc3320](https://github.com/navaneeshnagarajan/FlintTrade/commit/bdc33208b43e99b9c90cb274aebb90eb600c4deb))
* **brokers:** remediate re-audit findings on the wave-review fixes ([e265382](https://github.com/navaneeshnagarajan/FlintTrade/commit/e2653823048cfe1a9facebdafe7cb60bc641e577))
* **brokers:** remediate wave-2 audit and one-core conformance findings ([a3bb5df](https://github.com/navaneeshnagarajan/FlintTrade/commit/a3bb5df2eda8c04dd9ff41b8d9be59e869764d0a))
* **brokers:** return blockers from legacy native rejects ([23a3a27](https://github.com/navaneeshnagarajan/FlintTrade/commit/23a3a275c007c2ea7f1948835a232b733a73de4e))
* **brokers:** route native connects away from legacy gateway ([ae5cd6b](https://github.com/navaneeshnagarajan/FlintTrade/commit/ae5cd6b286607b825e483b97b03a60245e182542))
* **brokers:** serialise native connect + correct a stale docstring ([4884c55](https://github.com/navaneeshnagarajan/FlintTrade/commit/4884c5506faba014e72872f37b35ad9eb08e7122))
* **brokers:** surface Groww session approval blocker ([0ae840c](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ae840cbd6409df2ff6b12b063468bcd0eacca69))
* **brokers:** surface static IP requirements ([8fc079e](https://github.com/navaneeshnagarajan/FlintTrade/commit/8fc079e11eaddfc8e60cd96669c721148c869faf))
* **brokers:** unify native history interval metadata ([cbeab08](https://github.com/navaneeshnagarajan/FlintTrade/commit/cbeab0896a03b8f4617cbd6b31d34fb11dbf8df5))
* clear the three flagged residuals + a latent PIN-error bug ([05f3f58](https://github.com/navaneeshnagarajan/FlintTrade/commit/05f3f58a5426f77e5c4019f87c5b9137413f90b2))
* **core,gateway,screener:** backend hygiene — locking, retention, dedupe, fail-closed classification ([e10a821](https://github.com/navaneeshnagarajan/FlintTrade/commit/e10a82167e38c3a696610f569884f82bfa1ea406))
* **core:** bind native mutations to generations ([17c4018](https://github.com/navaneeshnagarajan/FlintTrade/commit/17c4018bcd0ebea1d3f75c110650118091d33a21))
* **core:** close runtime ownership safely ([b870f0e](https://github.com/navaneeshnagarajan/FlintTrade/commit/b870f0e6bdca3613573e401fb23d433b56416930))
* **core:** close shutdown publication races ([def547d](https://github.com/navaneeshnagarajan/FlintTrade/commit/def547d4815b2a77a7c48da12940025166603c5b))
* **core:** defer unrecovered recorder failures ([a347803](https://github.com/navaneeshnagarajan/FlintTrade/commit/a3478039deb7e9f8ba31263b30bf354722a51257))
* **core:** drain admitted requests on shutdown ([18f27ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/18f27ef00b311c64a3401bcd6113ecd124a1832f))
* **core:** fail closed on stale market calendars ([90e3f10](https://github.com/navaneeshnagarajan/FlintTrade/commit/90e3f10f1dd7190377bc9e0bc07366f283b68c6b))
* **core:** honour backend port override ([8f20e5e](https://github.com/navaneeshnagarajan/FlintTrade/commit/8f20e5e32d0bcae1b1f58fc2126cc02b435fe6f7))
* **core:** honour OpenAlgo REST port config ([3e2d6a4](https://github.com/navaneeshnagarajan/FlintTrade/commit/3e2d6a41bce08d33c1bcb453a6275bae2f088bc9))
* **core:** honour workspace OpenAlgo settings in order fallback ([f622889](https://github.com/navaneeshnagarajan/FlintTrade/commit/f622889d67672df2c1c64bc5febe97ec966b0827))
* **core:** make native account mutations transactional ([710d698](https://github.com/navaneeshnagarajan/FlintTrade/commit/710d69817568e8c663a1f43a213129874ea6c71d))
* **core:** make native account swaps transactional ([c6a51a1](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6a51a150c1b77123fdce487fa6619f7ab2126a9))
* **core:** one owner event loop for the shared OpenAlgo client ([06213ff](https://github.com/navaneeshnagarajan/FlintTrade/commit/06213ff9c92101e504a39a27891e603c8bbc94c5))
* **core:** own autonomous agent market sessions ([37e313b](https://github.com/navaneeshnagarajan/FlintTrade/commit/37e313bec7b38ec0d4472db5f4ecefe2b63148ac))
* **core:** preserve shared OpenAlgo lifecycle ([134d305](https://github.com/navaneeshnagarajan/FlintTrade/commit/134d30555b3743a7c1c25def10f83e4b52e21fa0))
* **core:** quiesce live-order owners before retirement ([2fa486b](https://github.com/navaneeshnagarajan/FlintTrade/commit/2fa486b3bdfe3e9c4adb36c0d51b3e0d09ddec36))
* **core:** quiesce runtime before request drain ([fd5f923](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd5f923e6d0f7ca91ef6b5c75f62aae88350c215))
* **core:** require a session JWT on Ditto management writes ([86b5871](https://github.com/navaneeshnagarajan/FlintTrade/commit/86b5871bcf54324fdd213c70f39f21ab60ed45fe))
* **core:** retain late-session retraining work ([7facb68](https://github.com/navaneeshnagarajan/FlintTrade/commit/7facb689c4505bcb450b5ef110275046d78a638c))
* **core:** retire runtime generations safely ([10749b1](https://github.com/navaneeshnagarajan/FlintTrade/commit/10749b1cf4b98fc7e46d6d752b90c8e6c9fcf67a))
* **core:** reuse configured OpenAlgo client in routes ([0d2c92e](https://github.com/navaneeshnagarajan/FlintTrade/commit/0d2c92ec278e01ef2a35b5171e44ae38a4588ac6))
* **core:** serialise runtime ownership shutdown ([28799b9](https://github.com/navaneeshnagarajan/FlintTrade/commit/28799b9d34a60114ce34af49f41c273b9b029015))
* **core:** serialise workspace updates ([ebe0710](https://github.com/navaneeshnagarajan/FlintTrade/commit/ebe071061257ba02e06ecfc93800a6ad9e2cf7d0))
* **core:** use workspace paths for AI and historify state ([8975539](https://github.com/navaneeshnagarajan/FlintTrade/commit/897553907e3665a84ce37204d5ff1cb2c5615651))
* **data:** G27/G28 data-completeness — export end_date, orderflow interval honesty, drop dead PnLTracker ([8153291](https://github.com/navaneeshnagarajan/FlintTrade/commit/8153291b7396afbcc68dc84717eabca9d95d1532))
* **data:** harden live tick and order-flow state ([d002f3a](https://github.com/navaneeshnagarajan/FlintTrade/commit/d002f3a412b5fdeee1fecb874065e71e37b14eb3))
* **data:** harden live tick capture ([930311b](https://github.com/navaneeshnagarajan/FlintTrade/commit/930311bd36b3f4aa3ba0af59330c90a3227b236d))
* **data:** harden tick and spread processing ([d144b18](https://github.com/navaneeshnagarajan/FlintTrade/commit/d144b182f1889be99dbe94a3bb60f0009cc3dd81))
* **data:** isolate order flow by exchange ([436465e](https://github.com/navaneeshnagarajan/FlintTrade/commit/436465e1a11d9d4e2abd98cfc23bdeb2cb4d441f))
* **data:** make order flow concurrency safe ([c9ef2e7](https://github.com/navaneeshnagarajan/FlintTrade/commit/c9ef2e7f748426a45f3482ae6a9c9d6c7a8c53c2))
* **data:** make tick replay deterministic ([f5731eb](https://github.com/navaneeshnagarajan/FlintTrade/commit/f5731eb6497cd1bd1b5b04937b73cc507c11b414))
* **data:** migrate indexed tick schemas safely ([889f1b9](https://github.com/navaneeshnagarajan/FlintTrade/commit/889f1b9e4a28457d081d8096e3ef6a606240f67a))
* **data:** persist cursor-bound order-flow checkpoints ([ecef6df](https://github.com/navaneeshnagarajan/FlintTrade/commit/ecef6df372ed45ff9f32b9791752b81feb091c04))
* **data:** preserve live order-flow integrity ([1b2db12](https://github.com/navaneeshnagarajan/FlintTrade/commit/1b2db128fea66a819de8a626cececd20f651d9c8))
* **data:** preserve order-flow restart provenance ([37e31f1](https://github.com/navaneeshnagarajan/FlintTrade/commit/37e31f1a0b5bd2d9ba573f225f5c8b1256806caa))
* **data:** preserve truthful order flow state ([6bfa360](https://github.com/navaneeshnagarajan/FlintTrade/commit/6bfa360f006613256a8f4c89248201264fe0baac))
* **data:** recover counter namespaces safely ([20fb46a](https://github.com/navaneeshnagarajan/FlintTrade/commit/20fb46a96a013b76c036bc61093d2c656f8d745a))
* **data:** repair OpenAlgo tick recording ([fa52daf](https://github.com/navaneeshnagarajan/FlintTrade/commit/fa52dafcb09f8f294abdb168364709c73d50e5e8))
* **data:** restore bounded tick state at boot ([c6986a3](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6986a3beade9aa513c627d1d11f8f697729b49d))
* **data:** stop reusing one workspace dir across test runs ([82d7e17](https://github.com/navaneeshnagarajan/FlintTrade/commit/82d7e17f017c1fe5bff8495f861e3d70a7d8d611))
* **data:** validate live tick provenance ([4dc2ae9](https://github.com/navaneeshnagarajan/FlintTrade/commit/4dc2ae9bcfad619f4b721b89b7f5c1f7b89c26a6))
* **desktop,security,test:** pin+verify update assets, de-flake concurrent SQLite test ([e71849f](https://github.com/navaneeshnagarajan/FlintTrade/commit/e71849fddcc6bac11ecf7a5d57346fa13556b17c))
* **desktop,terminal:** updater robustness, LLM-persist debounce, fail-safe update UX ([a4fba13](https://github.com/navaneeshnagarajan/FlintTrade/commit/a4fba135a9709661d0c1b82fb7a0550d8305d060))
* **desktop:** bound sidecar supervision safely ([9123a0a](https://github.com/navaneeshnagarajan/FlintTrade/commit/9123a0abdfc7fd325a3ab33d23a2829c62c52e79))
* **desktop:** close sidecar identity races ([aac965e](https://github.com/navaneeshnagarajan/FlintTrade/commit/aac965ef1c1d7b4a0a6ece3323742fb5ccd8e4ff))
* **desktop:** contain backend process tree ([b868fb0](https://github.com/navaneeshnagarajan/FlintTrade/commit/b868fb09b595983f09283d3840e275687fde175e))
* **desktop:** fail closed on stale sidecars ([162774b](https://github.com/navaneeshnagarajan/FlintTrade/commit/162774bdaa4c004045f4f9d16e45b7610c89b3fa))
* **desktop:** flush tick capture on shutdown ([4b879a0](https://github.com/navaneeshnagarajan/FlintTrade/commit/4b879a03706edb7db37206ece14d1a527db1a221))
* **desktop:** harden sidecar ownership and recovery ([dae24d1](https://github.com/navaneeshnagarajan/FlintTrade/commit/dae24d1955e532e7a8f483054785568f135911f5))
* **desktop:** keep supervising detached sidecar ([b4b06c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b4b06c8a2b9dc72496a58ede45adaa34cbc4b599))
* **desktop:** make POSIX containment work on pidfd-less builds and dying parents ([d1d0a25](https://github.com/navaneeshnagarajan/FlintTrade/commit/d1d0a2528c3074d3d305d95b4ab7fcc795472d02))
* **desktop:** propagate backend shutdown failures ([9aaa157](https://github.com/navaneeshnagarajan/FlintTrade/commit/9aaa1575e445fec7cf44652b29187e6d633c24dd))
* **desktop:** retain frozen backend ownership ([b245a95](https://github.com/navaneeshnagarajan/FlintTrade/commit/b245a9550d83e58f47fcd883cb9db5aead7265d1))
* **desktop:** retain tick storage across flush retries ([d952514](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9525145ceaa55d44ace2ff5fce89694df0a3917))
* **desktop:** skip unparseable /proc rows in the containment snapshot ([22207e0](https://github.com/navaneeshnagarajan/FlintTrade/commit/22207e007f267e291feab845da3ef359a447691d))
* **ditto:** guarantee mirror deactivation when emergency flatten is declined ([157241d](https://github.com/navaneeshnagarajan/FlintTrade/commit/157241d398bb5de94108c709581d4b5746f48d71))
* **ditto:** retire the ungated mirror order path and close the URL tripwire gap ([0a5301d](https://github.com/navaneeshnagarajan/FlintTrade/commit/0a5301d43db1bb376821106ad93b1b501665c920))
* **ditto:** thread operator trading mode into the mirror, fail closed on non-live ([f239893](https://github.com/navaneeshnagarajan/FlintTrade/commit/f23989356ec17f6aa63ac01a2c4e43d807937ad9))
* **engine,core:** never let a dead intent journal veto the emergency flatten ([ad108fd](https://github.com/navaneeshnagarajan/FlintTrade/commit/ad108fdb568f8ec86abb40d1da3c15feb32b0486))
* **engine,desktop:** own strategy process lifecycles ([eb749fc](https://github.com/navaneeshnagarajan/FlintTrade/commit/eb749fc1f2a373cf775716029592949922c11c1d))
* **engine,terminal:** reject fabricated 0.0 sandbox fills (G14) ([ef67d64](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef67d643383ebe87cef25d03c19e389b21003fcc))
* **engine:** fail-close interrupted Action Centre dispatches on restart ([82741b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/82741b809000a251f5c975b5fcf95db9756b0157))
* **engine:** make basket/split executors synchronous (WSGI parity, adversarial finding) ([bf514d2](https://github.com/navaneeshnagarajan/FlintTrade/commit/bf514d25e521bcf05e0a91fdb122f7912f60f5d7))
* **engine:** preserve scheduled market context ([7cd648d](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cd648d933b7f9a48c4dd1424c9b3e89527ca813))
* **gateway:** align Kotak Neo fin-key headers with docs ([1471f68](https://github.com/navaneeshnagarajan/FlintTrade/commit/1471f68fd680e8f93289454bf320f381ddb8930f))
* **gateway:** derive native capability registry ([54b4758](https://github.com/navaneeshnagarajan/FlintTrade/commit/54b4758ba1ed70fa72c7be55aab459073fbc4341))
* **gateway:** expose Kotak Neo exchange coverage ([b14f991](https://github.com/navaneeshnagarajan/FlintTrade/commit/b14f991497f4316d4bfa11bbfabd6d56531a4fe4))
* **gateway:** expose native broker runtime capabilities ([ab937ab](https://github.com/navaneeshnagarajan/FlintTrade/commit/ab937ab64ed0c04cfe4e87fa8a37eccbbecb30d3))
* **gateway:** gate stale coming-soon native accounts ([5709581](https://github.com/navaneeshnagarajan/FlintTrade/commit/5709581d6343d1620c9cab30b4ae91a526514861))
* **gateway:** keep coming-soon natives dormant ([e9b2096](https://github.com/navaneeshnagarajan/FlintTrade/commit/e9b2096ac0a36c2a73105c03fde7634bbee6f349))
* **gateway:** keep native session across service-window and transient probe errors ([9b4c6a7](https://github.com/navaneeshnagarajan/FlintTrade/commit/9b4c6a72f056b6de1803ae84585218dc229fbba4))
* **gateway:** preserve Upstox special sessions ([76fcfb2](https://github.com/navaneeshnagarajan/FlintTrade/commit/76fcfb24a47a30aa9db7fc61ac9462d8191c41d3))
* **gateway:** refresh Upstox MCP use cases ([514c7b2](https://github.com/navaneeshnagarajan/FlintTrade/commit/514c7b2fc28db7e828235f7f8e8ce77218cf3378))
* **gateway:** repo-manage broker SDKs and repair Groww auth ([9018835](https://github.com/navaneeshnagarajan/FlintTrade/commit/9018835634467c1e25197dc15253d596e2b06777))
* **gateway:** resolve INDstocks symbols from instruments master ([442858b](https://github.com/navaneeshnagarajan/FlintTrade/commit/442858b7ba591a9009ee2f1f07c5d60c52d754c1))
* **gateway:** revoke stale router generations ([6b3e54a](https://github.com/navaneeshnagarajan/FlintTrade/commit/6b3e54a8b2552dabd6fd4fc907380fb78d1ad567))
* **gateway:** stage native credential changes ([d010d63](https://github.com/navaneeshnagarajan/FlintTrade/commit/d010d63669c4f08fe9f4f54cf743c5b594c519cb))
* **groww:** map MCX commodity segment ([3c9ea84](https://github.com/navaneeshnagarajan/FlintTrade/commit/3c9ea84f1412eab5b5414719b04dd6456ce5b353))
* **groww:** match official SDK request headers ([eff4e09](https://github.com/navaneeshnagarajan/FlintTrade/commit/eff4e093af65f29f91a478e8913c612b2708c5e5))
* **groww:** preserve segment on native cancels ([af31088](https://github.com/navaneeshnagarajan/FlintTrade/commit/af310883ef01813bd4566daf6675c82dc68c4ca8))
* **honesty:** sample data declares itself + WS unsubscribe refcounting ([6fdc6a8](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fdc6a880a1c22ebaa94b79ee97fcde595ad1fc7))
* **install:** harden headless consent() + trusted-URL windows dry-run fixture ([41831e2](https://github.com/navaneeshnagarajan/FlintTrade/commit/41831e2a4c4599304ec46e6517a4ebab545a92ff))
* **journal:** thread-safety + P&L/date/import correctness (G31 verify) ([1108437](https://github.com/navaneeshnagarajan/FlintTrade/commit/11084378ccdd522d47a9a15da4301c408f76d602))
* **kotakneo:** accept docs access token alias ([c23118a](https://github.com/navaneeshnagarajan/FlintTrade/commit/c23118a031a00f820381d7e4bfb098abf0de8824))
* **kotakneo:** align order mapping with current docs ([1c0fd8e](https://github.com/navaneeshnagarajan/FlintTrade/commit/1c0fd8e628931e356d75e88b0c0cb8eae4191503))
* **kotakneo:** align v2 headers and order-feed startup ([dd7cb9d](https://github.com/navaneeshnagarajan/FlintTrade/commit/dd7cb9ddab152aa26cfa3003ead88baa15b8ae76))
* **kotakneo:** canonicalise quote filters and index names ([ed65944](https://github.com/navaneeshnagarajan/FlintTrade/commit/ed6594481c0592e15bd3d4e0c586da6e1469cf3a))
* **kotakneo:** parse current quote depth payloads ([d885fee](https://github.com/navaneeshnagarajan/FlintTrade/commit/d885fee063717705bfebfa46e239665afc4b81c6))
* **kotakneo:** sign documented AMO cancel symbol ([c160190](https://github.com/navaneeshnagarajan/FlintTrade/commit/c160190d79c266e29b4577be2ad12f9f88089154))
* **logging:** redact sensitive runtime identifiers ([f8e6b8c](https://github.com/navaneeshnagarajan/FlintTrade/commit/f8e6b8c62b94ed718fa586051d99d1cda7eb43a8))
* **native:** drop stale sessions on replay login failure ([be4575b](https://github.com/navaneeshnagarajan/FlintTrade/commit/be4575b195a6593fad5e211c721d4f96ae255f5c))
* **probe:** mark Upstox analytics tokens read-only ([20f535c](https://github.com/navaneeshnagarajan/FlintTrade/commit/20f535cc3949f06d30797fb79bb884b0c7bae5ef))
* **probe:** resolve Dhan symbols for live reads ([58ba9e2](https://github.com/navaneeshnagarajan/FlintTrade/commit/58ba9e29f8b770bb379fdb9241db5826c5733a35))
* **release:** stamp the stability disclaimer into generated release notes ([730c580](https://github.com/navaneeshnagarajan/FlintTrade/commit/730c5801e0f1e901a93bc7bcb72b90c53e15816f))
* **runtime:** gate emergency flatten and retain order flow ([1f13b3b](https://github.com/navaneeshnagarajan/FlintTrade/commit/1f13b3b7d0026ceff988256414a957e138be15b8))
* **runtime:** preserve mutable state ownership ([ff20423](https://github.com/navaneeshnagarajan/FlintTrade/commit/ff2042355904efd578460170b83c5786dd628eb2))
* **runtime:** share exchange calendar state ([2b5caee](https://github.com/navaneeshnagarajan/FlintTrade/commit/2b5caeee98c9ad4e234d2376355f8bce5fb1b399))
* **scheduling:** honour effective market sessions ([257a967](https://github.com/navaneeshnagarajan/FlintTrade/commit/257a967390a362591b58d443247e3c4074e440bf))
* **sdk:** omit empty broker digest metadata ([a02b32f](https://github.com/navaneeshnagarajan/FlintTrade/commit/a02b32f17e048b55740bfa0c6b3da8de147f5c05))
* **security:** bound native connect response ([bd3452b](https://github.com/navaneeshnagarajan/FlintTrade/commit/bd3452bc668b39af1d6e845bf9296071bce5815f))
* **security:** clear all 14 open code-scanning alerts ([0b2bc18](https://github.com/navaneeshnagarajan/FlintTrade/commit/0b2bc18d14cc27fad3cf9c3a187792556418f714))
* **security:** close remaining CodeQL alert paths ([0899db0](https://github.com/navaneeshnagarajan/FlintTrade/commit/0899db0f3473f75ee90566c81c4b035624302e8d))
* **security:** constrain chart-prefs user_id to a safe identifier charset ([715da56](https://github.com/navaneeshnagarajan/FlintTrade/commit/715da562779df8333311b7e15e4b79fb8b579044))
* **security:** remediate CodeQL alerts across routes, secrets, and paths ([12891a1](https://github.com/navaneeshnagarajan/FlintTrade/commit/12891a129ae8ebbc5f31b5ed82318345dfc329ba))
* **security:** stop bracket-cancel 503 reflecting exception text ([e814198](https://github.com/navaneeshnagarajan/FlintTrade/commit/e814198530a5b04933d75a2e1f0bb4cdcd7edbb0))
* **security:** stop native connect response taint ([c098f43](https://github.com/navaneeshnagarajan/FlintTrade/commit/c098f433d90c54928f2ee50db55880e2a4f66dfd))
* **setup:** block read-only native primary promotion ([e8f7007](https://github.com/navaneeshnagarajan/FlintTrade/commit/e8f700795311dfc53277bdc8f86c7eae0c1f5367))
* **setup:** require write-capable broker for native completion ([c425fc5](https://github.com/navaneeshnagarajan/FlintTrade/commit/c425fc5122014300cfb3185c057a0074fdbb9653))
* **setup:** sync repo broker SDK pins ([a00c221](https://github.com/navaneeshnagarajan/FlintTrade/commit/a00c22146ee48c5f6bd7dfdd3f8d23f664bd074a))
* **setup:** use unified broker account gate ([642bc97](https://github.com/navaneeshnagarajan/FlintTrade/commit/642bc97189b4349aaa4315bfddec4a2b4eac69cc))
* **site:** publish current desktop download copy ([edec745](https://github.com/navaneeshnagarajan/FlintTrade/commit/edec745e0670848f26fbb7f62e3c35247aaffcee))
* **site:** update widget-count assertions to 102 after the G36 doc fix ([13927d7](https://github.com/navaneeshnagarajan/FlintTrade/commit/13927d7e41cd879c5adee2efb836ea0ab29f529f))
* **supply-chain:** bind audits to current locks ([00f6ea1](https://github.com/navaneeshnagarajan/FlintTrade/commit/00f6ea1489ca7c63388bdc0e9df3c32492a5eef3))
* **supply-chain:** bump crossbeam-epoch 0.9.18 -&gt; 0.9.20 (RUSTSEC-2026-0204) ([33f48d0](https://github.com/navaneeshnagarajan/FlintTrade/commit/33f48d0ef8595d35427445fb8fb9101882b89aeb))
* **supply-chain:** close 4 deferred audit gaps in the SDK provenance gates ([996fd0c](https://github.com/navaneeshnagarajan/FlintTrade/commit/996fd0cdae7c6528a64bfc260dcd3cade76b2eb6))
* **supply-chain:** regenerate stale NOTICE bundle ([18d063d](https://github.com/navaneeshnagarajan/FlintTrade/commit/18d063d272932d7640bb28c9d9e2a397796ae267))
* **terminal,core:** make OpenAlgo config backend-authoritative ([172fecc](https://github.com/navaneeshnagarajan/FlintTrade/commit/172fecc7a1116fc7f20b4928a17b83b3110eff12))
* **terminal,core:** rehydrate OpenAlgo apiKey + fail-closed live-order routing after reload ([4d1d676](https://github.com/navaneeshnagarajan/FlintTrade/commit/4d1d6769f2819db7506f0228d335298cb32b477e))
* **terminal,data:** disclose sample data affordances ([ceb2efb](https://github.com/navaneeshnagarajan/FlintTrade/commit/ceb2efbee573f65b2b63bff6101ae1c051e13c04))
* **terminal,desktop:** post-audit — no fabricated P&L, persistent unprotected-bracket, webview origin confinement ([dd96710](https://github.com/navaneeshnagarajan/FlintTrade/commit/dd96710f265cb2eab6ceb32ff534c7e6f7210b9e))
* **terminal:** add login 2FA recovery and accept backup codes ([e3ef175](https://github.com/navaneeshnagarajan/FlintTrade/commit/e3ef175c61dbfcb9df7d52a1c7d05932facba58e))
* **terminal:** align live market signal state ([fd01278](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd012784e35c33e539877181f393cc99ef1c847a))
* **terminal:** align order-flow exchange sessions ([3cce8b2](https://github.com/navaneeshnagarajan/FlintTrade/commit/3cce8b2fab403fd29d848afe6a23993d433c9a22))
* **terminal:** book partial-close realised P&L from the tradebook ([11cc78c](https://github.com/navaneeshnagarajan/FlintTrade/commit/11cc78c20d93e6b3fd296e035b7a7e83c5ffcd46))
* **terminal:** connect native brokers from the setup wizard ([145a3a0](https://github.com/navaneeshnagarajan/FlintTrade/commit/145a3a007009d59cbe67289926774998aa2058cd))
* **terminal:** derive native broker copy from catalogue ([ee190d7](https://github.com/navaneeshnagarajan/FlintTrade/commit/ee190d7aadf79d96e48b1e64ad22eceac153182a))
* **terminal:** disclose order-flow provenance ([6d6ae67](https://github.com/navaneeshnagarajan/FlintTrade/commit/6d6ae67704a722429b72b7f7d2129b40d8d5f5b5))
* **terminal:** fail closed on broker-management writes during OpenAlgo config hydration ([e0cbfda](https://github.com/navaneeshnagarajan/FlintTrade/commit/e0cbfdad812a9c4583fb42c254988659e5d73e96))
* **terminal:** gate broker account data behind connection ([050a9ac](https://github.com/navaneeshnagarajan/FlintTrade/commit/050a9ac22e720f62b18f1d92ff2429f7d0bcb69b))
* **terminal:** keep order-flow canvases truthful ([2770f38](https://github.com/navaneeshnagarajan/FlintTrade/commit/2770f3872260aba0c20289434c5f2e687ecfd764))
* **terminal:** keep order-flow instruments aligned ([6fefdf5](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fefdf5842b47d179edd6896220c6fee0e37d233))
* **terminal:** keep the kill switch available on a failed safety refresh ([d7f4e4b](https://github.com/navaneeshnagarajan/FlintTrade/commit/d7f4e4bc9a8aa25aeb4ea28581593ce456b1ae8e))
* **terminal:** make broker MCP setup copy honest ([2edd235](https://github.com/navaneeshnagarajan/FlintTrade/commit/2edd235addf9e1bdf4707b3b6a2d441faad510e3))
* **terminal:** make the daily trading loop honest and operable ([dc63373](https://github.com/navaneeshnagarajan/FlintTrade/commit/dc63373249b93e9d23b742098faa4c2e04891c7d))
* **terminal:** merge setup broker label flow ([81818c7](https://github.com/navaneeshnagarajan/FlintTrade/commit/81818c7f6ed849711b72ebe1c2e9a8a45f8fe8fc))
* **terminal:** preserve authenticated live feeds ([7f42fce](https://github.com/navaneeshnagarajan/FlintTrade/commit/7f42fce64ccb74d7815b90290682f4727def0778))
* **terminal:** preserve compact market-data controls ([afe1afb](https://github.com/navaneeshnagarajan/FlintTrade/commit/afe1afb8c16e09d07826dfd0ac1fdfff1dac7ef1))
* **terminal:** preserve live data provenance ([d9beefd](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9beefda17c4c2a56e274be6d22e50d44d0156c7))
* **terminal:** reconcile emergency runtime state ([7c4cf6a](https://github.com/navaneeshnagarajan/FlintTrade/commit/7c4cf6a6863780f3181d41f674c2ac978d3ce3fa))
* **terminal:** resolve broker account selectors safely ([74eb2a0](https://github.com/navaneeshnagarajan/FlintTrade/commit/74eb2a0938b4e6d7eef0999ade74e03239e534a0))
* **terminal:** retire legacy broker auth hook ([2781942](https://github.com/navaneeshnagarajan/FlintTrade/commit/27819426981d490bc8b3d48ebbb566fed5cb4189))
* **terminal:** route app auth through shared backend client ([7d9fa93](https://github.com/navaneeshnagarajan/FlintTrade/commit/7d9fa9323011fb812074532db52966273675241a))
* **terminal:** route broker reauth to unified settings ([c1bd83d](https://github.com/navaneeshnagarajan/FlintTrade/commit/c1bd83d94db3e6cfcc53402f6d78125b20a79de7))
* **terminal:** route native ltp quote details ([904ceaa](https://github.com/navaneeshnagarajan/FlintTrade/commit/904ceaa6295dd5460d9804347fa2603a675684b9))
* **terminal:** setup and settings traps — honest defaults, no premature commits ([48f2498](https://github.com/navaneeshnagarajan/FlintTrade/commit/48f249844c794e7cb8044121ba0a5d5c67d5f26d))
* **terminal:** show broker recommendation gaps ([bd0c201](https://github.com/navaneeshnagarajan/FlintTrade/commit/bd0c201573c7abd80dba79f705644375500c870c))
* **terminal:** show full broker MCP setup metadata ([b72d31d](https://github.com/navaneeshnagarajan/FlintTrade/commit/b72d31dfc3e049e034ce2f8cd6786cc2da7abed5))
* **terminal:** validate market-data provenance ([0625e90](https://github.com/navaneeshnagarajan/FlintTrade/commit/0625e903dfb9d112b01174e5e758145c61f066e6))
* **terminal:** wire webhooks panel to backend registry ([a2800cd](https://github.com/navaneeshnagarajan/FlintTrade/commit/a2800cdbc493f19a4bc2ac2f56dfd721dad9541d))
* **ticks:** preserve PyO3 extraction contracts ([59fbc67](https://github.com/navaneeshnagarajan/FlintTrade/commit/59fbc676502092b88ed71e805d15a9b61b99575c))
* **ticks:** reject unsafe spread arithmetic ([569dad7](https://github.com/navaneeshnagarajan/FlintTrade/commit/569dad74715f074e0fdbaf6238de1462fa3f8044))
* **ticks:** validate spread batches before parallel work ([c90d246](https://github.com/navaneeshnagarajan/FlintTrade/commit/c90d2461d4c5e8c358092d0e87cb777e149576a7))
* **ticks:** validate spread batches before rayon ([7aeb937](https://github.com/navaneeshnagarajan/FlintTrade/commit/7aeb937cdb3a17cb604c16edcf6d3d30f693b555))
* **ticks:** validate spread batches deterministically ([f54ae95](https://github.com/navaneeshnagarajan/FlintTrade/commit/f54ae95ed19647372577574535acabe8568fb2fb))
* **upstox:** align GTT trigger rules ([cf3ff09](https://github.com/navaneeshnagarajan/FlintTrade/commit/cf3ff096e671a6806e54d73f26a1740730ed21b9))
* **upstox:** route native OHLC reads through facade ([5c27fbb](https://github.com/navaneeshnagarajan/FlintTrade/commit/5c27fbbef6f5b614e4a44ec36c484dd484b16629))
* **webhooks:** fail order signals honestly instead of faking a queued success ([6dc1d9e](https://github.com/navaneeshnagarajan/FlintTrade/commit/6dc1d9eda6d5479f3bcb29fab42405f58afa5988))
* **webhooks:** gate public signed webhook intake by registry ([8dc0f0e](https://github.com/navaneeshnagarajan/FlintTrade/commit/8dc0f0e911d63dfbb15e3286d4a8a492cc902309))
* **webhooks:** route signed order intents through gated router ([afb1868](https://github.com/navaneeshnagarajan/FlintTrade/commit/afb1868ee64b01478355224742a3eedfb3a4e70a))
* **webhooks:** share fail-closed HMAC verification ([2433594](https://github.com/navaneeshnagarajan/FlintTrade/commit/24335940495554ef80d66335e5142e3cb63a653d))


### Changed

* **ai:** retire duplicate memory manager logic ([c4b9686](https://github.com/navaneeshnagarajan/FlintTrade/commit/c4b9686d51268d66fae3a57cf32f286a53f393a5))
* **ai:** retire duplicate ML advisor chain ([73880fa](https://github.com/navaneeshnagarajan/FlintTrade/commit/73880fa0daac503845650c08489cc2eb3753653c))
* **ai:** retire duplicate ML advisor chain ([068084c](https://github.com/navaneeshnagarajan/FlintTrade/commit/068084ca98378837a89aa86bc6a38883e829b986))
* **ai:** retire duplicate sentiment modules ([5876e1f](https://github.com/navaneeshnagarajan/FlintTrade/commit/5876e1fcd265f031719c6573f8d1dcf2139725ef))
* **ai:** retire duplicate team orchestrators ([472a852](https://github.com/navaneeshnagarajan/FlintTrade/commit/472a8521a05fd3076da764492b5311e99fc97c23))
* **ai:** retire duplicate trade reflector ([cad1f58](https://github.com/navaneeshnagarajan/FlintTrade/commit/cad1f58ede90f62839030abe0ae402585b3b967e))
* **ai:** retire empty signal routes ([4d78b15](https://github.com/navaneeshnagarajan/FlintTrade/commit/4d78b15e96b3d60e44ba0d21b938cfcf9fef9bd4))
* **ai:** retire the duplicate RAG implementation ([e385ff6](https://github.com/navaneeshnagarajan/FlintTrade/commit/e385ff6ba9c6de88ca6a230beaf6d74fee3caaaa))
* **core:** drop the unused ollama loopback-port helper ([770998c](https://github.com/navaneeshnagarajan/FlintTrade/commit/770998ccedad673d316368b37b19ed364c9b0e4e))
* **data:** remove the redundant audit-export blueprint after verifying the merge ([d100312](https://github.com/navaneeshnagarajan/FlintTrade/commit/d100312673e891a66e207bb3839caa54b1d08938))
* **ditto:** store account api_keys in the canonical credential vault ([31eae8e](https://github.com/navaneeshnagarajan/FlintTrade/commit/31eae8e698bf7954c9b879078d659210bc5e37a8))
* **engine:** drop the superseded legacy emergency dispatcher ([8cd2e2b](https://github.com/navaneeshnagarajan/FlintTrade/commit/8cd2e2b284a912f5e001f5ce178b1a4ee65c238d))
* **gateway:** add BrokerRouter.default_selector accessor ([0ab2c6c](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ab2c6c3723beac9cd24cabe49bd308af3e8f177))
* **gateway:** derive native capabilities from adapter registry ([1520ee2](https://github.com/navaneeshnagarajan/FlintTrade/commit/1520ee2eff1564cf4795fe3a393bad43441e4cc6))
* **gateway:** derive native capability rows ([79365b9](https://github.com/navaneeshnagarajan/FlintTrade/commit/79365b9e0546e64af3364e5462706d7cbac71a6c))
* **gateway:** derive native SDK pins from broker catalogue ([5e7c70d](https://github.com/navaneeshnagarajan/FlintTrade/commit/5e7c70d1ffe936ac45d08c59640e1cbcf64062d2))
* **gateway:** retire legacy broker interface stack ([e05235e](https://github.com/navaneeshnagarajan/FlintTrade/commit/e05235e195cbdbcce80398e195e18535bb790052))
* **gateway:** unify the broker catalogue with connectable + native flags ([96fdb47](https://github.com/navaneeshnagarajan/FlintTrade/commit/96fdb47e2cc33436059a64f9ddb53d964ce15d75))
* **orders:** collapse order routing to the single gated surface ([b1c66b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b1c66b83d29c564e8a9f3f0c149fdbc38af7c6a7))
* **setup:** merge legacy broker picker into unified connect ([3d50901](https://github.com/navaneeshnagarajan/FlintTrade/commit/3d5090126a786687998944f6d2834cac53d9d19c))
* **terminal:** centralise native read account selection ([3a171cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/3a171cfc6ef142f8d3905946e4ccc7215a34d5ac))
* **terminal:** drop unused legacy gateway connect calls ([760c050](https://github.com/navaneeshnagarajan/FlintTrade/commit/760c050e9c2400b5da5087f29d301cf1c074feb1))
* **terminal:** retire dead broker auth hook ([81af974](https://github.com/navaneeshnagarajan/FlintTrade/commit/81af974b8678541a9fca5d6ad0243ce8b34be08e))
* **terminal:** retire legacy broker list hook ([c8d3140](https://github.com/navaneeshnagarajan/FlintTrade/commit/c8d31402fc67f24bd5fede3bd7d728af54707f54))
* **terminal:** reuse unified broker account connectivity ([8293102](https://github.com/navaneeshnagarajan/FlintTrade/commit/829310212d09a937491edeceb7324cbd8b1e561b))
* **terminal:** share gateway v1 client helpers ([4866a6a](https://github.com/navaneeshnagarajan/FlintTrade/commit/4866a6ad776d7e7e2ef36652973977bf0bd3b465))
* **terminal:** unify broker account client actions ([b2650e9](https://github.com/navaneeshnagarajan/FlintTrade/commit/b2650e99b44ecfd0d4006203ec717dd870f71ef7))
* **terminal:** unify broker account query surface ([504d3b1](https://github.com/navaneeshnagarajan/FlintTrade/commit/504d3b1facd208e99710400d06fa53b4db9e7ac5))
* **webhooks:** retire standalone webhook server ([128be23](https://github.com/navaneeshnagarajan/FlintTrade/commit/128be238f7dc154ed9ba1d8700a4ca4e8cb5b7ca))

## [Unreleased]

## [0.6.0-beta.1 → 0.6.0-beta.3] — consolidated feature notes

Hand-written notes for everything shipped across the beta.1→beta.3 line;
release-please now generates the per-release sections above from
Conventional Commits, so this block is historical narrative, not pending work.

### Added

- **Payload updates without an installer cycle** — every release now ships
  the frozen backend (terminal embedded) as a hash-verified
  `flinttrade-payload-<triple>` asset, and the desktop shell manages it the
  way it manages the Ollama runtime: staged download, streaming SHA-256
  verification against the release manifest, durable swap under
  `runtime/backend/<version>/` with the previous version retained for
  rollback, and automatic demotion back to the bundled backend if a payload
  fails to start. The thin shell rarely needs rebuilding; daily changes reach
  users as one-click backend updates.
- **CI-owned release engineering** — release-please maintains the release PR
  (version bumps from Conventional Commits, changelog generation), a
  propagation script keeps the ~25-file version contract consistent, and
  merging the PR builds all five installer targets in CI and publishes them
  non-draft with `SHA256SUMS.txt` and the desktop manifest. Apple
  signing/notarisation steps are wired but dormant until secrets exist;
  updater artifacts are minisign-signed with the repository's Tauri updater
  key.
- **One-click native updates** — the desktop shell now carries
  tauri-plugin-updater: Settings → Updates offers a single "Update and
  restart" action fed by the signed `latest.json` on the rolling
  `updater-beta`/`updater-stable` GitHub release, falling back to the bundled
  installer-script flow where the native updater is unavailable. Install
  scripts and the in-app updater read release metadata straight from
  `github.com/…/releases/download/` URLs — no first-party web host in the
  update path.
- **Web UI as a first-class surface** — the backend already serves the built
  terminal at `/`; `FLINTTRADE_BACKEND_HOST` now selects the bind interface for
  the standalone serve path (for example a Tailscale tailnet IP) so a plain
  browser on another machine is a full client. Non-loopback binds fail closed
  until the operator account exists or `FLINTTRADE_API_KEY` is set — loopback's
  unauthenticated trust never crosses the network — and the desktop sidecar
  path stays loopback-locked. An authenticated GET may rehydrate the OpenAlgo
  connection remotely; configuration writes remain loopback-only.
- **Managed local AI with Ollama** — FlintTrade can install a pinned official
  Ollama server archive on explicit operator confirmation, verify its SHA-256,
  run it as a loopback-only owned child on an unpredictable high port, manage
  model pulls, require explicit digest acceptance into a locked model alias,
  verify the loaded digest before releasing inference, and stop only the process
  it started. LM Studio is no longer a named dependency; every persisted
  LM Studio configuration migrates one-way to managed Ollama, while explicitly
  configured generic OpenAI-compatible hosts retain the `custom` provider.
  Runtime and model downloads remain opt-in and no model is bundled. Runtime
  update/rollback/uninstall, model reclamation and durable admission receipts
  keep timed-out control requests idempotently reconcilable. An explicitly
  confirmed acknowledgement can release a proved indeterminate receipt only by
  its exact operation and original admission IDs; it never retries the action or
  infers success. Cross-process lease paths and destructive-operation cancellation
  are fail-closed, and the terminal validates action-specific responses before
  releasing an admission lock.
- **Live Ditto runtime** — the Account Manager now owns real mirror status,
  start/stop, risk snapshots, and an all-account emergency flatten. Mirrored
  writes and kill-all actions use dedicated immutable `BrokerRouter`
  generations and mint a fresh `SafetyContext`; source state is primed before
  callbacks and runtime shutdown drains Ditto before shared routing
  dependencies are retired.
- **Email-OTP password recovery in the login screen** — the existing
  enumeration-resistant password-reset routes are now reachable from the
  signed-out UI, with six-digit-code filtering, password confirmation, bounded
  errors, and session invalidation retained on the backend.
- **Operator support diagnostics** — `GET /v1/support/diagnostics`
  (scope-guarded, `admin.errors.read`) returns a privacy-collapsed snapshot for
  bug reports: app version, platform, and aggregated recent client errors with
  routes, methods, and error classes sanitised before they leave the backend.
- **AI backends — six supported, OpenClaw removed** — the OpenClaw external-
  gateway bridge is gone (bridge, `/ai/openclaw/*` routes, widget, exports).
  In its place a `flinttrade_ai.agent_backends` registry catalogues the six
  supported backends and an **AI Backends** widget lists them with honest
  installed/ready/needs-config status. Three are chat/completion providers
  wired into the existing `LLMClient`: **Cerebras** (OpenAI-compatible),
  **Claude Code (API key)**, and **Claude Code (OAuth/subscription credits)** —
  the anthropic path now selects `Authorization: Bearer` + the Claude Code
  beta/identity headers vs `x-api-key` by token shape (operator-supplied token;
  no OAuth flow is run and no keychain is read). Three are agent runtimes
  replacing the "deploy an agent" concept, each streaming live turn output over
  the shared `AgentSession` contract: **Codex** over its `app-server`
  JSON-RPC-over-stdio protocol, **Hermes** over the Agent Client Protocol (ACP)
  JSON-RPC stdio session (`initialize`/`session/new`/`session/prompt` →
  `session/update` chunks, with fail-closed permission handling), and
  **Antigravity CLI** by spawning `agy -p` per turn and streaming its stdout (it
  manages its own auth). `POST /api/v1/ai/agents/run` streams `AgentEvent`s as
  SSE; a client disconnect genuinely stops the backend turn and terminates the
  subprocess.

- **Binary-first desktop install and update** — `/download`, `/install.sh`,
  `/install.ps1`, and Settings → Updates now resolve the canonical
  `/api/desktop-release` manifest and install the matching published desktop
  asset (`.dmg`, NSIS `.exe`, `.AppImage`, `.deb`, or `.rpm`) by default. The
  older local Rust/Node/Python/Tauri build path remains available only through
  the explicit `--build-from-source` / `-BuildFromSource` advanced fallback.
- **Desktop release manifest and checksums** — the Desktop Release workflow now
  aggregates matrix artifacts, publishes `flinttrade-desktop-manifest.json`,
  publishes `SHA256SUMS.txt`, and keeps unsigned beta installers honestly
  labelled while leaving signing/notarisation hooks env-gated for future certs.
- **Authenticated gated-audit export (CSV/PDF) + summary** — the
  gated-execution audit (order placements + per-layer safety verdicts) can now
  be exported over a date range as CSV or PDF and summarised, via
  `GET /api/v1/audit/events/export?format=csv|pdf&from=&to=` and
  `GET /api/v1/audit/events/summary?from=&to=`, both scope-guarded by
  `admin.audit.read`. This is the registered, reachable form of a capability
  that previously existed only in a built-but-unregistered blueprint whose
  routes were **unauthenticated** — the PDF/summary capability (via
  `AuditExporter`) is now behind the same auth as every other audit endpoint.
  The `AuditExporter` engine is kept (now consumed); the old standalone
  blueprint was removed only after verifying every capability lives on the
  authed routes and it has no consumers. PDF needs the optional `[export]` extra
  (reportlab) and degrades to a clean 500 without it. Hardened per an
  adversarial review: a corrupt/tampered audit day fails with a controlled,
  logged error (not an uncaught 500) rather than silently emitting an
  incomplete report; the date range is capped; and the auth boundary on every
  audit route is now pinned by a marker test so dropping `@require_scope` fails
  CI.
- **Tick-engine full surface importable from Python** — the `tick_engine`
  package re-exported only the four core simulator types while the compiled
  crate registers 28 (Monte Carlo, session tracker, options + spread
  backtesters, pairs). All 28 are now re-exported, with the crate's dormant
  status (built and tested, no production consumer yet) documented in the
  package docstring and pinned by a surface-completeness test.
- **Basket and split orders are now live, fully gated** — the
  `/api/v1/orders/{basket,split,options-strategy}` routes returned 503 because
  their executors were deliberately never wired: the executors placed each
  leg/chunk through `OrderRouter.route_order` (SafetySystem only — no
  `gate_order`/HMAC/`BrokerRouter`), so wiring them would have opened an ungated
  live-order path. Both executors now dispatch every leg (and every basket
  rollback leg) through the same gated `build_gated_leg_dispatchers` `place_leg`
  as a bracket leg (SafetySystem L1–L5 → `gate_order` one-shot HMAC
  `SafetyContext` → `BrokerRouter` → adapter), hold no broker client, and are
  wired in `create_flask_app` bound to the request's session-JWT principal.
  `basket_orders.py`/`split_orders.py` were removed from the
  `test_no_legacy_order_path` raw-route allowlist and pinned by new gated tests
  (they graduated exactly as `BRACKET_SERVICE` did). The executors are
  synchronous like the bracket service (the gated `place_leg` marshals broker
  I/O onto the client's owner loop itself), so they work under the bare-WSGI /
  gunicorn deployment too — an adversarial-review finding where the previous
  async wrapping would have failed every leg closed when no client was bound.
- **Rust ticks crate is now tested in CI** — a `rust-ticks-tests` job
  (`test.yml`, eighth per-push Ubuntu job) runs `cargo test` on the
  `packages/core/ticks` crate. Its unit tests ran in no CI job before (`cargo
  audit` in `supply-chain.yml` checks advisories, not behaviour). A guarded
  `make ticks-test` target runs the same tests locally (skipped when `cargo` is
  absent) and `make test` now chains it.
- **Gated bracket orders** — `POST /api/v1/orders/bracket` (entry + stop-loss
  or target exit) is now live: every leg traverses SafetySystem L1–L5 →
  `gate_order` → `BrokerRouter` via injected dispatchers (the service holds no
  broker client), cancel is mode-guarded and fails closed when every leg
  cancel fails, and honest warnings call out unconfirmed legs and a filled
  MARKET entry position that cancelling does not close. OCO pairs and trailing
  are refused at placement rather than silently accepted.
- **Per-position square-off** — the Positions widget gained a per-row
  Square-off (opposite-side market order through the existing gated path, with
  confirm), alongside Convert and Exit-all.
- **Scalper SL/Target legs, honestly this time** — the inputs removed earlier
  (they silently never sent) are back, wired to the gated bracket endpoint:
  one exit leg per order (the backend refuses OCO pairs it cannot monitor),
  absolute leg prices anchored to the limit price or live LTP (fail-closed
  without an anchor), and "bracket placed — legs pending", never "filled".
  The Scalper also resolves lot sizes at runtime from the symbol master
  (its hardcoded table is now an explicitly-marked display-only fallback).
- **In-app updater (release asset first)** — Settings → Updates (desktop builds
  only) compares the running version against the newest desktop release with a
  matching platform asset and runs the bundled installer script in binary
  update mode. Machines with a source checkout still get **Rebuild from
  source** as a separate advanced fallback.
- **One lot-size table** — the screener's contract-size table (with a
  provenance-aware resolver over the live symbol master) is now the single
  source: the mirror engine (BANKNIFTY was 15 — badly stale, mis-sizing
  mirrored quantities), the MCP order parser (FINNIFTY 40 vs the current 65),
  two backtest strategy registries, and the demo fallback all derive from it,
  and underlying matching prefers the longest match ("NIFTY" no longer
  shadows BANKNIFTY contracts).
- **Watchlist drives the chart** — clicking a watchlist row now retargets the
  default chart panel; charts pinned to an explicit symbol keep it.
- **Live tick wiring for order widgets** — OrderPad and OrderLadder now
  actually subscribe to the ticks they render (Fund-mode sizing and ladder
  pricing were dead for unsubscribed symbols), and the OrderLadder reconciles
  its rows against the live order book so fills/rejections clear stale rows.
- **Demo-data badges everywhere** — the eight option-analytics widgets (GEX,
  Gamma Density, Vol Surface, OI Profile, Straddle P&L, IV Smile, Greeks
  Surface, Historical Chain) and the economic calendar now surface the
  `is_sample_data` flag visibly; the Arbitrage Scanner sends real scan
  parameters and shows honest empty/error states instead of refetching a
  canned sample.
- **Desktop self-healing** — the Tauri shell detects and terminates a stale
  sidecar from a crashed run (identity-checked PID file) and the sidecar
  carries a parent-liveness watchdog, so force-quits no longer orphan
  backends; broker OAuth pages open in the system browser through a scoped
  opener capability (the webview's `window.open` was a dead button).
- **Set-PIN-later path** — `POST /v1/auth/pin/set` lets an operator who skipped
  the optional PIN at account setup create (or change) the 6-digit quick-unlock
  PIN over a live session, with the account password as a re-confirmation
  factor. Previously Live mode was permanently unreachable for PIN-less
  accounts (every unlock said "Invalid PIN.") and the only escape was wiping
  the account. `/v1/auth/status` now reports `has_pin`, and a PIN-less Live
  unlock returns a distinct "No PIN is set" message pointing at the fix
  instead of masquerading as a wrong PIN.
- **Native SDK readiness surfaced** — `/api/v1/broker/capabilities`,
  `/api/v1/broker/mcp`, and the native broker catalogue rows now carry the
  repo-managed SDK attestation status (pinned vs installed version), so the
  connect UI can say exactly why a native broker is not ready.
- **Broker connect blockers in metadata** — native catalogue rows expose
  `requires_static_ip` and human-readable `native_connect_blockers`, rendered
  in the shared BrokerConnect surface for the coming-soon brokers.
- **Workspace-persisted OpenAlgo REST port** — a REST Port field in Settings →
  Broker Gateway and Setup → OpenAlgo Bridge persists `openalgo.port` to
  `workspace.json`; every consolidated route resolves the OpenAlgo base URL
  through the shared `openalgo_rest_base_url` helper, so a non-default REST
  port no longer needs a `.env` edit.
- **OpenAlgo connection cache is no longer a second credential store** — the
  terminal hydrates host/WebSocket state from `/v1/config/openalgo` on app
  startup, keeps any just-entered API key only in memory for the current
  session, clears the legacy `flinttrade:connection` session cache, and lets
  authenticated app API calls use the FlintTrade session JWT instead of relying
  on a browser-persisted OpenAlgo key.
- **LLM config persists from Settings** — `GET/POST /v1/config/llm` now stores
  provider, host, and model in `workspace.json`, stores the active provider API
  key in a hardened local secret referenced by `llm.api_key_ref`, returns only
  redacted key metadata, and `LLMConfig.from_env()` resolves that workspace
  secret when explicit env overrides are absent.

- **Six new Analysis widgets** — FII Long/Short, Gamma Density, Arbitrage Scanner,
  Index Contribution, Pattern Detection, and Time & Sales, taking the widget
  catalogue from 95 to 101. Backed by new screener routes:
  `GET /api/v1/screener/fii-long-short`, `POST /api/v1/gammadensity`,
  `POST /api/v1/screener/arbitrage`, `POST /api/v1/candlestick-patterns`, and
  `GET /v1/index-contribution`.
- **Watchlist formula builder** — a safe expression engine (no `eval`; a
  purpose-built parser over quote fields) powers user-defined formula columns in
  the Watchlist, plus row-hover **quick Buy/Sell** buttons that open the OrderPad
  pre-filled for that scrip — the ticket still traverses the full gated execution
  path.
- **Invest hide-values toggle** — a privacy control on the Invest workspace that
  masks holdings, net-worth, and P&L amounts on screen.
- **GoCharting webhook source** — `/v1/webhook/gocharting` joins TradingView,
  ChartInk, and custom as an accepted webhook source, routed through the same
  gated dispatcher.
- **BROKER_CATALOG 32 → 35** — catalogued the OpenAlgo MCP entry plus the
  upstream `arrow` and `tradesmart` adapters in the broker catalogue.
- **Desktop close-to-tray background runtime** — closing the window now hides it
  to the system tray while the backend sidecar (and any running agent) keeps
  working, with a tray menu (Show/Quit), a global show/hide hotkey
  (Cmd/Ctrl+Shift+F), and native notifications; quit fully via the tray's
  "Quit FlintTrade".
- **ML/AI dependency stack installed by default** — vectorbt, lightgbm, optuna,
  chromadb, openpyxl, and reportlab join the default environment, unlocking 68
  previously skipped tests.
- **Native desktop app (Linux, Windows, macOS)** — a Tauri 2 shell
  (`packages/apps/desktop`) packages the FlintTrade backend and terminal into a
  single installable app. On launch it provisions the credential-vault master
  password (first run only), spawns the PyInstaller-frozen backend sidecar on an
  OS-chosen loopback port, waits for the `FLINTTRADE_BACKEND_READY` handshake,
  and points one native window at it — the backend serves both the React
  terminal and the API from that single origin, so every feature works with no
  separate server to run and no in-app configuration. A brand-matched splash
  window covers boot. Build with `make desktop-build` (frontend + backend
  sidecar + Tauri bundle) or run `make desktop-dev`; see
  [docs/DESKTOP.md](docs/DESKTOP.md).
- **Native broker adapters at full feature parity (Dhan, Upstox, Kotak Neo, IndMoney)** —
  the four founder-broker adapters were built out from gated skeletons to the **complete**
  doc-grounded surface, each from a feature matrix vs the broker's own API docs/SDK. Dhan:
  orders (all products/validities), forever (GTT) + super (CO/BO) + conditional-trigger
  (v2.5) management, order slicing, Trader's Control (P&L exit + Exit All), EDIS,
  convert-position, margin, historical incl. expired options, option chain, quotes,
  market-feed + 20/200-level depth + order-update WebSockets. Upstox: full v2/v3 surface
  incl. OAuth, GTT, slicing, multi-order, cancel-all/exit-all, brokerage + P&L, v3
  quotes/Greeks, 1-second candles + expired instruments, a broker-error→taxonomy mapping,
  and the v3 feed. Kotak Neo: TOTP login, BO/CO leg cancels, order/trade history, limits,
  8 quote types + depth, scrip master/search, HSM feeds. IndMoney (no official SDK): a
  REST + WebSocket adapter built from scratch with smart (GTT/OCO) orders. All four advertise
  honest capabilities, mint every write through the gated path, and stay dormant until SDK
  attestation + vault credentials — the remaining work is live-credential testing only.
- **Extended gated routing + reconciliation** — `gate_broker_write` + `BrokerRouter.execute_gated`
  (table-driven, the verb discriminator signed into the one-shot HMAC) make the forever / super /
  conditional-trigger / convert-position / exit-all / multi-order / cancel-all / smart-cancel
  verbs reachable through the single gated path, exposed as `/api/v1/orders/*` + `/api/v1/positions/*`
  routes and as Forever (GTT), Super Orders and Conditional Triggers terminal widgets (plus a
  broker-target selector and typed-EXIT confirmation on the Positions widget's Convert / Exit-all).
  `Order` gained optional `validity` + OCO leg fields. A reconciliation layer
  (`flinttrade_gateway.reconciliation` + an engine-side runner persisting JSONL reports and
  emitting `RECONCILIATION_MISMATCH` audit events) compares broker-side state to FlintTrade's,
  surfaced in a Reconciliation widget.
- **Autonomous trading agent — control plane** — `POST /api/v1/ai/agent/{start,stop,status}`
  runs the LLM-driven analyse → signal → risk-check → execute loop as a background
  session, surfaced in the AI route's **Agent** panel (start form, live P&L / cycles /
  positions, "Stop & square off"). OFF by default (`ai.autonomous_agent.enabled`),
  live-mode only; the agent runs as its own ACL'd principal (`autonomous-trader`) and
  every order — including SL/TP exits and end-of-day square-off — traverses the full
  gated path. Logout / mode-downgrade revokes the agent's orders mid-session.
- **Smart order routing** — `POST /api/v1/orders/smart-route` slices a parent order by
  urgency (high = single market order, medium = depth-aware chunks, low = TWAP over a
  configurable window) as a background job with live polling and a cancel control, and a
  **Smart Order** terminal widget drives it. Every child order independently traverses
  the full gated execution path (SafetySystem L1–L5 → `gate_order` → `BrokerRouter`);
  the budget is enforced and an order larger than the visible book is refused (use TWAP).
  OFF by default (`brokers.smart_routing.enabled`) and live-mode only.
- **Options Builder in the Lab** — the previously unreachable Strategy Builder tool
  (legs / payoff / margin / Pine) is mounted as a Lab tab, and the Strategy Templates
  widget now loads its option-only templates into it with explicit strike offsets
  (an iron condor arrives as four distinct strikes, not two indistinguishable "OTM"
  legs). Templates containing stock or multi-expiry legs are honestly marked
  reference-only rather than loaded as degenerate approximations.
- **Excel import** — `POST /api/v1/integration/excel/import/upload` accepts a browser
  file upload (multipart), and Settings → Data gained a **download-watchlist manager**
  (list / add / remove symbols, plus "Import from Excel" with skipped-row reporting) —
  previously the bulk downloader's watchlist had no UI at all, so a fresh install could
  never populate it.
- **n8n bridge surface** — Automate → "n8n Bridge" section wires the existing backend
  bridge end-to-end: connection health, workflow activate/deactivate, and a manual
  webhook trigger, with honest offline and missing-API-key states. `N8N_HOST` /
  `N8N_API_KEY` are documented in `.env.example`.
- Home **Breadth card** now shows live market breadth when a broker is connected
  (same `/v1/breadth/current` contract as the Market Breadth widget), with the demo
  badge retained whenever the data is sample.
- Native **Upstox** and **Kotak Neo** broker adapter skeletons (gated, doc-grounded
  capabilities) alongside Dhan, plus a **broker capability recommender**
  and `GET /api/v1/broker/recommendations` filtering broker metadata per use case
  (low-cost execution, market depth, options analytics, historical data,
  streaming, throughput, advanced orders).
- AI panel routes `GET /api/v1/ai/sentiment/summary`, `…/ai/sentiment/tickers`, and
  `…/ai/regime` (previously 404) — wired to the sentiment and regime engines with
  honest degradation when no data source is connected.
- Sandbox `GET /v1/sandbox/status` — combined virtual-capital status for the terminal
  panel.
- **Options Scalper** workspace preset (Index/Futures + CE/PE strike charts + Option
  Chain) and per-panel chart symbol pinning; all 14 layouts now applicable from the
  Ctrl+K command palette.
- **Live trade journalling** — every executed live order is now recorded to a shared
  DuckDB store (best-effort, never blocks the order), so the trade journal and P&L
  analytics populate in Live instead of staying empty. `GET /api/v1/trades/journal`
  reads the same store and supports a `start_date`+`end_date` history window across all
  strategies (`StorageManager.get_trades_by_date_range`).
- **Order-latency monitoring** — the gated order dispatch now feeds the latency tracker,
  so per-broker round-trip stats populate `/api/v1/latency/stats` (previously empty).
- **Nightly DuckDB maintenance** — a scheduled `db_optimise_job` (00:30 IST) runs
  `CHECKPOINT` + `ANALYZE` on the shared trade/tick store so the database stays compact
  and queries stay fast.
- **Regime-aware strategy suggestion** — the AI Regime panel now recommends a
  regime-appropriate strategy style (momentum / mean-reversion / theta / stand-aside)
  via `select_strategy_for_regime`, surfaced in `GET /ai/regime` as `suggested_strategy`.

### Changed

- **AI consolidation and lifecycle ownership** — the componentised RAG,
  tiered memory, reflection, sentiment, multi-agent, and signal pipelines are
  the canonical implementations; duplicate modules were retired only after
  their unique refinements moved. RAG domain filtering is opt-in for the docs
  corpus, and scheduled training/agents now respect dated exchange sessions
  and process-owned shutdown.
- **One Practice paper engine** — the engine-package `SandboxEngine` and its
  `/v1/sandbox-config` blueprint were retired after their unique capabilities
  (leverage-aware `SandboxConfig` and margin estimation, pending
  LIMIT/SL/SL-M fills, trades ledger, daily P&L history, square-off) moved
  into the canonical data-package `SandboxEngine` behind the existing
  `/v1/sandbox` surface. Practice dispatch, the strategy sandbox, and the
  terminal Practice controls now share the single engine.
- **Read-only (analytics-token) broker sessions are demoted from the live
  write default** — a connect or daily re-login that comes back read-only can
  no longer become or remain `brokers.execution.default` or the vault primary.
  The replacement policy fails closed: the prior default is restored, else the
  configured OpenAlgo bridge, else the default is CLEARED (never an arbitrary
  other account), and the connect/re-login response carries a `notice` telling
  the operator the write default changed. A corrupt `workspace.json` defers
  the demotion with a notice instead of failing the connect with a 500.
- **Native setup completion requires a write-capable broker** — finishing
  native broker setup with only read-only sessions connected is refused, so a
  fresh install cannot end setup with an untradeable write default.
- **Setup wizard's Practice choice now mints a Practice session** — choosing
  Practice on the final setup step routes through the server mode transition
  (`POST /v1/auth/mode`) before the UI flips, so the first sandbox order no
  longer fails 403 `mode_blocked` under a PRACTICE badge; on failure the
  wizard shows a notice and keeps UI and JWT in lockstep. The setup wizard's
  Connected Accounts list also now shares Settings' primary-eligibility rule,
  so stale or read-only gateway rows no longer offer "Set primary".
- **INDstocks sessions expire at the daily 06:00 IST token reset** — the
  INDmoney adapter stamps session expiry to the broker's documented daily
  token reset so the morning refresh re-authenticates instead of trusting a
  dead token.

### Fixed

- **Action Centre crash recovery** — an approval left in the `dispatching`
  state by a process that died mid-dispatch is now reconciled on queue open:
  it is terminally closed as failed with `outcome_uncertain` set (the broker
  outcome is genuinely unknown), so it is never silently re-dispatched nor
  marked approved, and it no longer lingers as a phantom in-flight intent that
  the pending-order expiry sweep cannot touch.
- **Ditto emergency-flatten fail-safe** — when the managed-account kill-all
  declines because the mirror cannot be quiesced in time, the mirror is now
  guaranteed deactivated before the refusal surfaces, and the operator-facing
  error names the account-wide kill switch as the escalation path.
- **Safety-critical runtime wave** — emergency flattening is selector-bound,
  gated, generation-leased, and journalled; a durable-journal storage outage
  now degrades the already-latched cancel/flatten operation to a process-local
  write-ahead journal instead of vetoing exposure reduction, while durable
  latch reset remains fail-closed. The degrade also covers the LATCH itself:
  a failed durable episode write no longer vetoes the L5/MTM flatten — the
  episode falls back to the dispatcher's process-local journal (reset still
  requires the durable store). One process-wide fallback journal is shared by
  the runtime and HTTP dispatchers so replay/acknowledgement continuity spans
  activations during an outage, and HTTP kill-switch activation latches L5
  BEFORE taking the router generation lease — a busy rebuild now degrades the
  broker sweep to a bounded partial outcome with the latch held instead of
  refusing to latch at all. Live-order owners, SSE streams, strategy
  children, retrainers, tick capture, and desktop sidecars are quiesced before
  dependency teardown and retained for retry when a drain cannot be proved.
- **Ditto management writes require the operator session (G9)** — account
  create/enable/disable/delete and mirror-stop were reachable with the API key
  alone; all five now demand a valid session JWT in any mode (kill-all and
  mirror-start keep their stronger live-operator guards). The terminal kill
  switch also stays available when the safety-config refresh fails with a
  last-known state on screen (emergency controls fail available).
- **Managed local-AI transitions fail closed under races and teardown** — one
  bounded deadline covers process verification and shutdown, inconclusive
  ownership is refused, Windows state reads are reparse-safe, and failed boot
  stops the child before dependent teardown. Configuration changes are
  revision-bound and rollback-checked; the terminal waits for hydration,
  handles stored credentials explicitly and keeps runtime Stop available during
  long start or model-pull operations.
- **Market-state and persistence integrity** — indexed legacy DuckDB tick
  schemas migrate safely, order-flow checkpoints bind to committed cursors and
  source provenance, spread arithmetic validates before parallel execution,
  and an unreachable OpenAlgo calendar no longer disarms calendar-independent
  cron or Practice scheduling. Empty/malformed calendar envelopes remain
  non-authoritative.
- **Intraday P&L now books partial-close realised from the tradebook** — the
  widget split realised from positionbook alone, so a position partially closed
  earlier in the session showed zero realised (the booked amount was buried in
  the still-open row and overwritten by the local MTM). It now attributes
  per-symbol realised from today's tradebook (a shared `lib/pnl.ts` FIFO helper,
  also used by the P&L dashboard) to open positions, keeps the accurate broker
  pnl for fully-closed rows, and falls back to the old behaviour when the
  tradebook is unavailable. Realised for a position carried over from a prior
  day remains understated (no matching buy leg in today's tradebook) — the same
  documented intraday-only limitation.
- **`make full-check` no longer OOMs on the vitest stage** — it ran the entire
  terminal suite unbounded in one 4 GB process, which OOMs on the same heavy
  widgets CI has to shard around. It now uses CI's form (`--pool=forks
  --maxWorkers=1 --no-file-parallelism`, fork-per-file isolation caps peak
  memory at the heaviest single file) with an 8 GB heap.
- **Practice fills no longer fabricate a position at price 0.0** — both paper
  engines at the time (`flinttrade_data.SandboxEngine` — the Practice dispatch
  target — and the since-retired `flinttrade_engine.SandboxEngine`, now folded
  into the data engine) rejected
  nothing when a MARKET order arrived without a live price, so the fill booked
  at 0.0 (a zero-notional order that also skipped the capital check) and created
  a position at an average price of zero. Both engines now reject a
  zero/negative-price market fill with a clear message; the DuckDB engine keeps
  an `allow_zero_price_fills` opt-in for the fill-lifecycle tests only, never in
  production. The Order Pad feeds the live LTP as the price for a Practice
  MARKET/SL-M order so the paper fill is realistic — live-order payloads are
  unchanged (a live market order still sends price 0; the broker fills at
  market).
- **OrderPad could never place an NFO order in a real browser** — the quantity
  input's `min=1 step=<lot>` made every exact lot multiple a native
  `stepMismatch`, silently blocking form submission before validation ran.
  The form now opts out of native constraint validation (zod + an explicit
  fail-closed lot-multiple check own it, with clear messages) and the stepper
  is lot-aligned.
- **Order flow honesty** — the order book refetches on placement and keeps a
  session-aware refresh across NSE/BSE day and MCX/CDS evening hours (it
  previously froze outside NSE hours); Intraday P&L coerces string-typed
  broker `pnl`/`quantity` and computes P&L locally where possible; MTM
  Monitor/Net Position show error banners + staleness instead of silently
  freezing; Action Centre approve/reject failures surface the server message
  with a retry.
- **WebSocket failure modes** — reconnects now back off exponentially and an
  authentication failure stops retrying after a bounded number of attempts and
  surfaces "authentication failed" to the connection UI (previously a ~1 s
  silent reconnect loop, forever); the per-instrument tick-atom cache is
  bounded instead of retaining every symbol for the tab's lifetime.
- **Settings/setup traps** — the Broker Gateway placeholder no longer points
  the OpenAlgo URL at FlintTrade's own backend port; clearing the REST Port
  field now clears the override instead of silently failing the save; Test
  Connection exercises the candidate values without committing them to the
  live connection store first; the Practice-mode card no longer claims a
  broker is required; QuickTrade requires an explicit instrument instead of
  defaulting to NIFTY; the orphaned /setup wizard is reachable again; a
  freshly-demoted read-only connect now says why.
- **Backend hygiene** — the request traffic logger serialises its DuckDB
  writes behind a lock and prunes by age/row cap (it previously wrote from all
  request threads unlocked and grew forever); the duplicated SDK-attestation
  helper collapsed into a single gateway implementation; Upstox session
  read-only classification is derived server-side (fail-closed) instead of
  client-declared; the live-probe script derives Upstox analytics-token
  defaults from `BROKER_CATALOG` so they cannot drift.
- **`FLINTTRADE_PORT` unified** — Docker/compose/entrypoint used a variable
  the backend never read; everything now uses `FLINTTRADE_BACKEND_PORT` (the
  container entrypoint still honours the legacy name).
- **Legacy state migrated to the platform workspace directory** — the
  download watchlist (`watchlist.db`) and trained AI signal model
  (`signal_model.joblib`) moved from `~/.flinttrade` to the cross-platform
  workspace directory without a migration; both are now copied forward
  one-shot on first use, so existing macOS/Windows installs keep their
  curated watchlist and trained model (the legacy files remain as backups).
- **Expiry-tracker capture survives OpenAlgo settings hot-reload** — the
  tracker now resolves the shared OpenAlgo client per capture instead of
  capturing (and outliving) a client the Settings hot-reload had closed,
  which previously broke every capture until a backend restart.
- **AI signal history honours the configured OpenAlgo REST port** — the
  signal pipeline's fallback client is built from the full workspace/env
  settings instead of a partial host+key rebuild that silently reverted to
  port 5000.
- NOTICE regeneration — the ML/AI dependency wave changed the lockfiles without
  regenerating `notice.generated`, failing the Supply Chain NOTICE-drift gate;
  the bundle is regenerated against the current lockfiles and the gate is green
  again.
- Final `v0.6.0-beta.1` app audit fixes: Live setup now verifies the PIN and
  stores the live-unlocked session token before entering Live mode; normal
  password and 2FA login clears stale Live UI state; Explore onboarding CTAs
  route first-time users to account setup; the site release catalogue includes
  the current beta note; desktop release dispatch rejects stale tags; and
  Supply Chain CI audits the desktop Rust lockfile with expiring reviewed
  warning allowlist entries.
- The desktop Tauri lockfile no longer carries the vulnerable `quick-xml`
  `0.39.x` line (`RUSTSEC-2026-0194`); `plist` 1.9.0 is temporarily vendored
  with only its `quick-xml` dependency bumped to the patched `0.41.x` floor
  until upstream publishes a compatible release.
- AI memory retrieval survives a wedged ChromaDB vector index — chromadb 1.5.9's Rust
  core can permanently lose an `add()`'s embedding write under rapid collection churn
  (upstream chroma-core/chroma#7032: every later vector query raises "Error finding id"
  while the row's metadata stays readable; ~4% of adds in tight loops, unrecoverable by
  retry or a fresh handle). `get_memories` now degrades to metadata retrieval (symbol
  filter + recency/importance ranking with neutral similarity, logged loudly) instead of
  silently returning no memories, so the agent loop never goes blind. Root cause of the
  intermittent `test_all_four_layers_independent` failure.
- Home market-breadth card showed sample data even with a broker connected — the live
  branch called a registry method that does not exist. It now computes real NIFTY 50
  advance/decline from a live quote sweep (and stays honestly "sample" when the sweep
  is unavailable or too thin), without mutating the shared sample series.
- Excel import required a worksheet literally named "Sheet1"; it now reads the
  workbook's first sheet, so FlintTrade's own exports (sheet "Data") round-trip, and the
  response reports the sheet actually read. A partial watchlist import is reported
  honestly (added / skipped / failed) instead of as a total failure.
- Strategy-builder margin estimates used a single hardcoded notional for every
  underlying (a SENSEX spread priced like a NIFTY one); they now derive from each leg's
  real strike × lot size, and the lot sizes were updated to current values.
- Parallel test runs no longer contend on a single machine-wide DuckDB file when the
  local `.env` pins `DUCKDB_PATH` — the test harness isolates a per-worker scratch
  database (at the repo root and the data package), fixing a recurring trade-store
  wiring flake.
- The Windows `make test` target now includes the ditto (Account Manager) package
  tests, matching the POSIX glob.
- ftApi helpers now surface the backend's actionable `{status, message}` body on a
  non-2xx response instead of a bare "HTTP 403", so disabled-feature / missing-ACL /
  missing-key errors reach the operator verbatim across every helper-based surface.
- Terminal build restored — shadcn primitives imported undeclared `@radix-ui/react-*`
  packages; migrated to the unified `radix-ui` (87 TS errors → 0).
- Welcome screen no longer hangs on "Checking workspace…" when the backend is
  unreachable (graceful degradation in production, not just dev).
- Option Chain widget crashed in production builds (`react-responsive-carousel`
  externalised); no longer externalises glide-data-grid's bundled peer deps.
- Strategy runner wired (`STRATEGY_RUNNER`/`CRON_SCHEDULER`) — `/api/v1/strategies`
  no longer 503s in production.
- RiskSection sent rupee MTM values into the backend's *percentage* daily-loss fields
  (the Layer 4 hard stop could never latch) and sent 0 for blank fields (hard stop on
  any loss) — now percentages, blanks omitted.
- StrategyMonitor no longer renders fabricated live P&L when a broker is connected.
- Sandbox virtual-capital panel works end-to-end (status/adjust/export/import contracts
  aligned).
- All six analysis routes (GEX/IV/OI/vol-surface) honour the terminal's
  `expiry_date`/`expiry_dates` keys instead of silently using a hardcoded expiry.
- AI Signals tab reads the working `/signals/recent` instead of the unwired
  `/signals/active`.
- Workspace preset save/edit no longer 400s (client `widgets` aligned to the backend's
  ID-list model; cards derive the widget count).
- Earnings sample data always includes recent past results regardless of the calendar
  date.
- Trade Log, Trade Performance, Net Positions and Risk Dashboard no longer show
  fabricated sample data to a *connected* user — each now switches to the real broker
  positionbook / funds / trade journal when connected (the connection flag previously
  only toggled a "Sample" badge). Risk Dashboard shows only the metrics it can derive
  faithfully (exposure, margin utilised); net delta / theta / max-loss are omitted with
  an honest note rather than invented, pending a portfolio option-greeks feed.
- `order_analytics`/`strategy_comparison` blueprints registered (`/api/v1/...`) — were
  defined but never wired.
- **14 more analysis/utility widgets** no longer show fabricated data to a connected
  user — each renders an always-visible "Sample data" badge (or an honest empty state)
  instead of disguising sample data as live, and deceptive "live updating" affordances
  were removed (Market Summary, Multi-Timeframe, Correlation Pairs/Matrix, VWAP Bands,
  PCR Trend, Sector Performance, Implied Move, Instrument Compare, Heat Calendar,
  Microstructure, Audit Trail, Global Indices, Earnings Calendar).
- **Five analysis endpoints** (GEX, IV Smile, Vol Surface, OI Profile, Straddle P&L)
  now return the shape their widgets expect — they previously emitted raw dataclass
  field names, so the widgets read undefined and rendered empty when connected.
- Market Breadth fetched a 404 route (`/breadth` vs `/breadth/current`) and silently
  showed sample data; now fetches the correct route and flags backend sample data.
- Trade-journal analytics counted open legs (null P&L) as losing trades, distorting
  win-rate; open legs are now excluded until they have a realised P&L.
- Safety layer L2 (position-count + margin %) now enforces against **live** portfolio
  state on the manual order path AND the smart-route / autonomous-agent paths — it
  previously ran on empty/zero state and never fired. Live positions + funds are
  fetched best-effort (a read hiccup never blocks an order; smart routes cache once
  per route, the agent fetches fresh per order), scoped to the functional OpenAlgo
  adapter, and L2's quantity parse tolerates float-strings.

### Removed

- **Superseded emergency dispatcher** — the unreferenced
  `_dispatch_legacy_target` was dropped from the safety engine after
  `_dispatch_planned_target` (a strict superset that adds intent settle /
  mark-unknown / coordinated-lease handling) became the live path
  `dispatch_prepared` calls. Removing the dead path keeps it unambiguous which
  dispatcher the safety file actually runs.
- **Unused Ollama loopback-port helper** — `_allocate_loopback_port` was never
  wired as `OllamaRuntime`'s port allocator (which defaults to binding port 0
  for a race-free OS-assigned ephemeral port), so the abandoned
  bind-probe-then-rebind scaffolding was removed.
- **Multi-user backend** (`/api/v1/users/*` CRUD + the `admin`/`trader`/`viewer`
  account manager, previously opt-in behind `FLINTTRADE_MULTI_USER`) — removed as
  overscope. FlintTrade is a single-operator personal-use tool (operator == user ==
  data principal); a multi-user admin surface is out of scope. If ever needed it
  should be redesigned around the gated-principal model, not a parallel user table.
  The frontend admin user-CRUD clients were already removed.

## [0.6.0-alpha] - 2026-05-30

Tag: `v0.6.0-alpha` · Type: SemVer alpha prerelease · Status: not
production ready.

### Added

- Root [disclaimer.md](disclaimer.md) covering alpha readiness, no-advice
  boundaries, trading risk, user responsibility, and no-warranty terms.
- Central product-version helpers for terminal, backend, and site-generated
  metadata so Settings, docs MCP, website content, and backend startup agree
  on `v0.6.0-alpha`.
- Public Next.js/Fumadocs site generation for docs, package READMEs, release
  notes, llms files, and the read-only contribution MCP.
- Home widget picker/frame/registry surfaces with add, remove, preset,
  drag/reorder, and resize behaviour covered by terminal tests.
- Ditto account create, enable/disable, and delete flows in the terminal plus
  backend route coverage.
- Restructure regression tests that catch stale package paths, lowercase root
  document drift, optional-OpenAlgo violations, shared UI delegation, and
  docs/site version mismatches.

### Changed

- Repository layout documented as `packages/apps`, `packages/core`,
  `packages/integrations`, and `packages/services`, with 17 package surfaces:
  13 Python packages, 2 React apps, 1 shared TypeScript design system, and
  1 Rust/PyO3 tick engine.
- Makefile, systemd, cron, deployment, rollback, health, status, and reset
  scripts now treat FlintTrade's backend as the primary runtime and OpenAlgo
  as an optional external integration.
- Terminal welcome, Explore/Demo, Settings, overlay stacking, home widgets,
  Ditto, setup, connection, and version display flows were tightened to match
  the centralised design-system and backend boundaries.
- Public README, docs index, architecture guide, developer guide, setup
  quickstart, API reference, CI guide, issue template, website landing page,
  and package READMEs were updated for the alpha release.
- Screenshot references were refreshed to current terminal screens and
  transient broken/fixed screenshots were removed from the public docs set.

### Fixed

- Settings crash from empty Radix Select item values.
- Demo mode navigation entering the terminal instead of the intended dashboard
  route.
- Explore route drift where the explanatory Explore page and demo entry point
  were conflated.
- UI layering conflicts where popover descriptions could render under app
  sidebars.
- Home "Add widget" and widget drag/resize wiring that existed in UI shape
  but was not fully connected.
- Credentials store: the `adapter_id` backfill and `set_primary` updates are now
  atomic under SQLite autocommit (no permanently-stranded legacy accounts after a
  crash mid-migration, and no transient zero-primary window); a duplicate-column
  migration race is tolerated; the broker rollback snapshot is written atomically.
- A malformed `brokers.account_acls` block now raises a typed `RoutingConfigError`
  at parse time instead of surfacing a late `AttributeError`.

### Security

- **Selector-bound principal + gated execution** (the v0.6.0-alpha namesake,
  previously absent from this changelog). Live orders bind to a canonical
  `adapter_id:account_id` selector and are authorised per `(actor, account)`:
  `gate_order` mints a one-shot, HMAC-signed `SafetyContext` (binding the order,
  mode, caller, adapter, and account); the `BrokerRouter` verifies and consumes
  it before any broker write; an `AuthenticatingSessionProvider` enforces
  `workspace.json` `brokers.account_acls`. The credentials store gained an
  `adapter_id` column with an additive, self-healing backfill migration.
- The live order endpoint `POST /api/v1/orders/place` — the path the terminal
  actually calls — now runs through the 5-layer SafetySystem, the one-shot gate,
  and the per-account ACL instead of forwarding straight to OpenAlgo. It can no
  longer place an unvalidated, unbound order, and fails closed with an actionable
  message when the gate, ACL, or routing is not configured. Live `/modify` and
  `/cancel` now run the same one-shot gate + per-account ACL (via new
  `BrokerRouter.modify_order`/`cancel_order`; modify is also kill-switch-guarded,
  cancel is always permitted so a halted account can still reduce exposure). The
  remaining live actions (smart/options/GTT/cancel-all/close/open) stay
  kill-switch-guarded pending their own `BrokerRouter` write methods.
- The first operator to log in is **auto-authorised** for the default execution
  account (trust-on-first-use): their actor id (JWT `sub`) is added to the running
  router's ACL so gated `/place`, `/modify`, and `/cancel` work without a manual
  `workspace.json` edit. This is in-memory and re-established by an actual
  authenticated login each process — non-human actors (Ditto, ChartInk, agents)
  and additional human users must still be listed explicitly in
  `brokers.account_acls`.
- The dedicated safety-gate HMAC secret is now generated and bound at startup
  (hardened `~/.flinttrade/safety_gate_secret`), so the gated path is functional
  rather than refusing every order.
- Ditto's multi-account mirror now **fails closed by default**: without an injected
  `BrokerRouter`, the transitional ungated raw-OpenAlgo forward is refused unless
  the operator explicitly opts in (`allow_ungated_fallback=True`). The gated
  mirror path (account-bound HMAC + ACL + one-shot consume) is the only enabled
  route otherwise.
- Operational log streams (`/v1/logs/stream`, `/v1/logs/recent`) now also redact
  IPv6 addresses and bare high-entropy tokens.

### Notes

- This is an alpha release. Users should stay in Explore or Practice mode
  until they have reviewed the code, configured broker-side safeguards, and
  verified their own environment.
- OpenAlgo remains supported through the optional OpenAlgo-compatible API
  path; it is not bundled or required for FlintTrade's core backend.

### Removed

- Removed `.github/FUNDING.yml` until FlintTrade has live sponsorship accounts to link to.

### OpenAlgo v2.0.1.1 parity sync (2026-05-21)

Refresh of the OpenAlgo integration from upstream `08c2a553` (post-v2.0.0.5)
to `7e48b2e8` (post-v2.0.1.1) — 199 commits across six version bumps.
Findings catalogued in `.local/openalgo-sync-2.0.1.1/`.

#### Added

- **GTT (Good Till Triggered) orders** end-to-end. New methods
  `place_gtt` / `modify_gtt` / `cancel_gtt` / `gtt_orderbook` on
  `OpenAlgoClient`. New Pydantic models `GttOrder`, `ModifyGttOrder`,
  `CancelGttOrder`, `GttTrigger`. New safety-proxy routes at
  `/api/v1/orders/gtt-{place,modify,cancel}` that honour the mode gate
  and live-mode JWT unlock. Frontend helpers `placeGtt` / `modifyGtt` /
  `cancelGtt` / `getGttOrderbook` plus `GTT_PRODUCTS` / `GTT_TRIGGER_TYPES`
  constants and `tradingConstants.GTT_PRODUCTS`. Live broker support
  upstream: Dhan + Zerodha. Other brokers return clean 501.
- **New exchanges** `NCO` (NSE Commodities), `MCX_INDEX`, `GLOBAL_INDEX`
  added to `Exchange` enum (`packages/core/core/src/models.py`), per-broker
  `BROKER_CATALOG` (`packages/integrations/gateway/src/adapter.py`), backend enums
  (`safety.py`, `market_hours.py`, `scheduler.py`, `strategy_routes.py`,
  `historical/downloader.py`, `integration/tradingview.py`), `flint.toml`,
  and frontend constants (`tradingConstants.ts`, `market.ts`, `BacktestLab`,
  `StrategyBuilder/types.ts`, `widgets/analysis/Depth/`,
  `tools/FlowBuilder/flow/ConfigPanel.tsx`).
- **IIFL Capital broker** added to `BROKER_CATALOG` as a distinct entry
  alongside `iifl`. Live MQTT market-data feed picked up automatically
  from the refreshed upstream checkout.
- **`search()` exchange filter** — `OpenAlgoClient.search()` and the
  terminal `searchSymbol()` helper now forward the optional `exchange`
  kwarg added to upstream's `SearchSchema` in v2.0.1.x.
- **WhatsApp settings section** in Settings → WhatsApp. Outbound-only
  surface (`POST /api/v1/whatsapp/notify`) wired to the existing
  `testWhatsAppAlert` helper. `settingsStore` bumped to v7 with an
  idempotent migration that adds the WhatsApp default block.
- **`TRUST_PROXY_HEADERS` env gate** in `packages/core/core/src/app.py`. When
  set, wraps `wsgi_app` with Werkzeug's `ProxyFix` so deployments behind
  Nginx see real client IPs instead of `127.0.0.1`. Mirrors the same
  gate upstream added in OpenAlgo v2.0.0.7 for `utils/ip_helper.py`.
- **Password-change session invalidation** — new `password_changed_at`
  column on `AuthService.account`, stamped on every successful
  `update_password()`. `decode_token()` rejects any JWT whose `iat`
  predates the stamp (with a 2-second skew tolerance), so leaked
  reset / session tokens cannot survive a password change. Mirrors
  OpenAlgo's v2.0.0.7 hardening.
- **`API_KEY_PEPPER` first-run generation + persist** — new
  `_get_api_key_pepper()` in `packages/core/core/src/app.py` generates a
  64-byte pepper on first boot and persists it to
  `~/.flinttrade/api_key_pepper` (mode 0600), then pushes it into
  `os.environ` before the gateway shim imports OpenAlgo's broker
  modules. Rejects the publicly leaked placeholder values upstream
  flagged in commit `0162ce3a`.

#### Changed

- **`COMPATIBILITY.md`, `PARITY_STATUS.md`, `REFERENCE_MAP.md`,
  `absorption-status.json`** updated to declare v2.0.1.1 parity with
  the 32-broker count (including IIFL Capital), and the new GTT /
  exchange / WhatsApp surfaces. Pin in
  `scripts/setup-test-deps.sh` and `scripts/check_absorption_drift.py`
  bumped from `08c2a553` to `7e48b2e8`.
- **`docs/API.md`, `docs/.../OPENALGO_API.md`, AI skill
  `packages/services/ai/skills/openalgo_api.md`, agent-context template
  `templates/agent-context/CLAUDE.md.template`** gained GTT sections
  and WhatsApp notify documentation.
- **Analyzer docstrings** in `OpenAlgoClient.analyzer_status` /
  `analyzer_toggle` updated to reference upstream's v2.0.0.6
  "sandbox trading" terminology. Route slugs and response keys are
  unchanged so no client-call sites needed touching.
- **`flint.toml`** broker count corrected from 30 → 32 (the previous
  list mistakenly conflated `IIFL` with the legacy `IIFL-XTS`
  designation that upstream never used). Exchange section gained the
  five new entries with `quote_only` markers for the index segments.
- **`.local/external/openalgo/`** fast-forwarded to upstream HEAD
  (`7e48b2e8`, v2.0.1.1). Brings in the silent broker fixes that
  FlintTrade picks up automatically through the in-process adapter
  shim — Kotak Neo payload alignment, Angel defensive `.get()`,
  Paytm / Groww / Kotak index symbol normalisation, ~12 WebSocket
  adapters hardened (batch-queue subscribes, auth-fail short-circuit,
  FD-leak fixes across reconnect).

#### Notes

- **Not absorbed** — OpenAlgo's Remote MCP (OAuth 2.1 + JSON-RPC) is
  orthogonal to FlintTrade's in-process MCP bridge at
  `packages/services/ai/src/mcp_bridge.py`. WhatsApp inbound slash commands are
  intentionally outbound-only on FlintTrade so orders cannot bypass
  the mode guard. The `opengreeks` Rust replacement for `py_vollib`
  is transparent — same response shape, no code change required.
- **Tests** — 370 tests across the touched packages pass. The
  pre-existing `test_bootstrap_is_idempotent` order-dependent flake
  in `packages/integrations/gateway/tests/test_adapter.py` is unchanged.

### Public repo modernisation pass (2026-05-20)

Reshapes the contributor-facing surface of the repository now that it is public AGPL-3.0. No application code, tests, or runtime behaviour touched.

#### Changed

- **README.md** rewritten as a hybrid trader + developer landing page. Top fold opens with a four-screenshot trader pitch, badges, a feature list, and a five-minute Docker quickstart. Second fold opens the developer view with a Mermaid component diagram, a 16-package map, and the tech stack.
- **`docs/`** restructured by audience. New `USER_GUIDE.md` (trader-facing walkthrough), `DEVELOPER_GUIDE.md` (contributor-facing), `API.md` (REST + WebSocket reference), and `docs/README.md` (landing index). `ARCHITECTURE.md` refreshed with current package count, test count, and three Mermaid diagrams. `CI_BUDGET_AND_QUALITY.md` reframed as `CI.md` for contributors.
- **Release notes** moved from `docs/RELEASE_NOTES_v0.5.x.md` into `docs/releases/`.
- **`docs/machine-setup/`** renamed to `docs/setup/`.
- **CONTRIBUTING.md** rewritten end-to-end. Drops references to agent-internal context files; adds Conventional Commits, code style + lint, areas where help is wanted, AGPL-3.0 implications.
- **CODE_OF_CONDUCT.md** updated. Preserves Contributor Covenant v2.1; enforcement contact moved from a personal email to private GitHub Security Advisories; full Enforcement Guidelines section added.
- **SECURITY.md** rewritten. Supported-versions table updated to reflect that only the latest minor receives patches pre-1.0. Reporting moves to GitHub Security Advisories with a documented SLA and safe-harbour policy for researchers.
- **Per-package READMEs** added for all 16 packages, generated from `templates/package-purposes.yml` via `scripts/generate-package-readmes.py`.

#### Added

- `.github/ISSUE_TEMPLATE/bug_report.md`, `feature_request.md`, `question.md`, `config.yml` — three structured templates plus a config that disables blank issues and redirects security to private Advisories.
- `.github/PULL_REQUEST_TEMPLATE.md` — checklist-style template with summary, change type, persona affected, testing, screenshots, and reviewer-friendly checklist.
- `scripts/setup-agent-context.sh` — idempotent scaffolder that copies `templates/agent-context/*.template` to `.local/agent-context/` so contributors using a CLAUDE-aware or AGENTS-aware coding agent can populate their machine-local context after a fresh clone.
- `scripts/generate-package-readmes.py` — generates the 16 per-package READMEs from a YAML data file.
- `templates/agent-context/` — tracked source for the 35 previously-tracked agent-internal context files.
- `templates/package-purposes.yml` — single source of truth for per-package purpose + entry points.
- `docs/superpowers/specs/2026-05-20-public-repo-modernisation-design.md` — the spec governing this pass.
- `docs/superpowers/plans/2026-05-20-public-repo-modernisation.md` — the implementation plan.

#### Removed (from tracking — content preserved on disk)

- 35 agent-internal `.md` files removed from tracking: root `CLAUDE.md`, `AGENTS.md`, `PLAN.md`, plus `packages/<pkg>/CLAUDE.md` and `packages/<pkg>/AGENTS.md` across all 16 packages. Templates preserved under `templates/agent-context/`; machine-local working copies scaffolded under `.local/agent-context/` via `scripts/setup-agent-context.sh`. `.gitignore` updated.
- 5 stale docs archived to `.local/archive/docs-internal/`: `docs/COMPETITIVE_ANALYSIS.md`, `docs/research/` (3 files), `docs/status/` (6 files), `docs/superpowers/plans/2026-04-*` (2 superseded plans), and the full version of `docs/REFERENCES.md`.

#### Process notes

Executed via the `superpowers:brainstorming` → `writing-plans` → `subagent-driven-development` workflow. Four parallel Technical Writer subagents handled README, docs restructure, governance, and `.github/` metadata in parallel. One subagent's summary output was blocked by a content-safety filter on security-policy content; the file content it produced had already landed and the missing summary work was completed inline.

---

## [0.5.2-dev] - 2026-05-20

Tag: `v0.5.2-dev` · Base: `514dcd4` (`v0.5.1`) · Diff: 2 commits ·
Type: SemVer prerelease development snapshot. Latest stable remains `v0.5.1`.

Carry from v0.5.1: Windows sandbox Job Object via pywin32, trusted-mode
subprocess spawn bypass for BacktestLab inner loops, 8 stub backend
endpoints still returning `is_sample_data: true`, glib upstream wait
(tracked in dismissed Dependabot alert).

### Changed
- Release hygiene: normalised annotated tag dates, rebuilt GitHub releases in
  chronological SemVer order, and standardised release-note structure.
- Version metadata: advanced the root project, release-tracked Python packages,
  terminal, and desktop Tauri manifests to `0.5.2-dev`; Chrome extension,
  tick-engine, and the private desktop npm shell remain on independent package
  version tracks.
- Release policy: documented that manifests use bare SemVer, git tags use
  `v<semver>`, prereleases are marked as GitHub prereleases, and published
  release contents stay immutable.

### Notes
- `0.5.2-dev` is a prerelease snapshot, not the stable production target.
  Production users should stay on `v0.5.1` until a stable `v0.5.2` is cut.
- Python package tooling normalises `0.5.2-dev` to `0.5.2.dev0` internally;
  source manifests keep the project SemVer spelling.

---

## [0.5.1] - 2026-05-20

Tag: `v0.5.1` · Base: `2741cad` (v0.5.0) · Diff: 65 commits · CI: green
on `ea64af5` (8,989 Python tests passed, 147 skipped, 0 warnings,
0 ruff errors, 0 open Dependabot alerts). Final post-CI commits reconcile
release metadata, package versions, and lockfile self-version fields.

See `docs/RELEASE_NOTES_v0.5.1.md` for the GA narrative. Highlights:

- 4 Codex stop-gate findings closed (advanced-order mode-safety,
  helper auth-header propagation, JWT-revocation lifecycle,
  rate-limit auto-discovery + fail-closed mode downgrade)
- Sandbox subprocess isolation (closes Codex MEDIUM finding) — hostile
  code can no longer outlive its wall-clock timeout
- Python CI hang root-caused to `PositionWatcher._poll_loop` using
  uninterruptible `time.sleep`; rewritten on `threading.Event.wait`
- CI MemoryError root-caused to `_run_in_thread` calling process-wide
  `setrlimit(RLIMIT_AS)` from a worker thread (poisoned the pytest
  parent at 256 MiB after any in-thread test ran)
- Workspace shallow-copy bug — `_DEFAULT_CONFIG`'s nested dicts were
  shared across `Workspace` instances, letting `ws.set` mutate the
  default; replaced with `copy.deepcopy`
- 2 flaky route tests fixed (`test_pnl_routes::test_series_returns_ok`
  via function-scoped fixture; `test_watchlist_routes::test_list_after_add`
  made self-contained)
- 24 src/ + 286 test/ ruff errors cleared (renames, unused imports,
  E402 fixes, TYPE_CHECKING forward refs)
- 49 CI warnings → 0 (datetime.utcnow, tar.extractall PEP 706, JWT
  HMAC key length, numpy divide-by-zero in corrcoef, AsyncMock coro
  leaks, huggingface_hub filter)
- CI infra: `actions/setup-python@v5→v6`, `actions/setup-node@v4→v5`,
  `--timeout-method=thread` added to pytest, vitest `pool=forks` to
  unblock widget tests, radix-ui umbrella unwound for ~40× module-graph
  reduction
- Per-package versions bumped 0.5.0 → 0.5.1 across 12 Python packages
  + terminal + desktop/src-tauri

---

### Detailed implementation notes

### Sandbox hardening + Vitest OOM root-cause fix (2026-05-19/20)

#### Sandbox subprocess isolation (closes Codex MEDIUM finding)

The sandbox executor previously ran user-uploaded strategy code via `exec()` inside a daemon `threading.Thread` with a `threading.Timer` for timeout. When a strategy hit `while True: pass`, the timer fired and the result was marked `timed_out=True`, but the daemon thread kept running until the parent process exited. CPython has no thread-kill primitive, so any hostile strategy could pin a CPU core for the lifetime of the FlintTrade backend.

- **New** `packages/services/engine/src/_sandbox_child.py` — child-process entry point. Reads a pickled payload from stdin, runs the strategy in the same in-process sandbox the parent would have used, and emits a length-prefixed JSON result frame to stdout. JSON-only on the parent-facing channel — the parent NEVER `pickle.loads` from the child, so a hostile child cannot inject a `__reduce__` payload into the parent.
- **Refactored** `SandboxExecutor.run` — new `use_subprocess=True` default. Spawns `python -m packages.engine.src._sandbox_child` with stdin/stdout/stderr pipes, sends the payload, waits with the wall-clock cap, and on timeout calls `proc.kill()` (`TerminateProcess` on Windows, `SIGKILL` on POSIX). Hostile strategies can no longer outlive the timeout window.
- **Legacy in-thread path** preserved as `_run_in_thread`, accessible via `use_subprocess=False`. Faster (no spawn overhead) but cannot terminate hostile code — only for trusted callers (in-house template engine, BacktestLab hot loops where the source has been reviewed).
- **POSIX resource limits** applied inside the child: `RLIMIT_AS` (256 MB), `RLIMIT_CPU`, `RLIMIT_NOFILE` (64), `RLIMIT_FSIZE=0` (strategy can't write any file). Windows Job Object equivalent is a follow-up — wall-clock kill is the only enforcement on Windows pending that work.
- **stdout capped at 1 MiB** inside the child to prevent a hostile strategy from filling the parent's memory with megabytes of garbage print() before crashing.
- **New** `TestSubprocessIsolation` class — 7 tests covering signal round-trip, print round-trip, hard timeout (verified <3s for a 1s cap that the in-thread path can't enforce), AST violation propagation, unpicklable context → clean `ContextSerialisationError`, in-thread opt-in still works, and runtime exceptions return structured failures (not `SandboxCrash`).
- 51/51 sandbox tests pass (44 pre-existing + 7 new).

#### Vitest OOM root cause — radix-ui umbrella unwound

Performance Benchmarker agent traced the persistent `ERR_WORKER_OUT_OF_MEMORY` in `node-widget-tests-1` and `node-widget-tests-3` to the radix-ui umbrella package. All 14 shadcn files in `packages/apps/terminal/src/components/ui/*.tsx` used `import { X } from "radix-ui"`, which is a 74-line index that does `import * as X from "@radix-ui/react-X"` for 40 sub-packages. Vitest's SSR transform cannot tree-shake those, so every test file that touches a shadcn primitive drags ~2,400 modules into its module graph. With `pool: 'threads'` and 4 concurrent workers sharing one process heap, that's ~8 GB resident before any tests even run.

- **Switched pool 'threads' → 'forks'** in `packages/apps/terminal/vite.config.ts`. Each test file now runs in its own child process; OS reclaims the heap on file completion. Context7 confirms this is the documented antidote for jsdom + ESM module-graph memory exhaustion.
- **Unwound the radix-ui umbrella** in all 14 shadcn files. `import { Dialog as DialogPrimitive } from "radix-ui"` → `import * as DialogPrimitive from "@radix-ui/react-dialog"`. Each shadcn primitive now pulls in only its single Radix sub-package (~60 modules) instead of all 40. Same change pattern for `alert-dialog`, `badge`, `button`, `dialog`, `dropdown-menu`, `label`, `popover`, `scroll-area`, `select`, `separator`, `sheet`, `switch`, `tabs`, `tooltip`.
- Targeted widget-tests run: 437/438 pass (was 0/438 with the OOM). The 1 real failure was a stale assertion in `GreeksHeatmapWidget.test.tsx` (sample-data badge is now always visible per the 2026-04 audit) — fixed.
- `tsc --noEmit` clean.

### Post-public-flip Codex audit — CRITICAL + HIGH fixes (2026-05-19)

The "fix everything" sweep after the second Codex audit. Repo is now PUBLIC AGPL-3.0 with unlimited Actions minutes.

#### CRITICAL — JWT lifecycle drift between PIN unlock and UI mode toggle
- `ModeIndicator.tsx:71-93` previously called `/ft-api/v1/auth/pin` and **discarded the returned live-unlocked JWT**, so a stale Practice JWT stayed in `authStore` while the UI displayed Live. Backend `require_live_unlocked` then rejected every live order, and conversely, if the user later switched the UI to Practice the still-valid live-unlocked JWT in memory could place real orders.
- **Fix**:
  - `handleConfirmLive` now parses the PIN response and calls `useAuthStore.updateToken(newToken)` so the in-memory token actually carries `live_mode_unlocked: true`.
  - **New** `POST /v1/auth/mode` backend endpoint accepts `{mode: "practice"}` from a valid Bearer-authenticated caller, mints a new Practice JWT, revokes the original JTI via the shared blocklist, and returns the new token. Upgrades to `live` are explicitly rejected here (400 with a message pointing back at `/v1/auth/pin`).
  - `handleToggle` (live → practice) now POSTs to `/v1/auth/mode`, swaps the new token in via `updateToken`, then flips local UI state. If the call fails the UI surfaces a `role="alert"` error and stays in Live (no silent downgrade-of-display-only).
  - New `authStore.updateToken(token)` action — replaces the JWT in-place while preserving username/expiresAt and resetting activity.
- **Tests** in `test_auth_routes.py::TestModeSwitchEndpoint` lock four invariants: practice-downgrade returns a fresh distinct token, the prior token is revoked (second call with the same Bearer gets 401), upgrading to `live` here is 400, and missing/invalid token is 401. Plus a new `test_pin_response_includes_new_token` regression on the PIN handler.

#### HIGH — frontend↔backend route drift (silent 404s in production)
- `ftApi.analysis.ts:180` was calling `iv_smile`; backend route is `/ivsmile`. Fixed frontend.
- `packages/services/screener/src/payoff_routes.py` blueprint was mounted at `/v1` instead of `/api/v1`, so all `analytics/correlation`, `payoff/*`, and `regime/current` POSTs from `ftApi.analysis.ts` 404'd. Moved to `/api/v1`; test files updated.
- `packages/services/screener/src/earnings_routes.py` had the same `/v1/earnings/` prefix mismatch. Moved to `/api/v1/earnings/`; both `test_earnings_routes.py` and `test_earnings_calendar.py` updated.
- `pnl_symbols_routes.py` only accepted GET. Added POST handler (reads from JSON body) so the route contract matches OpenAlgo's `POST /api/v1/pnl/symbols` — defensive; the actual frontend call goes via Vite's `/api` proxy to OpenAlgo, but a FlintTrade-side caller would now also work.
- `ftApi.backtest.ts` was calling `strategies/uploaded/<id>/{start,stop,logs}` which matched no backend route (404). Engine's `strategy_bp` handles uploaded strategy lifecycle at `/api/v1/strategies/<id>/{start,stop,logs}`. Removed the spurious `/uploaded/` segment from frontend.

#### HIGH — legacy password reset endpoints not rate-limited
- `auth_routes.auth_forgot_password` and `auth_reset_password` lacked rate-limit decorators. Added `@_rate_limit("3 per hour")` and `@_rate_limit("5 per minute")` respectively. OTP-reset paths were already rate-limited; these are defence-in-depth on top of single-use JTI tokens.

#### Duplicate-route audit cleanup (Codex finding #2)
- **Security routes**: removed `/security/{stats,bans,ban,unban}` from `operations_routes.py` — `security_bp` already owns them at `/api/v1/security/*` and registered first, silently shadowing these duplicates. Kept the `/security/settings` GET/POST handlers since `security_bp` doesn't expose those.
- **Strategy routes**: `backtest_routes.py` registered `/strategies`, `/strategies/running`, `/strategies/uploaded`, `/strategies/<name>/start`, `/strategies/<name>/stop` — all of which collided with engine's `strategy_bp` (live strategy lifecycle). Renamed every backtest_bp strategy route to `/backtest/strategies*` so the two surfaces don't fight over Flask's URL dispatcher. Frontend `ftApi.backtest.ts` (`getStrategies`, `getRunningStrategies`, `getUploadedStrategies`, `startStrategy`, `stopStrategy`) updated to match. Tests in `test_backtest_routes.py` updated.

### Orphan API stubs + remaining hook coverage (2026-05-19)

- **`packages/services/screener/src/sample_data_routes.py`** added — eight Flask routes that previously 404'd in production now return `is_sample_data: true` placeholders matching the frontend TypeScript interfaces:
  - `GET /api/v1/etf/screener` — ETF screener rows (NIFTYBEES, GOLDBEES, BANKBEES)
  - `GET /api/v1/sectors/rotation` — RRG-quadrant-tagged sector momentum
  - `GET /api/v1/analytics/risk-return` — annualised return/volatility scatter
  - `GET /api/v1/crypto/funding_rates` — BTC/ETH perp funding rate snapshot
  - `GET /api/v1/global/indices` — 9 indices across India/US/Europe/Asia regions
  - `GET /api/v1/screener/shareholding?symbol=` — promoter/FII/DII/public/government percentages summing to ~100, financials = null placeholders
  - `GET /api/v1/screener/sector-constituents?sector=` — 4-stock RRG drill-down with tail points
  - `GET /api/v1/screener/lot-size?symbol=&exchange=` — real lookup against a 15-symbol F&O lot-size table (NIFTY=75, BANKNIFTY=30, FINNIFTY=65, USDINR=1000, etc.); unknown symbols return `0` so the ScalperWidget falls back to its built-in config rather than getting an error.
- The blueprint registers in `core.app` alongside `analysis_bp`. Widgets that already check `is_sample_data` (EtfScreenerTab, RiskReturnTab, SectorRotationTab, ShareholdingTab, PortfolioRRGTab, etc.) now render their "Demo" badge instead of an error panel. `retry: false` is no longer strictly necessary on PortfolioRRGTab but is kept as a safety net against accidental regressions.
- **`packages/services/screener/tests/test_sample_data_routes.py`** added — 12 tests confirm every route returns HTTP 200, `is_sample_data: true`, the response shape matches the frontend interface, and query params (symbol/sector/exchange) echo through correctly. Lot-size table values are pinned: NIFTY=75, BANKNIFTY=30, USDINR=1000. A future PR replacing a stub with a real implementation MUST keep these assertions passing.

### Additional hook coverage (2026-05-19)

- **`packages/apps/terminal/src/hooks/__tests__/useOrdersPositionsMargin.test.ts`** added — 12 tests covering the three remaining REST-query hooks. `useOrders` and `usePositions` get URL-called, response-shape, and error-state coverage. `useMargin` gets the load-bearing conditional `enabled` gate locked end-to-end: fires only when symbol non-empty AND exchange non-empty AND qty>0 AND caller's `enabled` is true. Four no-fetch branches + one positive fetch branch + one success-shape assertion = full coverage of the gate logic.

### Critical safety — advanced order mode-guard (2026-05-19)

- **Codex stop-gate finding #4 closed**: engine `order_bp` routes (basket, split, options-strategy) and `bracket_bp.place_bracket` were carrying only `@require_non_explore`, which blocks explore-mode but never checks the `live_mode_unlocked` JWT claim. These four routes execute orders via FT's own executors (`BasketOrderExecutor`, `SplitOrderExecutor`, `OptionsStrategyBuilder`, `BracketOrderService`) that call OpenAlgo *directly* — they don't re-enter the mode-aware `core.order_routes` proxy, so the proxy's safety fan-out never protects them. Net effect before this fix: a live-mode user without a PIN-verified JWT could place basket/split/options-strategy/bracket orders that hit the broker.
- **Fix**: new `require_live_unlocked` decorator in `packages/services/engine/src/mode_guard.py` reproduces the full `core._dispatch_order` semantics at the route boundary — explore→403 (`mode_blocked`), practice→403 (`practice_unsupported` — no sandbox executor parity yet), live without `live_mode_unlocked` claim→403 (`live_locked`), live unlocked→pass, missing JWT→401 (`auth_required`), unknown mode→400 (`mode_invalid`). `TESTING=True` bypass preserved so unit tests keep working.
- **Applied to** `place_basket`, `place_split`, `place_options_strategy`, `place_bracket` (4 routes). `require_non_explore` is retained for strategy-lifecycle routes whose downstream orders flow back through the mode-aware `orders_bp` and therefore inherit its safety stack.
- **Tests**: new `packages/services/engine/tests/test_mode_guard.py` (17 cases) covers both decorators end-to-end with real JWT minting (`TESTING=False`), explore/practice/live × locked/unlocked, missing-token, invalid-token, and unknown-mode paths. Existing route tests stay green via the TESTING-mode bypass.
- **Frontend collateral**: `vi.stubEnv("DEV", "true")` → `vi.stubEnv("DEV", true)` (vitest 3.2.4 requires `boolean` for DEV). `PortfolioRRGTab.tsx` query for `getSectorConstituents` gains `retry: false` to stop the orphan-API retry storm until the backend route is built.
- **Codex stop-gate finding closed inside the same session**: Codex's review of the first iteration flagged that `placeBracketOrder` (and any other call going through `ftApi.helpers.post`) would now hit `auth_required: 401` because the bare `post()` helper only sent `Content-Type`. Fix: `ftApi.helpers.{post,get,put,del}` all route through a new `buildHeaders()` that imperatively reads `useConnectionStore.getState().apiKey` and `useAuthStore.getState().token`, attaching `X-API-Key` and `Authorization: Bearer <jwt>` whenever they're populated. Three new tests in `ftApi.helpers.test.ts` lock the contract (populated headers, GET without Content-Type, omitted headers when stores are empty). Brings the helper layer to parity with `api.postOrder()`, so basket/split/options-strategy/bracket all carry the JWT the new server-side guard now requires.

### CI budget + quality plan (2026-05-19)

- **`test.yml` cost reduced ~64%** per push (effective minute weight): macOS and Windows runners removed from the always-on matrix and moved to a new weekly `nightly-cross-platform.yml` (Sunday 03:00 UTC). macOS billed 10× and Windows 2× the Linux rate, both with `continue-on-error: true` so they never gated anything — pure budget burn.
- **`test.yml` paths-ignore** added — doc-only commits (`*.md`, `docs/**`, `.local/**`, `NOTICE`, `LICENSE`, `.gitignore`, `.gitattributes`, `.editorconfig`, sibling Claude/status workflow files, issue templates) skip the entire matrix.
- **`test.yml` concurrency cancel** added — back-to-back pushes only run the latest, no more amplification.
- **`test.yml` draft-PR guard** added — every job gates on `github.event.pull_request.draft != true`, so iterative draft pushes cost nothing.
- **`claude-code-review.yml`** trimmed: removed `synchronize` trigger (was firing on every PR commit — 5–10× per multi-commit PR), added paths-ignore and concurrency cancel, added draft-PR guard.
- **`status-report.yml`** repaired: dropped `submodules: recursive` (submodules were detached in `3da42e4`); fixed `scripts/audit_repos.py` to accept both legacy dict and current list shapes of `absorption-status.json` (was crashing every weekly run with `AttributeError: 'list' object has no attribute 'get'`).
- **`docs/CI_BUDGET_AND_QUALITY.md`** added — the contract: hosted-runner cost model, per-commit checklist, workflow inventory, defence-in-depth layers, runbook for bill spikes. Any future workflow change must update this doc in the same commit.

### Post-v0.5.0 GA hardening (commits since `2741cad`, 2026-04-19 → 2026-05-19)

#### Changed
- **Infra:** OpenAlgo + OpenClaw detached from git submodules (commit `3da42e4`). They are now external services FlintTrade talks to over HTTP/WS; contributors can clone local-dev copies into `.local/external/{openalgo,openclaw}/` via `scripts/setup-test-deps.sh` (gitignored, not shipped). The legacy `infra/openalgo/` path remains as a fallback in `packages/integrations/gateway/src/adapter.py:_resolve_openalgo_root()` for older checkouts.
- **Ditto:** `algomirror_bridge.py` and its tests dropped (commit `ce5f6df`). AlgoMirror's multi-account mirroring patterns are fully absorbed in-process by `packages/services/ditto/` (`PositionMirror`, `TrailingSLManager`, `MarginCalculator`, `RiskManager`). There is no live AlgoMirror integration; the upstream repo is no longer tracked.
- **Compat:** `docs/COMPATIBILITY.md` refocused on min + latest tested versions (drift-tracking removed, commit `fa59ef7`).
- **Test infra (commits `268e8e7`, `3826662`, `84637f1`, `879b3da`):** Batch test-suite cleanup — real bug fixed in routes, dead tests removed, stale fixtures refreshed, parallel-test dependencies registered, isolated workspace per worker, custom markers (`unit`, `integration`, `slow`) registered with `--strict-markers`.
- **Setup wizard (commit `41d319f`):** End-to-end account creation flow with escape hatches and `/v1/test-connection` backend-proxy that avoids OpenAlgo CORS.
- **Reference repos (commit `12bea2b`):** 15 redundant repo clones deleted; absorption tracking reconciled (`.local/reference/REFERENCE_MAP.md` now ~230 repos).
- **Backend boot (commit `cd2d374`):** structlog single pipeline, ANSI off, Waitress (production WSGI server), three-state health check.
- **Privacy scrub (commit `c563bd5`):** Removed personal identifiers and infrastructure from tracked files.
- **Audit passes (commits `ab0b595`, `e61b7a8`, `bb51149`, `025a552`):** Four full-repo audit sweeps — security, privacy, WCAG, state boundaries, persistence, tests, a11y, CI matrix, hook tests, screener tests, zero `any` types.

#### Tooling
- `.codex/` gitignored alongside other agent tool caches (commit `aa7b387`).
- Codex CLI integration verified and stop-time review gate enabled.

#### Verified metrics (2026-05-19)
- Total tests collected: **~12,062** (9,089 pytest + ~2,973 vitest).
- Test file counts: 313 Python + 264 vitest.
- Widget count: 82 directories under `packages/apps/terminal/src/widgets/` (22 trading + 38 analysis + 22 utility); registry has 83 entries (`chartgrid` reuses the Chart folder).
- Tool count: 7 (`BacktestLab`, `FlowBuilder`, `MarketIntelligence`, `PnLDashboard`, `Settings`, `StrategyBuilder`, `TradeJournal`).
- Routes: 12 public + DEV `/admin` + `*` 404 catch-all.
- Workspace presets: 13 (`packages/apps/terminal/src/layout/workspacePresets.ts`).
- Backtest strategy templates: 94 (`packages/services/backtest/src/strategies/`); plus 2 live-engine strategies in `packages/services/engine/src/strategies/`.
- AI skill markdown files: 30 (`packages/services/ai/skills/`).
- CI jobs: 9 parallel GitHub Actions jobs.

---

## [0.5.0] - 2026-04-19

Tag: `v0.5.0` · Base: `v0.5.0-beta` (`a0c0f29`) · Stable OpenAlgo
v2.0.0.4 parity baseline.

### Added — OpenAlgo v2.0.0.4 Parity (Waves 1-5, 1,499 tests)
- Wave 1 — Scanner, cron, error log, seasonality, security/session tooling (253 tests)
- Wave 2 — Analytics + orders + infra: GEX, IV smile, vol surface, OI profile, straddle P&L, basket/split orders, traffic/latency/event-bus (347 tests)
- Wave 3 — Security + smart routing: TOTP 2FA for FlintTrade login, smart order router, qty-freeze controls (73 tests)
- Wave 4 — Action center, WS proxy, historify, plugin/cache layer, IP whitelist, CSP, health monitor (449 tests)
- Wave 5 — 9 parity endpoints, ops tools, strategy hot-reload, frontend parity, voice + deploy (314 tests)

### Security
- TOTP encryption passphrase now derives from a per-install random secret at `~/.flinttrade/totp_install_key` when `FLINTTRADE_TOTP_KEY` is unset — eliminates the shared default key
- TradingView webhook signature verification is fail-closed when a secret is configured (missing header now rejects)
- Flow builder HTTP node blocks non-public URLs (loopback, RFC1918, link-local, cloud metadata 169.254.169.254) and disables redirects
- Engine order/bracket/strategy-start routes now enforce JWT mode claim server-side — explore-mode callers receive HTTP 403

### Chores
- Removed personal identifiers from sample data and test fixtures (replaced with generic placeholders + RFC 5737 IPs)
- Replaced seven realistic Indian client names + broker names in `operations_routes.py` sample accounts with anonymous demo tokens
- Bumped `packages/apps/terminal/package.json` to `0.5.0` to match the monorepo version

### Added — Features (Waves 1-9)
- Signals pipeline: real-time signal generation, scoring, and routing to order engine (signal_pipeline.py + signal_routes.py + useSignals hook)
- MCX commodity support: symbol normalisation, market hours, lot sizes (mcxLots.ts + 46 tests)
- Mutual Funds module: MutualFundTab in /invest with AMFI NAV lookup, SIP calculator, fund comparison (mf_routes.py)
- WhatsApp notification channel alongside existing Telegram bot (whatsapp_alerts.py + whatsapp_routes.py)
- ExpiryTrack: historical expired options tracking with expiry_tracker.py + routes
- Pine Script editor: browser-based Pine-to-Python transpiler (PineEditor.tsx + compile endpoint)
- Chrome extension: quick order entry and watchlist from any browser tab (packages/chrome-extension/)
- Tauri desktop shell: native window wrapper for the React terminal (packages/desktop/)
- Multi-user support: role-based access (admin/trader/viewer) with JWT claims (user_manager.py + user_routes.py)
- IPO Tracker: ipo_routes.py + ipo_calendar.json + IpoTab.tsx with NSE data
- FinRL reinforcement learning: rl_environment.py + rl_trainer.py + rl_features.py
- OpenClaw bridge: openclaw_bridge.py in both ai and automation packages + routes

### Added — Features (Waves 10-23)
- Multi-agent AI team: MiroFish + TradingAgents architecture (multi_agent.py)
- Risk debate: multi-perspective risk assessment engine (risk_debate.py)
- Ensemble selector: strategy ensemble voting system (ensemble_selector.py)
- Hyperopt strategy optimiser: hyperparameter optimisation for strategies (hyperopt_strategy.py)
- Fundamental screener: Screener.in integration for fundamental analysis (fundamental_screener.py)
- FII/DII tracker: NSE scraper for institutional flow data (fii_dii.py)
- RRG calculator: Relative Rotation Graph computation + SectorMap RRG view (rrg.py + useRRGData.ts)
- Portfolio backtester: VectorBT patterns for portfolio-level backtesting (vectorbt_runner.py)
- Bracket orders: bracket order support with strategy state persistence (bracket_order.py)
- Order flow inference: trade-side inference from tick data (orderflow_inference.py)
- Alert trigger log: persistent alert audit trail for compliance (alert_trigger_log.py)
- Activity log: comprehensive SEBI-compliant user action logging (activity_log.py)

### Added — Wiring & Mode System
- Server-side order safety proxy (order_routes.py) — all orders route through FlintTrade backend
- Unified mode system: Explore (sample data) / Practice (paper trading) / Live (real orders)
- useModeData hook: components receive live, mock, or paper data based on active mode
- MockDataEngine: deterministic sample data generator for Explore mode
- CSRF token middleware on all state-mutating endpoints
- Mode reset on disconnect: reverts to Explore when broker session expires
- Persona-aware setup wizard: interest matrix seeds default workspace and visible routes
- ModeIndicator component in TopBar with Practice-to-Live toggle
- Practice section in Settings with SandboxControls
- DemoChoice overlay on first /explore visit
- GoalTab wired into /invest route
- JWT secret persistence across server restarts
- SEBI disclaimer banner in practice mode

### Added — Infrastructure
- SSE log streaming: /ft-api/v1/logs/stream endpoint for real-time execution log tailing
- flask-mail integration for password reset and alert emails
- API key separation: distinct keys for OpenAlgo vs FlintTrade backend
- Docker production config: multi-stage Dockerfile with uv (10x faster pip), tini init, non-root user, start.sh
- Nginx hardening: rate limiting, CSP headers, HSTS, X-Frame-Options
- Security headers middleware: CSP, X-Frame-Options, HSTS, X-Content-Type-Options on all responses
- WebSocket handler upgrade: mode-specific subscribe, batch subscribe, reference counting
- All 3 git submodules synced (openalgo, algomirror, openclaw) — historical: submodules were later detached in commit `3da42e4` (2026-04-30); see Post-v0.5.0 section below

### Added — Features (Wave 24 — Absorption)
- CommandPalette (Ctrl+K): global command search with 51 commands, fuzzy search, recent history, keyboard navigation (absorbed from openalgo-chart)
- Price Alerts widget: armed/triggered/expired states, LTP polling, condition types (above/below/crosses), localStorage persistence (31st widget)
- DrawingToolbar: vertical 20-tool sidebar with 7 groups, favourites, popover selection, lock/hide/clear (absorbed from openalgo-chart)
- LegBuilder: multi-leg option strategy builder (Straddle/Strangle/Spread/Condor/Butterfly/Custom), payoff calculation, basket order execution (absorbed from openalgo-chart)
- FlowBuilder rewrite: @xyflow/react v12, Zustand store, 54 node types across 8 categories, node palette, config panel, execution log (absorbed from openalgo-flow)
- ETF Screener tab: filterable TanStack Table with 12 sortable columns, category pills (absorbed from etftracker)
- Sector Rotation tab: treemap heatmap + momentum scoreboard (absorbed from etftracker)
- Risk-Return tab: SVG scatter plot (volatility vs return, Sharpe sizing) with stats cards (absorbed from etftracker)
- Correlation Matrix tab: HTML heatmap + market regime indicator (Risk-On/Off/Rotation) + VIX/DXY badges (absorbed from etftracker)
- RouteBanner: dismissible contextual hints on /trade, /invest, /lab, /settings
- SpotlightTour: wired to /ai and /automate routes for beginners
- PositionTracker: thread-safe, DuckDB-persisted, R-multiple accounting, MTM square-off (absorbed from nifty-trading-railway)
- StateManager: 8-state strategy lifecycle with per-strategy locks, audit trail (absorbed from nifty-trading-railway)
- SwingDetector: watch-based confirmation, multi-symbol support, callbacks (absorbed from nifty-trading-railway)
- 5 new repos cloned: n8n-io/n8n, marketcalls/Vibe-Trading, openbull, upstox-api-docs, zerodha-api-docs
- absorption-status.json: 233 repos tracked (was 80)
- data-tour-target attributes added to WatchlistWidget, AIRoute sections, AutomateRoute sections
- 4 new ftApi endpoints: getEtfScreener, getSectorRotation, getRiskReturn, getCorrelationMatrix

### Added — Tests
- LearnRoute tests (3): heading, sidebar sections, default tab content
- InvestRoute tests (3): heading, tab navigation, default Dashboard tab
- AutomateRoute tests (3): heading, section tabs, sidebar rendering
- DittoRoute tests (10): header, tabs, accounts table, mirror tab, risk tab, error handling
- MCX lot sizes (46 tests), useSignals hook tests, security headers tests
- AlertsWidget tests (20), LegBuilder tests (31), FlowBuilder tests (5), ETF analytics tests (22)
- Python engine tests: position_tracker (46), state_manager (34), swing_detector (37)
- Total terminal tests: ~2,500 (Vitest, 227+ files) | Python: ~6,500 (pytest) = ~9,000 total (snapshot at Wave 24; current ~12,062 — see Post-v0.5.0 section)

### Added — Features (Wave 25 — Engine + Analytics)
- Backtest engine: event-driven BacktestEngine with MARKET/LIMIT/STOP/STOP_LIMIT orders, slippage, commission (absorbed from trading-strategies-openalgo)
- Indian tax calculator: STT, stamp duty, exchange charges, SEBI fee, GST — all Decimal precision
- BaseBacktestStrategy: abstract on_bar/on_tick, enter_long/short, Signal enum, indicator proxy
- Metrics: Sharpe, Sortino, CAGR, max drawdown (amount + duration), win rate, profit factor, Calmar, VaR/CVaR, streaming Welford
- 5 streaming indicators: MACD, Bollinger Bands, Supertrend, VWAP, Cumulative Delta (absorbed from pyindicators)
- 2 batch volume functions: cumulative_delta, volume_profile with Point of Control (absorbed from pyindicators)
- Portfolio Greeks: IV percentile/rank, P&L attribution (Taylor expansion), portfolio PCR, enhanced max pain (absorbed from openalgo-portfoliogreeks)
- OI Overlay on ChartWidget: histogram pane showing net CE-PE OI imbalance
- System Health widget (32nd widget): connections, performance, security, alerts, auto-refresh

### Added — Features (Wave 26 — Strategies + AI)
- MTM straddle strategies: MTMStraddleStrategy, TrailingStopStraddle, CombinedPremiumStraddle, MTMMonitor (absorbed from algo_trading_strategies_india)
- RAG pipeline: document loader, text chunker, embedding provider (sentence-transformers/OpenAI), ChromaDB vector store (absorbed from openalgo-chatbot)
- ML advisor: LightGBM classifier (BUY/HOLD/SELL) with 11 technical features, model persistence (absorbed from openadvisor)

### Added — Features (Wave 27 — Charts + Retraining)
- Three-Panel Chart widget (33rd widget): CE|Index|PE synchronised LWC v5 charts with auto ATM strike
- IndicatorSettingsModal: two-column modal with colour picker, line style, period inputs, draft state
- Auto-retraining loop: continuous ML model retraining (daily), drift detection (KS test), atomic model swap
- Retrain API: GET /retrain/status, POST /retrain/trigger, GET /retrain/history

### Added — Features (Wave 28 — Strategies + Journal + Broker)
- 29 backtest strategy templates across 5 categories: trend following (9), mean reversion (6), momentum (6), volatility (4), composite (4) (absorbed from AlgoTrading)
- STRATEGY_REGISTRY with name-based lookup, all extending BaseBacktestStrategy
- Trade Journal: DuckDB-backed CRUD with emotions, quality ratings, tags, auto-computed P&L, CSV export, tradebook import
- Journal API: 7 endpoints under /ft-api/v1/journal/
- BrokerInterface Protocol: 10 standard operations, 9 Pydantic models, BrokerRegistry, OpenAlgoBroker implementation (absorbed from openbull)

### Added — Features (Wave 29 — Skills + Swarm + Historical)
- SkillRegistry: markdown skills with YAML frontmatter, on-demand loading, fuzzy search (absorbed from Vibe-Trading)
- 10 starter AI skills: OpenAlgo API, option chain, straddle, risk, indicators, backtest, market hours, order safety, FII/DII, Greeks
- SwarmExecutor: async DAG task executor with topological layering, cycle detection, event emission (absorbed from Vibe-Trading)
- DataProvider Protocol: OpenAlgo, OpenChart (NSE free), yfinance (MCX) with fallback chain (absorbed from historify + openchart)
- OHLCVNormaliser: IST conversion, column aliasing, intraday cutoff, data validation
- HistoricalCache: DuckDB-backed, TTL freshness, incremental updates, batch fetch

### Added — Features (Waves 49-53 — Quality + Skills)
- WidgetPicker search: filter 80 widgets by name/description, highlight matches, live count
- 6 new workspace presets (12 total): Options Analysis, Sector View, Order Automation, Portfolio Manager, Market Overview, Quick Scalper
- PermutationTester: statistical significance testing, Monte Carlo equity curve confidence bands
- WalkForwardAnalyser: rolling/expanding window OOS validation, 6 metrics, robustness check
- KeyboardShortcutsDialog: ? key opens reference, 15 shortcuts, platform-aware labels, searchable
- Widget descriptions: all 80 widgets have one-line description in picker
- Preset management API: CRUD endpoints /ft-api/v1/presets/ with fork, export, import
- PresetSection in Settings: card grid, create/edit/fork/delete presets, widget selector
- 15 new AI skills (30 total): scalping, bracket orders, expiry day, algo deployment, India macro,
  candlestick patterns, support/resistance, intermarket, iron condor, earnings options, margin
  optimisation, Greeks guide, trading psychology, drawdown management, portfolio hedging
- conftest.py for backtest-engine: eliminated sys.path hacks from 20 test files
- CI split: 3 parallel vitest jobs (core + trading/utility + analysis/routes/tools)

### Added — Widgets (Waves 39-48 — 80 Widget Milestone)
- CurrencyConverterWidget, EarningsCalendarWidget, GlobalIndicesWidget, StrategyTemplatesWidget, AuditTrailWidget (Wave 39)
- PivotPointsWidget, EconomicCalendarWidget, PortfolioAllocationWidget, OrderBookReplayWidget (Wave 40)
- MarketBreadthWidget, QuickTradeWidget, VolatilityConeWidget, ProfitTargetWidget (Wave 41)
- HeatCalendarWidget, VWAPBandsWidget, CorrelationPairsWidget, MultiTimeframeWidget (Wave 42)
- PCRTrendWidget, TradePerformanceWidget, InstrumentCompareWidget, SpreadViewWidget (Wave 43)
- GreeksHeatmapWidget, MarketSummaryWidget, GapAnalysisWidget, SessionStatsWidget (Wave 44)
- ImpliedMoveWidget, RiskDashboardWidget, OptionsFlowWidget, TradeLogWidget (Wave 45)
- MicrostructureWidget, ExpiryCountdownWidget, PositionSizingWidget, CorrelationMatrixWidget (Wave 46)
- IVSkewWidget, MarketClockWidget, StrategyMonitorWidget, NetPositionWidget (Wave 47)
- TradeIdeaWidget, SectorPerformanceWidget, TickSpeedWidget, OrderLadderWidget (Wave 48)
- Total: 80 widgets across 3 categories (22 Trading + 36 Analysis + 22 Utility)

### Added — Python Backends (Waves 39-42)
- Earnings calendar: NIFTY 50 quarterly events, sample data generator, 3 Flask endpoints
- Enhanced audit routes: paginated log, large CSV export, action stats
- Pivot calculator: 5 methods (Standard/Fibonacci/Woodie/Camarilla/DeMark)
- Economic calendar: 26 event templates across 6 countries, cadence-based generation
- Market breadth: McClellan Oscillator, breadth thrust, A/D line, sample data
- Volatility cone: rolling HV percentile bands, IV percentile scoring
- VWAP bands calculator: session-aware, single-pass running variance
- Pair correlation: 5 preset Indian pairs, z-score classification
- Multi-timeframe analyser: RSI/MACD/EMA per-TF confluence scoring

### Added — Features (Wave 49 — Quality of Life)
- WidgetPicker search: filter 80 widgets by name, highlight matches, live count
- 6 new workspace presets (12 total): Options Analysis, Sector View, Order Automation, Portfolio Manager, Market Overview, Quick Scalper
- PermutationTester: statistical significance testing, Monte Carlo equity curve bands
- WalkForwardAnalyser: rolling/expanding window OOS validation, robustness check

### Fixed — CI (Wave 48)
- Node heap increased to 8GB (NODE_OPTIONS=--max-old-space-size=8192) for 227+ test files

### Fixed — Accessibility (Wave 39)
- 13 WCAG 2.1 AA issues fixed across 11 widgets (3 critical, 4 serious, 3 moderate)
- CommandPalette: aria-activedescendant ID linkage
- NotificationCentre: focus trap implementation
- DrawingToolbar: keyboard-operable popover items
- AlertsWidget: proper tab ARIA pattern
- TradeCopierWidget: shadcn/ui components, aria-labels
- LegBuilder: aria-pressed on BUY/SELL toggle

### Added — Features (Waves 33-35 — Deep Analytics)
- FlowBuilder: n8n-style NodeTypeDescriptor metadata, expression evaluator (safe {{variable}} interpolation), ExpressionInput with token highlighting and autocomplete
- Portfolio optimiser: Markowitz, min variance, risk parity, equal weight, Black-Litterman, efficient frontier (scipy SLSQP)
- Webhook receiver: HMAC-SHA256 verification, TradingView/ChartInk/custom parsers, async dispatch, rate limiter
- Options payoff engine: expiry/pre-expiry P&L curves, Black-Scholes Greeks, Monte Carlo POP (10k paths)
- Regime detector: 7-regime classification from VIX, returns, A/D, FII flow, breadth
- Correlation engine: pairwise Pearson, rolling correlation, regime-tagged matrix
- PayoffChart: pure SVG P&L visualisation with split green/red segments, hover tooltip
- Order analytics: fill rate, slippage (bps), execution speed (p50/p95/p99), by-hour/by-symbol
- Strategy comparator: side-by-side metrics, rankings, weighted scoring, optimal blend weights
- PositionHeatMapWidget (34th widget): squarified treemap of portfolio exposure

### Added — Features (Wave 31 — AI Refinements)
- MemoryManager: compound scoring (importance × recency_decay × relevance), exponential time decay, access boost, category defaults, pruning (absorbed from FinMem)
- TradeReflector: batch analysis every N trades, win/loss pattern extraction, rule-based + LLM paths (absorbed from LLM-TradeBot)
- NewsScheduler: pre-market 07:00, post-market 16:30, intraday 15min polls (IST), TTL dedup, async callbacks (absorbed from FinSights)

### Added — Features (Wave 32 — Simulation)
- SimulationEngine: multi-phase simulation wrapping BacktestEngine with 7 phases (warmup → crisis → recovery)
- MarketEvent injection: price shocks, volume spikes, volatility expansion, gaps
- 6 pre-built scenarios: flash crash, trend reversal, range bound, gap up, volatility expansion, liquidity crisis
- StressTestRunner: run strategy against all scenarios, generate survival report (absorbed from Stockagent)

### Added — Features (Wave 30 — Skill Variants)
- useSkillContent hook: returns skill-level-appropriate widgets (7/18/33), tools, tooltips, presets
- WidgetPicker + ToolsDropdown: filter by skill level via allowedIds props
- SkillBadge in TopBar showing current level with link to Settings

### Added — Waves 24-63 (2026-04-08 to 2026-04-13)
- Gap audit: 227 repos x 6 agents — 82 items addressed across 5 waves (59-63)
- Engine: OvertradingGuard, MTM circuit breaker, position reconciliation, RiskEvent, sandbox executor
- AI: regime detector, structured sentiment, swarm presets, async agents, DI drift, RAG filter
- Backtest: pairs trading, walk-forward, robustness testing, portfolio optimisers, tearsheet
- Terminal: ChartGrid, Footprint, DOM Heatmap, ETF screener, shareholding, sentiment panels
- Desktop: full Rust backend (keychain, auto-logout, webhook server)
- tick-engine: RaptorBT absorption (pairs/options/spreads, Monte Carlo, Rayon batch)
- Infra: Docker multi-arch, Makefile Windows, CI macOS+Windows, bash /tmp fix
- CI split into 5 parallel jobs (python-tests, node-core-tests, node-widget-tests-1, node-widget-tests-2, secrets-check)
- Node heap increased to 8 GB, singleFork mode to prevent OOM on CI runners
- 9 large files split into focused modules, shadcn/ui Select migration across terminal
- Production-readiness pass: imports, accessibility, types, lint across all packages

### Added — Flint Suite Redesign (2026-04-14)
- Phase 1: Glass Adaptive design system — 16 CSS vars, 13 Tailwind v4 utilities, 6 Aceternity components (FloatingDock, MovingBorder, FocusCards, InfiniteMovingCards, TextGenerateEffect, AnimatedTabs)
- Phase 1: TopBarV2 (38 px glass chrome), DockSidebar (macOS dock with drag reorder), BentoGrid engine, HomeRoute (12 bento cards), StatusBar
- Phase 2: Unified Search — 4-tab Ctrl+K command palette (Symbols with live prices, Commands, Widgets, Ask AI). Prefix routing: / commands, # widgets, @ai ask
- Phase 4: Ticker system — store persistence (tickerMode, tickerSymbols, tickerSpeed), TickerSettings UI with mode selector, speed slider, symbol editor with autocomplete
- Phase 5: Glass polish across 6 routes (Lab, AI, Admin, Automate, Settings, Ditto)
- Phase 6: pyproject.toml for all 12 Python packages with hatchling backend, uv workspace config, wheel source mappings for pip install
- Phase 7: Crawl4AI integration client — scrape(), extract_css(), extract_llm() with SSRF protection

### Fixed — Full Codebase Audit (2026-04-14)
- Security: SSRF URL validation in Crawl4AI, sample data VPN IPs replaced with RFC 5737
- Engine: replaced silent except:pass with logger.exception() in strategy_runner, position_tracker, state_manager
- Core: deferred engine imports in app.py to break circular dependency
- API: getMultiQuotes type corrected, normaliseMultiQuotes helper added
- WebSocket: mode 4 (depth v2) handler, reconnectCount + tickAgeMs diagnostics
- Accessibility: OrderPad form errors linked via aria-describedby, Settings arrow-key nav, AutomateRoute ARIA roles, TickerMarquee sr-only updates, DockSidebar keyboard access, StatusBar contrast + touch targets, loading state announcements, platform-detect Ctrl+K
- Logging: structlog bridge for all 250+ modules, 5 missing loggers added, proactive Telegram alert methods
- SQL: parameterised LIMIT binding, column allowlist in trade_journal
- Imports: intra-package relative imports across all 12 Python packages, gateway bare imports fixed
- Types: unified Raw* types (rawApi.ts), ESLint config, light mode contrast darkened

### Fixed — Audit Waves 56-57 (2026-04-12)
- Wave 56: 14 audit findings fixed — JWT-based mode detection, activity log timestamp handling, webhook behaviour changes
- Wave 57: timer cleanups, npm audit fixes, security fixes, performance guards

### Removed
- TopBar.tsx (804 LOC dead code, replaced by TopBarV2)

### Fixed — Code Review (Wave 24)
- AlertsWidget: fixed stale ltpMap closure causing poll data races (functional setLtpMap update)
- LegBuilder: fixed mixed UTC/local date accessors in normaliseExpiry (getUTCDate for consistent expiry symbols)
- CommandPalette: removed `as unknown as string` type lie on JSX prop
- flowStore: added structural validation before JSON.parse cast (prevents corrupt localStorage crash)
- PositionTracker: wrapped read methods and close_all in thread lock (TOCTOU fix)
- StateManager: added cache_lock for all_snapshots/strategies_in_state iteration safety
- PositionTracker + StateManager: added db_lock for DuckDB connection thread safety
- SwingDetector: all_swings now returns deepcopy (prevents mutation by _update_extreme)
- tourDefinitions: fixed target mismatch (orderpad -> order-pad)
- Ruff: removed unused imports in position_tracker.py and state_manager.py

### Fixed — Security
- JWT revocation: token blacklist on logout and password change
- Admin role enforcement: /admin route and admin API endpoints require admin JWT claim
- Scanner subprocess: additional forbidden builtins (__import__, exec, eval, compile)
- SQL injection fix: parameterised queries in DuckDB historical pipeline
- Strategy hardening: AST validation rejects os/sys/subprocess imports before execution

### Fixed — API Contracts
- 15+ endpoint request/response shapes aligned with OpenAlgo 2.0 spec
- OpenAlgo holidays/timings/intervals changed from POST to GET
- optionchain response normalised: nested greeks flattened to top-level fields
- multiquotes response: array wrapper added for consistency with quotes endpoint
- WebSocket auth error now returns structured JSON instead of plain text disconnect
- CORS preflight: OPTIONS handler added to all /ft-api routes

### Fixed — General
- Kill switch now properly awaits async coroutines (was silently failing)
- Scheduler no longer blocks equity ticks during market hours
- TOTP encryption upgraded from XOR to Fernet (AES-128-CBC + HMAC)
- API key moved from localStorage to sessionStorage
- 6 window.confirm replaced with AlertDialog (Scalper, ActionCenter, KeyboardSection)
- British English: Analyse, Behaviour, Centre, Colour (8+ locations)
- Hardcoded hex colours replaced with design tokens
- Path traversal validation uses Path.is_relative_to
- Scanner exec() sandbox expanded with additional forbidden attributes
- Lot sizes updated for SEBI Nov 2024 revision
- Cron manager silent exception swallowing replaced with logging
- Gateway bare imports fixed with relative paths

### Fixed — Accessibility
- Skip-nav link target corrected to #main-content on all routes
- Focus trap in modal dialogs (AlertDialog, Dialog) improved for screen readers
- Colour contrast ratio on muted text raised to WCAG AA minimum (4.5:1)

### Fixed — Performance
- Lazy-loaded InvestRoute tabs: 14 tabs code-split individually (~142 KB saved from initial bundle)
- TanStack Query deduplication: identical queries across widgets share a single network request
- WebSocket reconnect backoff: exponential with jitter, capped at 30 s
- WebSocket batch subscribe with reference counting (fewer messages, cleaner unsubscribe)

### Removed
- settingsStore.sandboxMode (mode now in modeStore exclusively)
- ModePill.tsx and SandboxToggle.tsx (replaced by ModeIndicator)
- Dead code: unused FlexLayoutNode imports, orphan utility functions, unreachable switch branches
- Legacy /api/v0/ route prefix (all endpoints now under /api/v1/ or /ft-api/v1/)

---

## [0.4.1] - 2026-04-08

Tag: `v0.4.1` · Base: `v0.4.0` (`d202d1f`) · Patch release for
mode wiring, deployment readiness, endpoint alignment, and audit fixes.

### Added
- Unified mode system wiring with server-side order safety refinements.
- Production infrastructure for logging, monitoring, and deployment.

### Fixed
- Backend port alignment to the FlintTrade `5100` standard.
- Welcome auth checks, OpenAlgo fresh-clone support, API route issues,
  accessibility findings, and CI dependency gaps.

---

## [0.4.0] - 2026-04-02

Tag: `v0.4.0` · Base: `v0.3.0` (`10228da`) · Security, themes, execution
modes, and welcome/setup flow overhaul.

### Added
- Auth foundation with password/PIN setup, lock-screen flow, setup resume,
  and 8 AM IST session expiry.
- Three execution modes in the UI: Demo, Sandbox, and Live.
- Theme v4 and welcome/setup flow improvements.

### Fixed
- Light-mode contrast, broker-skip setup paths, dev-mode auth fallback,
  Flask threading, and auth endpoint security edge cases.

---

## [0.3.0] — 2026-03-31

v0.3.0 "Structured Calm" — Bloomberg precision + Stripe polish + Linear minimalism.

### Added — UI Redesign
- ContentShell universal centering wrapper (max-w-6xl, responsive padding)
- SectionHeader component with optional action button
- DataNumber three-tier numeric display (hero/primary/cell)
- DataDirection profit/loss indicator with color + icon + sign + sr-only text
- 4-level surface hierarchy (Base → Raised → Elevated → Floating)
- CSS custom properties for data-elevation, shadow-elevated, shadow-floating
- Graphite theme (new default) — desaturated blue-indigo accent #7c8be8
- Monochrome theme — zero-color gray accent
- Solarized Dark theme
- Theme v3 migration (6 removed themes → mapped to kept themes)
- react-resizable-panels on /trade (sidebar + Dockview + bottom panel)
- Focus ring 200ms scale-in animation
- Data update pulse (100ms background flash)

### Changed
- GlassCard defaults to solid (glass=false). Glass only on Level 3 floating elements.
- Default theme changed from emerald-night to graphite
- Price tick flash shortened to 300ms
- AnimatedCounter capped at 800ms
- Applied ContentShell to /invest, /learn, /ai, /settings, /admin, /explore, /setup, 404
- Typography scale: 24px route titles, hero numbers per route

### Removed
- 6 themes: Emerald Night, Ocean Depth, Solar Flare, Neon Pulse, Blood Moon, Cyber Dusk
- TextGenerateEffect on page headers (repeat-visit routes)
- BlurFade on section headers
- StaggeredList on card grids (replaced with 150ms container fade)
- hover:-translate-y-0.5 on cards (border-color transition only)
- @utility hover-lift from index.css
- Particles on all routes except /welcome

### Fixed (from v0.2.0-beta audit)
- 43 audit findings resolved (4 critical, 12 high, 15 medium, 12 low)
- Ticker -100% on WS disconnect (LTP=0 guard)
- Stale API key in WS singleton (updateCredentials + reactive hooks)
- Silent widget failures (error banners with retry in Orders/Positions/Holdings)
- Hardcoded dark colors in 8 chart/tool widgets → CSS var reads
- Route nav buttons → Links (WCAG 2.4.4)
- text-muted contrast brightened on all dark themes (WCAG AA)
- Dockview ARIA roles (tablist/tab/tabpanel)
- Dashboard loading skeletons
- Scalper CE/PE color inversion, shadcn/ui migration, error states
- ToolsDropdown portal rendering, Chart theme reactivity
- react-plotly.js excluded from Vite dep optimizer (prevents crash)

## [0.2.0-alpha] — 2026-03-25

OpenAlgo absorption: direct broker connections, analysis tools, platform features.

### Added — Broker Gateway (SP1)
- New packages/integrations/gateway/ package: direct connection to 31 brokers via adapter pattern
- BrokerRegistry: multi-account management, N simultaneous broker connections
- Fernet-encrypted credential storage (PBKDF2, per-account salt)
- WebSocket bridge: TickDispatcher replaces ZMQ PUB/SUB (in-process, no separate server)
- Flask auth blueprint: 10 endpoints for broker catalog, account CRUD, OAuth/TOTP/API key/OTP auth flows
- 4 OpenAlgo import shims (token_db, auth_db, config, logging) for submodule isolation
- ContractManager: per-broker master contract SQLite cache
- Startup account reconnection from encrypted credentials
- Frontend: brokerStore (Zustand), gatewayApi client, useBrokerAccounts/useBrokerAuth/useBrokerList hooks
- Setup page: BrokerPicker, ConnectedAccounts, AuthFlowAPIKey, AuthFlowTOTP components

### Added — Analysis Tools (SP2)
- 5 new Plotly.js analysis widgets: GEX Dashboard, Volatility Surface 3D, IV Smile, Straddle P&L Simulator, OI Profile
- Plotly.js integration with shared PlotlyChart wrapper (theme-aware, lazy-loaded)
- 5 backend screener modules: gex.py, vol_surface.py, iv_smile.py, straddle_pnl.py, oi_profile.py
- 6 new Flask analysis endpoints (/ft-api/v1/gex, volsurface, ivsmile, straddlepnl, oiprofile, maxpain)
- OptionChain upgrade: LTP flash animation, max pain badge, gradient OI bars
- OIChart upgrade: Plotly grouped bars replacing CSS, PCR overlay, ATM/Max Pain markers
- Widget count: 21 → 26

### Added — Platform Features (SP3)
- Sandbox paper trading engine (DuckDB, MARKET/LIMIT/SL fills, auto square-off)
- Python strategy runner (AST validation, subprocess isolation, memory limits)
- Action Center: semi-auto order approval queue with configurable TTL
- Security dashboard: IP tracking, auto-ban on threshold, threat detection
- P&L tracker: real-time tradebook P&L time series
- Historify watchlist: scheduled OHLCV download management
- Health/Traffic/Latency monitoring with circular buffer and percentile tracking
- OrderRouter sandbox integration (routes to virtual engine when account is in sandbox mode)

### Added — Infrastructure
- Weekly submodule compatibility CI check (.github/workflows/submodule-check.yml)
- Makefile: start-gateway target for single-process mode
- .env.example: gateway section (MASTER_PASSWORD, FLINTTRADE_PORT, WS_PORT)

## [0.1.0-beta] — 2026-03-24

Full repo audit + god component refactoring. Security hardened, performance optimized, WCAG accessible.

### Added — Security
- Flask API authentication (before_request hook validates API key on all 20+ endpoints)
- SQL injection prevention (table name allowlist + path validation in DuckDB pipeline)
- Telegram bot denies commands by default when chat_id not configured
- Ditto module requires DITTO_ENCRYPTION_KEY (was silently generating ephemeral key)

### Added — Accessibility (WCAG 2.2 AA)
- MotionConfig reducedMotion="user" at app root (all Framer Motion respects OS preference)
- Landmarks (<main>, <header>, <nav>) on all 5 flow routes
- useDocumentTitle hook — page title updates on every route change
- Keyboard-accessible ToolsDropdown (role="menu", Arrow/Escape navigation)
- Keyboard-accessible workspace tab context menu (Shift+F10, Escape)
- ARIA roles for sidebars (Learn, Lab, Automate), workspace tabs, accordion items
- Form labels (aria-label) on all ThemePicker, BackgroundPicker, SettingsTool inputs
- Focus management on AIRoute overlay panels
- role="alertdialog" + aria-modal on SmallScreenOverlay
- role="dialog" on InteractiveTour

### Added — Performance
- vendor-misc chunk split: 1,116 KB → 320 KB (-71%). Tremor/recharts/d3 deferred to async vendor-charts
- WebSocket tick batching via requestAnimationFrame in useWsBridge
- Zustand useShallow selectors for array/object subscriptions (TopBar, GlassCard, RiskPanel, MTMMonitor)
- Dockview layout auto-save debounced to 500ms (was every pixel of drag)
- Build target set to es2022 (smaller output, native syntax)

### Changed — Code Quality
- ChartWidget split: 3,001 → 628 lines (indicators.ts, useChartInit, useDrawingTools, useIndicators, ChartLegend, types)
- OptionChainWidget split: 1,376 → 491 lines (SymbolSearch, BasketPanel, useOptionChainData, gridConfig, formatters, types)
- AutomateRoute split: 1,338 → 81 lines (7 section components)
- SetupRoute split: 1,422 → 367 lines (8 step components)
- SettingsTool split: 1,278 → 212 lines (11 section components with aria-labels)
- getWsService return type corrected to WebSocketService | null (was null!)
- Timer leaks fixed in OrderPad + OptionChain (ref-based cleanup)
- Dead FlexLayoutNode interface removed from 6 analysis widgets
- Relative imports converted to @/ alias in 6 analysis widgets
- prev_close added to Quote type, post() body type widened (removed double casts)
- useGlobalKeys now logs errors (was silently swallowing trading action failures)

### Fixed — Security
- Flask error responses sanitized (no more str(exc) leaked to clients)
- Webhook server binds to 127.0.0.1 by default (was 0.0.0.0)
- useDuration memory leak in LabRoute (setInterval in useState never cleared)
- Dockview panel listeners now disposed on unmount

### Fixed — Accessibility
- textMuted contrast fixed in 5 dark themes (Terminal Green, Ocean Blue, Sunset, Neon, Forest)
- Solarized Dark profit color contrast improved (#859900 → #a3b900)
- WelcomeRoute skips animation when prefers-reduced-motion enabled
- DailyWelcome: <p role="button"> replaced with native <button>
- SetupRoute: misused role="tablist" removed from progress indicator
- pulse-glow CSS animation changed to opacity-only (was animating box-shadow)
- bg-[rgba(...)] replaced with bg-loss/10 design token in DailyWelcome
- Circular chunk warning eliminated (cmdk + @floating-ui moved to vendor-radix)
- Unused deps (marked, react-responsive-carousel) moved to devDependencies

### Changed
- Order-safety doc rewritten with local audit, rate-limit, and kill-switch notes
- CONTRIBUTING.md rewritten with detailed commit guidelines
- .gitignore cleaned up
- Test counts: 979 Python + 36 Vitest = 1,015 total

### Removed
- 50 internal dev docs removed from public repo (archived locally)
- DEVLOG.md, SOP.md decommissioned (replaced by CHANGELOG + CONTRIBUTING)

## [0.1.0-alpha] — 2026-03-21

Feature-complete alpha release. 13 packages, 1,021 tests, 7 routes, 21 widgets, full-stack wiring.

### Added — UI Foundation
- Geist font (headings) + Inter (body) + JetBrains Mono (data) — 3-tier font system
- 60+ design tokens (surfaces, borders, text, trading semantics)
- 5 built-in themes: Midnight, Obsidian, Terminal Green, Ocean Blue, Light
- SVG Logo component (LogoIcon, LogoWordmark, LogoFull)
- Density modes (comfortable/compact, auto-detect on small screens)

### Added — Routes & Navigation
- 7 app routes: /learn, /invest, /trade, /lab, /automate, /ai, /settings
- Cinematic /welcome screen with pillar cards and theme switcher
- /explore demo mode with sample data previews (no broker needed)
- /setup onboarding wizard with persona x interest matrix
- Global route tabs in TopBar (Learn · Invest · Trade · Lab · Automate · AI)
- 6 workspace presets: Scalper Zone, Options Desk, Market Watch, Analysis, Risk Monitor, Investor View

### Added — Full-Stack Wiring
- 100% OpenAlgo API coverage (45+ endpoints wired to UI)
- 20 FlintTrade backend endpoints (backtest, signals, sentiment, RAG, cron, audit, safety, webhooks)
- ftApi.ts TypeScript client for FlintTrade Python backend
- Market Intelligence: 4 new tabs (GEX, IV Smile, Max Pain, OI Profile)
- Synthetic Future in OptionChain header, Margin in OrderPad
- Market status badge in TopBar, holiday-aware DailyWelcome
- REST ticker fallback when WebSocket disconnects
- AI Advisor embedded in /ai Chat section with streaming + MCP

### Added — UI Libraries
- Tremor (dashboard charts, KPI cards, sparklines, tracker)
- Magic UI (AnimatedCounter, ShimmerButton, Particles, BlurFade)
- Aceternity UI (HoverCard spotlight, TextGenerateEffect, Meteors)

### Added — Infrastructure
- ErrorBoundary wrapping entire app
- 404 catch-all route (NotFoundRoute)
- connectionStore persisted to localStorage
- Mobile/small screen warning overlay
- prefers-reduced-motion media query (WCAG 2.3.3)
- Semantic landmarks (<header>, <main>, <nav>), skip-to-content link
- ARIA roles on route tabs, sidebar navigation, icon buttons

### Fixed
- 80+ hardcoded palette colors → design tokens (text-profit/text-loss/text-warning)
- isMarketHours() deduplicated to lib/market.ts, polling now dynamic
- Dockview: slim tabs (28px), singleTabMode, hidden close buttons
- window.prompt/confirm → inline rename/delete UI
- TOOLS/WIDGETS buttons hidden on non-trade routes
- Sidebar border-l-2 jump fixed (transparent border on inactive)
- Light theme Dockview CSS uses var() tokens
- Setup wizard presets mapped to real workspace presets
- Empty Dockview state shows Add Widgets / Choose Template overlay
- DailyWelcome suggestions now clickable
- Removed unused deps (lodash, oakscriptjs)
- docker-compose: removed deleted packages, fixed ports

### Tests
- Python: 985 passed, 3 skipped
- Vitest: 36 passed (10 new ticker fallback tests)
- TypeScript: 0 errors (strict mode)
- Build: clean

### Added — Retroactive Backfill (2026-04-24, from DEVLOG)
These entries were shipped during the 0.1.0-alpha window (2026-03-19 / 2026-03-20) but missed on the DEVLOG-to-CHANGELOG handoff. Sourced from `.local/archive/DEVLOG.md` and `.local/journey/TIMELINE.md`.

- **Rust/PyO3 `tick-engine` package** — new monorepo package with TickSimulator + streaming EMA-crossover + 25 PyO3 tests; first Rust component in the stack (2026-03-20)
- **Python indicators endpoint** — `/api/v1/indicators/compute` plus 8 additional chart indicators (TA-Lib-backed) wired into ChartWidget (2026-03-20)
- **Analysis absorption** — 31 TA-Lib / Numba indicators plus 28 backtest-engine strategy templates absorbed from reference repos (2026-03-19)
- **OptionChainWidget canvas rewrite** — re-implemented on Glide Data Grid, removing ~320 lines of DOM markup and moving to a canvas renderer (2026-03-20)
- **NewsWidget v1** — RSS feed ingestion with rule-based sentiment keyword scoring (2026-03-19)
- **FlexLayout → Dockview v5 migration** — layout engine replaced across the terminal; removed `flexlayout-react` + `recharts`; full JSX → TSX conversion completed in the same window (2026-03-19)

### Fixed — Retroactive Backfill (2026-04-24)
- **TerminalRoute bundle size** — 1,251 KB → 19 KB via `manualChunks` configuration and lucide-react tree-shake fix; route-level code splitting enabled (2026-03-20)

## [0.0.1-dev] — 2026-03-14

### Added — Core
- async OpenAlgo client — 45+ endpoints, rate limiting (10 OPS orders,
  2 OPS smart, 50 OPS general), exponential backoff retry
- Pydantic models — Order, Position, Quote, Fund, OptionGreek, etc.
- Settings.from_env(), exceptions hierarchy
- FlintTradeApp entry point — wires all 12 packages into single startup

### Added — Engine
- 5-layer SafetySystem (OrderValidation, PositionLimits, PortfolioRisk,
  DailyPnL, KillSwitch)
- Per-exchange market hours (NFO/BFO 15:30, CDS 17:00, MCX 23:30, DELTA 24/7)
- OrderRouter wired to OpenAlgoClient + AuditLogger
- StrategyRunner + StrategyScheduler — async tick loop, deploy freeze guard
- EMACrossover — first concrete strategy with position reversal

### Added — Data & Historical
- Audit trail (JSONL append-only, gzip rotation; operator-controlled retention)
- DuckDB storage — ticks, trades, daily summaries
- Multi-source downloader, free NSE data, DuckDB pipeline, expiry manager

### Added — Screener & Analysis
- Option chain, OI spurt, futures quadrant, portfolio Greeks, IV analysis

### Added — Backtest
- Event-driven simulator, walk-forward optimizer, 12 strategy templates
- Monte Carlo analysis, performance metrics (Sharpe, Sortino, Calmar, VaR)
- React backtest UI — config panel, results, equity curves, compare mode

### Added — AI & Integration
- LLM client (LM Studio, Ollama, Anthropic, OpenAI), RAG, ML signals
- News sentiment, MCP bridge, stock advisor
- TradingView webhooks, ChartInk, visual flow builder, alerter

### Added — Automation & Ditto
- Cron manager (5 jobs), Telegram bot with /kill switch
- Position mirroring, margin-aware allocation, trailing SL, risk manager

### Added — Frontend
- terminal: Dockview widget-composable trading terminal — 14 widgets (TSX),
  7 tools, TypeScript strict, shadcn/ui, Zustand+Jotai+TanStack Query

### Added — Infrastructure
- Docker support — docker-compose.yml for Windows/macOS/Linux/Raspberry Pi
- Cross-platform setup guides (docs/setup/)
- systemd service file, production deployment scripts
- Feature flags — ENABLE_BACKTEST, ENABLE_AI

### Added — Initial Setup
- Monorepo — 12 packages with per-package CLAUDE.md + AGENTS.md
- CI/CD — GitHub Actions (pytest, ruff, secrets check)
- Order-safety framework — rate limits, kill switch architecture, audit
- Infrastructure — nginx, systemd, WireGuard, fail2ban, deploy scripts
- Git-native bug tracking system
- Documentation — OpenAlgo API reference, tools guide, machine configs

### Added — Retroactive Backfill (2026-04-24, from DEVLOG)
These entries correspond to material milestones reached during the 0.0.1-dev window (2026-03-16) but missed on the DEVLOG-to-CHANGELOG handoff. Sourced from `.local/archive/DEVLOG.md` and `.local/journey/TIMELINE.md`.

- **First end-to-end order** — first real order routed through FlintTrade -> OpenAlgo -> broker sandbox, confirming the full engine pipeline (OrderRouter + SafetySystem + AuditLogger + OpenAlgoClient) works against a live broker (2026-03-16)
- **First production deployment** — FlintTrade first run on bare-metal Ubuntu with systemd unit files and the production deploy script (2026-03-16)
- **OpenAlgo v2.0.0.1 submodule sync** — absorbed native Delta Exchange support, Nubra broker adapter, 5 new API endpoints, upstream CVE fixes (2026-03-16)
