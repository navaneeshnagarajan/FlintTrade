# Changelog

All notable changes to FlintTrade will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/).
Versioning: [Semantic Versioning](https://semver.org/).

<!--
Release history was reset to a clean v0.0.1 baseline on 2026-07-23. The earlier
v0.1.0…v0.6.0-beta.13 tags and releases (the retired Tauri/PyInstaller line, plus
the updater-beta channel manifest) were deleted so the project could restart with
honest, pre-release-marked 0.0.x semantic versioning while it is still pre-usable.

No history was lost: every commit and its detailed message remains in git.
release-please regenerates the sections below from Conventional Commits, so the
changelog rebuilds itself from the first release cut after this baseline.
-->

## 0.0.1 (2026-09-02)


### Added

* **ai,settings:** persist LLM config from the UI ([a7cd620](https://github.com/navaneeshnagarajan/FlintTrade/commit/a7cd620e5a839d137fa194819879dbfd272c1ab0))
* **ai:** make the componentised RAG pipeline canonical ([850ad29](https://github.com/navaneeshnagarajan/FlintTrade/commit/850ad298e2de389cf7de0b94ec9b25a4c906fa2b))
* **ai:** operator-approved skill drafts from post-session review — AI1 ([d73fd8b](https://github.com/navaneeshnagarajan/FlintTrade/commit/d73fd8b1e02d3a4a36afd9b17cc39dbcdee224ac))
* **ai:** persist and search AI chat sessions — AI2 cross-session recall ([2a61339](https://github.com/navaneeshnagarajan/FlintTrade/commit/2a6133969f48f5e91e623fb8fa043d27c4b62c87))
* **ai:** persist the Obsidian vault path from the UI (U18 slice) ([63ae047](https://github.com/navaneeshnagarajan/FlintTrade/commit/63ae047821b5073574ae646ff4ea5218fd0945df))
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
* **ai:** wire the agent learning loop — session trades → reflection → next-session context ([317c717](https://github.com/navaneeshnagarajan/FlintTrade/commit/317c7177117279a55e15b5ceab042a046266ec2d))
* **app:** consolidate the daily-driver runtime ([dff61a7](https://github.com/navaneeshnagarajan/FlintTrade/commit/dff61a7ebaa4478bec445945ff58b866cbd54b9d))
* **automation,core:** wire the post-market cron and the dormant admin routes ([cc306b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/cc306b8c2af1bc8b017fd007772c3d7545f758e5))
* **automation:** native Telegram bot — reachable kill switch, no python-telegram-bot (G30) ([3f30f75](https://github.com/navaneeshnagarajan/FlintTrade/commit/3f30f750c29fc0d01fe363b366f0e9096cffaa3b))
* **backtest:** fold the WFE ratio into the routed walk-forward path — U13 partial ([5c1a6d0](https://github.com/navaneeshnagarajan/FlintTrade/commit/5c1a6d0de174b5cfa5e3484fabcac3416203ec3e))
* **brokers:** catalogue arrow and TradeSmart bridge brokers (P12) ([929dff2](https://github.com/navaneeshnagarajan/FlintTrade/commit/929dff207e2a911d10268d805152a2e3d70e85af))
* **brokers:** catalogue OpenAlgo's self-hosted MCP as the first-preference entry ([7271f07](https://github.com/navaneeshnagarajan/FlintTrade/commit/7271f074e80e7426b11b0843e0032fc0ff1f8b93))
* **brokers:** surface native SDK readiness ([74ac701](https://github.com/navaneeshnagarajan/FlintTrade/commit/74ac70155512b6299112395bad00be61fec3bf1e))
* **ci:** automate version bumps and releases with release-please ([2dc1e3d](https://github.com/navaneeshnagarajan/FlintTrade/commit/2dc1e3dc2a91495d28f1d06eddf87bc1691ae73b))
* **ci:** publish the frozen backend as a hash-verified payload asset ([51e0901](https://github.com/navaneeshnagarajan/FlintTrade/commit/51e0901b69726f2a6101b213d76686ced466f957))
* **ci:** sign, notarise, and emit updater artifacts when secrets exist ([44627aa](https://github.com/navaneeshnagarajan/FlintTrade/commit/44627aa658f867395a02457bad3e6ccf9ad44964))
* **core,terminal:** persist n8n bridge settings from the UI (U18 slice) ([cb8b0e9](https://github.com/navaneeshnagarajan/FlintTrade/commit/cb8b0e9a5709652a9c5fc01e413b5222ea82a5fb))
* **core,terminal:** persist Telegram bot settings from the UI (U18 slice) ([dc28c04](https://github.com/navaneeshnagarajan/FlintTrade/commit/dc28c045c66879c199f0772c1122b47d82196cbd))
* **core,terminal:** persist WhatsApp alert settings from the UI (U18 slice) ([d0bddf4](https://github.com/navaneeshnagarajan/FlintTrade/commit/d0bddf4336764a215d88ab032de9a8074eb353f0))
* **core:** first-class web surface with a fail-closed remote bind ([43ca26c](https://github.com/navaneeshnagarajan/FlintTrade/commit/43ca26cef35d3a76138a0e0b937f4cea8336078e))
* **core:** migrate every module off the hardcoded ~/.flinttrade literal ([#106](https://github.com/navaneeshnagarajan/FlintTrade/issues/106)) ([ef6f3d1](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef6f3d169bcf7ec95704f537b8b80ae691ed74c6))
* **core:** serve traffic stats from the persistent store — U12 complete ([555a198](https://github.com/navaneeshnagarajan/FlintTrade/commit/555a198df70633d14962bd565489b7c5a99004e8))
* **core:** stream captured ticks into live signals ([64bb985](https://github.com/navaneeshnagarajan/FlintTrade/commit/64bb985652e70c27e521904fc23ce0a897110cae))
* **data:** authenticated gated-audit PDF/CSV export + summary (G37 A3) ([2bd443c](https://github.com/navaneeshnagarajan/FlintTrade/commit/2bd443c6a687457e55e6d8f1440e945e2b70f4a8))
* **data:** make the audit log a real tamper-evident hash chain (G26) ([acca656](https://github.com/navaneeshnagarajan/FlintTrade/commit/acca656d158c1c41d83508605e08af7fb5e06676))
* **data:** scheduled EOD delta-sync + tick capture mode config ([21e821c](https://github.com/navaneeshnagarajan/FlintTrade/commit/21e821cfa07671fd1c63c12d9827173b0fad43be))
* **data:** tick-capture status/query/watchlist API + configurable capture list ([3ea07fb](https://github.com/navaneeshnagarajan/FlintTrade/commit/3ea07fba671442a39488a8b0c06b926c65efe287))
* **deps:** declare and install the full ML/AI stack — 68 skipped tests now run ([4f92cf0](https://github.com/navaneeshnagarajan/FlintTrade/commit/4f92cf09dcfd89583f3398e55423a29210e265ca))
* **desktop:** add journalled source updater ([f3af162](https://github.com/navaneeshnagarajan/FlintTrade/commit/f3af162c1b62d8a349960f6c88ec527e6cd70dcc))
* **desktop:** add source guardian lifecycle ([3199dda](https://github.com/navaneeshnagarajan/FlintTrade/commit/3199dda695f2bc16432d8970e817691ebd0153c0))
* **desktop:** add verified source bootstrap ([c7dd3f4](https://github.com/navaneeshnagarajan/FlintTrade/commit/c7dd3f4e886a14de5291105c5cb5fa8068339078))
* **desktop:** background runtime — close-to-tray, tray, hotkey, native notifications ([7cfd407](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cfd407359f19a253e627511e445cf43d6bddc19))
* **desktop:** cut over Electron distribution ([c19991b](https://github.com/navaneeshnagarajan/FlintTrade/commit/c19991bf133e3f57e6ceaae1a35e0baf92e5a54a))
* **desktop:** Electron source-bootstrap migration + clean v0.0.1 release reset ([a6f9246](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6f92464977ab03a6049ebbaf7f579c31bcf69fd))
* **desktop:** harden source mutation with native atomicity and attested updates ([0723835](https://github.com/navaneeshnagarajan/FlintTrade/commit/0723835f9e591b2575eed5bfd52fb9b65a6233ae))
* **desktop:** install and update from release assets ([87e69a5](https://github.com/navaneeshnagarajan/FlintTrade/commit/87e69a558c4e665885b271d3f978971247bdfaf5))
* **desktop:** let the native Windows uninstaller remove all app data ([3b31935](https://github.com/navaneeshnagarajan/FlintTrade/commit/3b31935b253f503a209189469bc0064dbfdea813))
* **desktop:** manage the backend payload like the Ollama runtime ([08344ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/08344ef56deffb8947707c8ab4d82f4fb747814a))
* **desktop:** one-click native updates via tauri-plugin-updater ([5eb43c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/5eb43c81f7a1d27305c7acc92405d0ea9274a625))
* **desktop:** port Electron update experience ([44bab17](https://github.com/navaneeshnagarajan/FlintTrade/commit/44bab172324c849dacdf3de822f08833b0d93e03))
* **desktop:** retire legacy runtime ([ec01663](https://github.com/navaneeshnagarajan/FlintTrade/commit/ec01663851e71a833bcf04ac3d233eec36f6090a))
* **desktop:** scaffold Electron security waist ([296039e](https://github.com/navaneeshnagarajan/FlintTrade/commit/296039e77dc16ca027255b6addd637c78a2fd62e))
* **desktop:** ship clean uninstall scripts for macOS, Linux, and Windows ([2100234](https://github.com/navaneeshnagarajan/FlintTrade/commit/2100234491fdc68568d111fe2eab10bfd77542f1))
* **desktop:** sidecar watchdog, OAuth opener, in-app update-by-rebuild ([74760c3](https://github.com/navaneeshnagarajan/FlintTrade/commit/74760c39681b3e690fb508c3c9420d8cf0ce615e))
* **desktop:** thin-shell installers with first-run payload bootstrap ([fc6c716](https://github.com/navaneeshnagarajan/FlintTrade/commit/fc6c716ec1238d0f7126dd1883f19792be539ab1))
* **engine:** gated bracket orders — every leg through gate_order -&gt; BrokerRouter ([8128b4f](https://github.com/navaneeshnagarajan/FlintTrade/commit/8128b4fff2996ef056ec1519ccc295112036f2bb))
* **engine:** route basket/split orders through the gate, wire them live (G13) ([9114fde](https://github.com/navaneeshnagarajan/FlintTrade/commit/9114fde4a33b4bb4b6301687ec84bfb89d73ba8d))
* FINOS-stack migration — FlexLayout, FDC3, Perspective + full indicator restoration ([#88](https://github.com/navaneeshnagarajan/FlintTrade/issues/88)) ([94e1c50](https://github.com/navaneeshnagarajan/FlintTrade/commit/94e1c506b54699d2acf194ed405108d754e32ea9))
* **historical:** NSE bhavcopy downloader + local-store browse API ([e20c559](https://github.com/navaneeshnagarajan/FlintTrade/commit/e20c55939ff12e5485dcef8b55af821e29e4b0d6))
* **infra:** one installer per OS — universal macOS DMG, per-user Windows exe, AppImage-backed Linux command ([ac918f8](https://github.com/navaneeshnagarajan/FlintTrade/commit/ac918f8d4604a6a555efaeb80098e7990c55e4bf))
* **install:** fetch release metadata from GitHub release URLs ([fd3d6cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd3d6cf98eac978c0df31b9799de96db121dd8e8))
* **invest:** value-visibility (hide amounts) toggle (P7) ([8df16f5](https://github.com/navaneeshnagarajan/FlintTrade/commit/8df16f59c72ed35136580cdca943c4c7f90e1cd5))
* **journal:** port TradeJournal to SQLite + FTS5 with full-text search (G31) ([57c3b12](https://github.com/navaneeshnagarajan/FlintTrade/commit/57c3b12ee22c4712786abb9b65ae752fee2a2f1d))
* **journal:** wire the Trade Journal REST API + fix the migration (G31) ([c37f76e](https://github.com/navaneeshnagarajan/FlintTrade/commit/c37f76e9b386b7115bfd68d9fb7d94adbc6733fc))
* **repo:** converge completed non-release work ([#132](https://github.com/navaneeshnagarajan/FlintTrade/issues/132)) ([77deb79](https://github.com/navaneeshnagarajan/FlintTrade/commit/77deb79b5cc9d35bf7fc0f50d02581bcda55a398))
* **repo:** converge completed non-release work ([#142](https://github.com/navaneeshnagarajan/FlintTrade/issues/142)) ([7712623](https://github.com/navaneeshnagarajan/FlintTrade/commit/7712623651e528e8019eb5603713fc45d89e48ed))
* **screener,scalper:** one lot-size table + Scalper bracket legs ([5b76333](https://github.com/navaneeshnagarajan/FlintTrade/commit/5b76333f44287ffe714279c88a646a1e3ac646c7))
* **screener:** candlestick pattern detection (W4) ([f5893ea](https://github.com/navaneeshnagarajan/FlintTrade/commit/f5893ea876016da9eebfb7c4724ace122ebe1e9d))
* **screener:** cash-future & cross-exchange arbitrage scanner (DP3) ([e296b50](https://github.com/navaneeshnagarajan/FlintTrade/commit/e296b50ed43c58fe8494ec87e8d5d7446b0d5a79))
* **screener:** FII long/short ratio surface (DP1) ([4300c4e](https://github.com/navaneeshnagarajan/FlintTrade/commit/4300c4ea2a422a3a5b6a1534b8e008b87e26aa12))
* **screener:** gamma density analytics surface (DP2) ([e87bb4d](https://github.com/navaneeshnagarajan/FlintTrade/commit/e87bb4d8ec9c9cedeff269cb3c2c513a18876829))
* **screener:** index contribution panel (W7) ([81c11ab](https://github.com/navaneeshnagarajan/FlintTrade/commit/81c11abc168548dd2bd542dc3ddf075cd9cfbc22))
* **site,scripts:** one-command build-on-device installers + /download page ([56636e3](https://github.com/navaneeshnagarajan/FlintTrade/commit/56636e3863d7777955472951be61f83e8b329f68))
* **site:** port Graphite A1 motion with default-off Three.js ([#162](https://github.com/navaneeshnagarajan/FlintTrade/issues/162)) ([2bdad95](https://github.com/navaneeshnagarajan/FlintTrade/commit/2bdad9510b3c082dab32a2626e05530c48e9c8c6))
* **site:** web-first download page with one installer per OS ([f11e86e](https://github.com/navaneeshnagarajan/FlintTrade/commit/f11e86e2a0ed84bb494944f99ea482fd4ac0a2fa))
* **terminal:** add configurable AI team runs ([5bf61d9](https://github.com/navaneeshnagarajan/FlintTrade/commit/5bf61d935e534a7e00ebeb4d938b618d6ccc999f))
* **terminal:** AI Backends widget + Cerebras/Claude-OAuth in Settings (replaces OpenClaw) ([425ebb2](https://github.com/navaneeshnagarajan/FlintTrade/commit/425ebb2980b7c4d7a294c879b1de541cb5829271))
* **terminal:** apply the font-size setting to the terminal typography ([2b49957](https://github.com/navaneeshnagarajan/FlintTrade/commit/2b499574fb4852834251dbc41e95ca2890161e97))
* **terminal:** browse and search past AI sessions from the Advisor widget ([a6d8430](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6d84303f36ca6e0e76f6103f662946606fa6ef7))
* **terminal:** compute Session Stats from today's real trades ([ecd8c16](https://github.com/navaneeshnagarajan/FlintTrade/commit/ecd8c16a7610cc4018a440b23a09183e5af98384))
* **terminal:** daily-driver trade loop — live wiring, reconciliation, honest errors ([f795a71](https://github.com/navaneeshnagarajan/FlintTrade/commit/f795a71c9f8419cd131f103dae3fecd48aa27114))
* **terminal:** drive the Scanner widget from real scans ([c8be818](https://github.com/navaneeshnagarajan/FlintTrade/commit/c8be818b7c278abeecd09e309a8fd5ebeaad60ea))
* **terminal:** live-back the Market Summary widget with per-section provenance ([9d73658](https://github.com/navaneeshnagarajan/FlintTrade/commit/9d736585a3ced7ffb7136ccfc4b229d21f9c63dc))
* **terminal:** Local Data panel (tick capture + store + bhavcopy) & CI shard fix ([4b26cc8](https://github.com/navaneeshnagarajan/FlintTrade/commit/4b26cc8a9c5d3fe39d1a339b8ffaa30f8028aa84))
* **terminal:** make the Scanner's OI Change tab live — all four tabs now real ([cc2f28f](https://github.com/navaneeshnagarajan/FlintTrade/commit/cc2f28fbb37a55451d9a808b595590a71edcd324))
* **terminal:** move in-app saved content from WebView localStorage to the workspace ([1d1f253](https://github.com/navaneeshnagarajan/FlintTrade/commit/1d1f2537b165b263c2495a00c2a7287f5dabf9f9))
* **terminal:** review, approve and reject skill drafts from Settings ([97cb9ce](https://github.com/navaneeshnagarajan/FlintTrade/commit/97cb9cec1023407b3189ee3ba2cab0fdf70b2d38))
* **terminal:** set the Obsidian vault path from the widget ([30b50fe](https://github.com/navaneeshnagarajan/FlintTrade/commit/30b50fe209818779c9ac6e8db0bb655981a80ef6))
* **terminal:** Time & Sales tape widget (W3) ([90b567a](https://github.com/navaneeshnagarajan/FlintTrade/commit/90b567acaafbc288cf1c7e6eb2495c794b460427))
* **terminal:** Trade Journal widget — searchable annotated journal UI (G31) ([bbb1fd1](https://github.com/navaneeshnagarajan/FlintTrade/commit/bbb1fd11ea3ba51f6b1ec7fb8f188735e0c046d7))
* **ticks:** re-export the full compiled tick-engine surface (G29) ([8c5f875](https://github.com/navaneeshnagarajan/FlintTrade/commit/8c5f8755efdaec47c6fb6e330ae7a4c8ba12fdcf))
* **watchlist:** row-hover quick Buy/Sell → prefilled gated ticket (W2) ([98b5c3e](https://github.com/navaneeshnagarajan/FlintTrade/commit/98b5c3ef5308a71521d810c65b85d90737d4c7de))
* **watchlist:** user-defined formula builder (W1) ([64ec8eb](https://github.com/navaneeshnagarajan/FlintTrade/commit/64ec8eb4681558f9918c5029553737feab074732))
* **webhooks:** GoCharting alert webhook source (B2) ([6f739f6](https://github.com/navaneeshnagarajan/FlintTrade/commit/6f739f66d2d8d457cda34683fe2cc7bfe4167802))


### Fixed

* **ai,terminal:** harden unified signal feed ([c35c310](https://github.com/navaneeshnagarajan/FlintTrade/commit/c35c31054ce7939849ad6792815726ce05bfef6d))
* **ai:** bind agents and training to market sessions ([e5962c4](https://github.com/navaneeshnagarajan/FlintTrade/commit/e5962c486773bed1c0dec99cbaf2191111d4f8ba))
* **ai:** bound Antigravity stdout retention + broaden env-secret scrub (B2 audit) ([a995875](https://github.com/navaneeshnagarajan/FlintTrade/commit/a995875622f14fe236be85f78766ae4680ee8324))
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
* **ai:** replace vulnerable ChromaDB persistence ([#154](https://github.com/navaneeshnagarajan/FlintTrade/issues/154)) ([b615d2c](https://github.com/navaneeshnagarajan/FlintTrade/commit/b615d2c8f4b97723cac0d4f68dd4251db8a6c108))
* **ai:** respect exchange lifecycle ownership ([debeb3c](https://github.com/navaneeshnagarajan/FlintTrade/commit/debeb3cac961c04dd40ce41409ae6b1b49135b44))
* **ai:** respect instrument market hours ([193275d](https://github.com/navaneeshnagarajan/FlintTrade/commit/193275dab76a39176c71f2e41f3a6eccc367636f))
* **ai:** route signal history through core OpenAlgo client ([45e2699](https://github.com/navaneeshnagarajan/FlintTrade/commit/45e26997393c206cc8c34370c5cc40b124d55dbd))
* **ai:** scrub operator provider secrets from the Antigravity subprocess env ([515e73d](https://github.com/navaneeshnagarajan/FlintTrade/commit/515e73d87a6f6b5078171ac2ba2ba8b24050e935))
* **ai:** serialise autonomous agent startup ([3416187](https://github.com/navaneeshnagarajan/FlintTrade/commit/34161877e9fb7c669cab42dedd74797b9a83e98c))
* **ai:** synchronise scheduled signal rosters ([244ba85](https://github.com/navaneeshnagarajan/FlintTrade/commit/244ba857f9e04212aaa724052da10b58a9a1998e))
* **ai:** train only on closed market data ([c863673](https://github.com/navaneeshnagarajan/FlintTrade/commit/c863673f97f4110c53b8ce6cf89dc1d02d72c2af))
* **auth,brokers:** set-PIN-later, setup mode transition, fail-closed demotion, Codex-wave follow-ups ([b111e84](https://github.com/navaneeshnagarajan/FlintTrade/commit/b111e84964824bf122e332471e65ffb2cdc82879))
* **automation,core:** quiet the no-broker market-calendar log spam + provision master password for start ([2e9c788](https://github.com/navaneeshnagarajan/FlintTrade/commit/2e9c788d90abbfc550dda6bf109c90309fbf7fe1))
* **automation:** retain live calendar references ([da2014f](https://github.com/navaneeshnagarajan/FlintTrade/commit/da2014f78987cb9a0afdbf16d0706b766647a56b))
* **brokers:** activate Dhan resolver for native routes ([82786f7](https://github.com/navaneeshnagarajan/FlintTrade/commit/82786f7140d583e78faa327bf830b3a43d51678b))
* **brokers:** align broker verification surfaces ([ac2cc07](https://github.com/navaneeshnagarajan/FlintTrade/commit/ac2cc0715c4a858e69865622c9b5b619fb106ee4))
* **brokers:** align dashboard token reset expiry ([d697d04](https://github.com/navaneeshnagarajan/FlintTrade/commit/d697d0464480b3197c2b958718708d0883834ad4))
* **brokers:** align gateway primary eligibility ([5ae5553](https://github.com/navaneeshnagarajan/FlintTrade/commit/5ae555375e6ae1a6d4359bae1ef85747a96172d2))
* **brokers:** demote read-only native connect primaries ([fb88773](https://github.com/navaneeshnagarajan/FlintTrade/commit/fb88773857180cd7b370580767ced6396203744b))
* **brokers:** expose native connect blockers ([8c3c43c](https://github.com/navaneeshnagarajan/FlintTrade/commit/8c3c43cbb9cc44c2e9fca90e4ced80e7f59406a4))
* **brokers:** keep live probe handoff lists canonical ([b99799c](https://github.com/navaneeshnagarajan/FlintTrade/commit/b99799cbcb13b3b891320c3968d4e7b00bae0049))
* **brokers:** preflight native SDK readiness ([9cd6376](https://github.com/navaneeshnagarajan/FlintTrade/commit/9cd63763ecc402f6c28973e7c255fffdf17cf79c))
* **brokers:** remediate wave-2 audit and one-core conformance findings ([a3bb5df](https://github.com/navaneeshnagarajan/FlintTrade/commit/a3bb5df2eda8c04dd9ff41b8d9be59e869764d0a))
* **brokers:** return blockers from legacy native rejects ([23a3a27](https://github.com/navaneeshnagarajan/FlintTrade/commit/23a3a275c007c2ea7f1948835a232b733a73de4e))
* **brokers:** surface static IP requirements ([8fc079e](https://github.com/navaneeshnagarajan/FlintTrade/commit/8fc079e11eaddfc8e60cd96669c721148c869faf))
* **ci:** arch-qualify the macOS updater bundle before publishing ([b513941](https://github.com/navaneeshnagarajan/FlintTrade/commit/b513941ccc3d2ec455bdb2015d077028ae1bb904))
* **ci:** keep release-please on the 0.0.x line and make v0.0.1 the first cut release ([#92](https://github.com/navaneeshnagarajan/FlintTrade/issues/92)) ([386d4ab](https://github.com/navaneeshnagarajan/FlintTrade/commit/386d4ab30f9c8355e755a546bbec398d38d523cc))
* **ci:** keep required Test checks reachable ([#148](https://github.com/navaneeshnagarajan/FlintTrade/issues/148)) ([af8b501](https://github.com/navaneeshnagarajan/FlintTrade/commit/af8b5012200ef17e8b06b7760444e1e168ae94a1))
* **ci:** pin release-please's initial release to v0.0.1 ([#93](https://github.com/navaneeshnagarajan/FlintTrade/issues/93)) ([a287241](https://github.com/navaneeshnagarajan/FlintTrade/commit/a28724192be8f1726471832690542d3320ddc9b0))
* **ci:** seal macOS bundles, guard installer sizes, drop sidecar stubs ([4539607](https://github.com/navaneeshnagarajan/FlintTrade/commit/4539607679945123d7095e146a268c4298ce3a0a))
* **ci:** skip Identity H8 on push-to-main and harden nightly platform tests ([#140](https://github.com/navaneeshnagarajan/FlintTrade/issues/140)) ([6da0510](https://github.com/navaneeshnagarajan/FlintTrade/commit/6da0510e95a697edc97473a25cd5b479bd42f4ff))
* **ci:** unblock installer rebuilds for the current release tag ([5d9b66c](https://github.com/navaneeshnagarajan/FlintTrade/commit/5d9b66c50234761fbc17abd9d83d227b81aa1a5e))
* clear the three flagged residuals + a latent PIN-error bug ([05f3f58](https://github.com/navaneeshnagarajan/FlintTrade/commit/05f3f58a5426f77e5c4019f87c5b9137413f90b2))
* close the re-audit residuals — abandonable reflection thread, recursive redaction, safe clear-token ordering ([b0422aa](https://github.com/navaneeshnagarajan/FlintTrade/commit/b0422aa636eb97e718982a9d400fc40743bd86c5))
* **core,gateway,screener:** backend hygiene — locking, retention, dedupe, fail-closed classification ([e10a821](https://github.com/navaneeshnagarajan/FlintTrade/commit/e10a82167e38c3a696610f569884f82bfa1ea406))
* **core,terminal:** feed the persistent latency monitor and label session-scoped stats (U12) ([8ecde17](https://github.com/navaneeshnagarajan/FlintTrade/commit/8ecde178817e362615c7e5b7361f501360ca4149))
* **core:** bind authenticated rate limits to verified JWT ([#160](https://github.com/navaneeshnagarajan/FlintTrade/issues/160)) ([ceb936a](https://github.com/navaneeshnagarajan/FlintTrade/commit/ceb936aa16b34fbed261ad706b43bade8f3cba72))
* **core:** bind native mutations to generations ([17c4018](https://github.com/navaneeshnagarajan/FlintTrade/commit/17c4018bcd0ebea1d3f75c110650118091d33a21))
* **core:** close runtime ownership safely ([b870f0e](https://github.com/navaneeshnagarajan/FlintTrade/commit/b870f0e6bdca3613573e401fb23d433b56416930))
* **core:** close shutdown publication races ([def547d](https://github.com/navaneeshnagarajan/FlintTrade/commit/def547d4815b2a77a7c48da12940025166603c5b))
* **core:** defer unrecovered recorder failures ([a347803](https://github.com/navaneeshnagarajan/FlintTrade/commit/a3478039deb7e9f8ba31263b30bf354722a51257))
* **core:** drain admitted requests on shutdown ([18f27ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/18f27ef00b311c64a3401bcd6113ecd124a1832f))
* **core:** fail closed on stale market calendars ([90e3f10](https://github.com/navaneeshnagarajan/FlintTrade/commit/90e3f10f1dd7190377bc9e0bc07366f283b68c6b))
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
* **core:** Windows DACL and ollama-runtime root causes, docker profiles, log writer, repo-wide follow-ups ([#103](https://github.com/navaneeshnagarajan/FlintTrade/issues/103)) ([e870071](https://github.com/navaneeshnagarajan/FlintTrade/commit/e8700713d43b8b2e30ad08f9412baf9de95da017))
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
* **desktop:** announce second launches and align workspace env resolution ([ec51710](https://github.com/navaneeshnagarajan/FlintTrade/commit/ec5171098da39840104049526406bf60295a8d00))
* **desktop:** bound sidecar supervision safely ([9123a0a](https://github.com/navaneeshnagarajan/FlintTrade/commit/9123a0abdfc7fd325a3ab33d23a2829c62c52e79))
* **desktop:** close Electron scaffold review gaps ([c4a80f4](https://github.com/navaneeshnagarajan/FlintTrade/commit/c4a80f4544e8baa4447c29cfc234aa6b59887e38))
* **desktop:** close orphan-window and journal-growth review findings ([5db6999](https://github.com/navaneeshnagarajan/FlintTrade/commit/5db6999cdffa4f5fa8cddb7099e6a7218294ac7f))
* **desktop:** close sidecar identity races ([aac965e](https://github.com/navaneeshnagarajan/FlintTrade/commit/aac965ef1c1d7b4a0a6ece3323742fb5ccd8e4ff))
* **desktop:** close source bootstrap review gaps ([0ffbb2f](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ffbb2fc49ac8d8296e6d02b4d575dd9ae8022e7))
* **desktop:** close source lifecycle audit findings ([d678124](https://github.com/navaneeshnagarajan/FlintTrade/commit/d678124d1fcb094a4873735ccade3d32e6e94021))
* **desktop:** close Task 8 adversarial review findings ([8c9e054](https://github.com/navaneeshnagarajan/FlintTrade/commit/8c9e054d5ffcf96f691231c359bbd83592d25f7d))
* **desktop:** close the uninstall-wave review findings ([a0500b3](https://github.com/navaneeshnagarajan/FlintTrade/commit/a0500b38fd296f3c5c2f85762762437cbd50f05a))
* **desktop:** close the verification-round findings on the uninstall purge path ([644a994](https://github.com/navaneeshnagarajan/FlintTrade/commit/644a994f9a4adeb41294ed949210c3e2560daf40))
* **desktop:** contain backend process tree ([b868fb0](https://github.com/navaneeshnagarajan/FlintTrade/commit/b868fb09b595983f09283d3840e275687fde175e))
* **desktop:** default the Linux DMA-BUF workaround, name antivirus blocks, honour system proxies ([cab251a](https://github.com/navaneeshnagarajan/FlintTrade/commit/cab251af56c741309b5a4601c03d4d0e25cf0066))
* **desktop:** drop splash nosniff header per re-review ([2627091](https://github.com/navaneeshnagarajan/FlintTrade/commit/2627091b120d3c63dcfa1533db9d2f2ed0ace797))
* **desktop:** fail closed on stale sidecars ([162774b](https://github.com/navaneeshnagarajan/FlintTrade/commit/162774bdaa4c004045f4f9d16e45b7610c89b3fa))
* **desktop:** finish Electron migration with canonical app branding ([#101](https://github.com/navaneeshnagarajan/FlintTrade/issues/101)) ([fa50732](https://github.com/navaneeshnagarajan/FlintTrade/commit/fa50732fa86224ea58e8be4f57449ac78ee18016))
* **desktop:** flush tick capture on shutdown ([4b879a0](https://github.com/navaneeshnagarajan/FlintTrade/commit/4b879a03706edb7db37206ece14d1a527db1a221))
* **desktop:** give the backend real shutdown grace when the shell dies ([e4889c3](https://github.com/navaneeshnagarajan/FlintTrade/commit/e4889c38164b408c6c7a5d99b349f0cf41b3c05c))
* **desktop:** harden sidecar ownership and recovery ([dae24d1](https://github.com/navaneeshnagarajan/FlintTrade/commit/dae24d1955e532e7a8f483054785568f135911f5))
* **desktop:** harden source bootstrap recovery ([2309553](https://github.com/navaneeshnagarajan/FlintTrade/commit/23095535c6895673ee1ad7038680255352918b76))
* **desktop:** harden splash CSP, seed source revision, mandate native identity ([0840b8f](https://github.com/navaneeshnagarajan/FlintTrade/commit/0840b8f7d44ca575a76885a7a1b89387cdace5ab))
* **desktop:** harden the boot-attempt lifecycle against races and dead ends ([ef76c9a](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef76c9a73c6d0c345673737c1762ae6b5f47fcf5))
* **desktop:** heartbeat the splash during a slow first-boot migration ([fce0027](https://github.com/navaneeshnagarajan/FlintTrade/commit/fce0027404ad5825f55eb575af91d14a1753ac10))
* **desktop:** keep supervising detached sidecar ([b4b06c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b4b06c8a2b9dc72496a58ede45adaa34cbc4b599))
* **desktop:** make first-run progress actually reach the splash ([4760224](https://github.com/navaneeshnagarajan/FlintTrade/commit/47602249d5965d8e1ba420fa8398b9a3f1e70e9e))
* **desktop:** make POSIX containment work on pidfd-less builds and dying parents ([d1d0a25](https://github.com/navaneeshnagarajan/FlintTrade/commit/d1d0a2528c3074d3d305d95b4ab7fcc795472d02))
* **desktop:** propagate backend shutdown failures ([9aaa157](https://github.com/navaneeshnagarajan/FlintTrade/commit/9aaa1575e445fec7cf44652b29187e6d633c24dd))
* **desktop:** remove three first-run wedge/abort paths in the harness ([74235b1](https://github.com/navaneeshnagarajan/FlintTrade/commit/74235b1bcfe6b0562a106cf49d14d48f2edff605))
* **desktop:** retain frozen backend ownership ([b245a95](https://github.com/navaneeshnagarajan/FlintTrade/commit/b245a9550d83e58f47fcd883cb9db5aead7265d1))
* **desktop:** retain tick storage across flush retries ([d952514](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9525145ceaa55d44ace2ff5fce89694df0a3917))
* **desktop:** revive the dead pre-start cancel patterns, and two flagged follow-ups ([#116](https://github.com/navaneeshnagarajan/FlintTrade/issues/116)) ([5ef8af0](https://github.com/navaneeshnagarajan/FlintTrade/commit/5ef8af0123cc3ee614f238503f71e06f77714e5a))
* **desktop:** self-heal the stale-sidecar wedge and auto-upgrade stale payloads ([4c65b39](https://github.com/navaneeshnagarajan/FlintTrade/commit/4c65b39eee4c501cf1ac5b607968302e0a7fb607))
* **desktop:** skip unparseable /proc rows in the containment snapshot ([22207e0](https://github.com/navaneeshnagarajan/FlintTrade/commit/22207e007f267e291feab845da3ef359a447691d))
* **desktop:** stop a broken shell pipe from killing the orphan watchdog ([d11add2](https://github.com/navaneeshnagarajan/FlintTrade/commit/d11add24df7e01941eb844d277394b35f159d89e))
* **desktop:** stop Quit from freezing the app for the whole shutdown budget ([5d6b463](https://github.com/navaneeshnagarajan/FlintTrade/commit/5d6b4636062a8196d15d8df9a23fa05cc41151a9))
* **desktop:** stop recycled PIDs and legacy records from wedging startup ([45bc52c](https://github.com/navaneeshnagarajan/FlintTrade/commit/45bc52c3e32bccb5d6b02cfd77a6e38297b53032))
* **desktop:** uv ships a flat Windows zip, so stop expecting a nested path ([#107](https://github.com/navaneeshnagarajan/FlintTrade/issues/107)) ([acf0d19](https://github.com/navaneeshnagarajan/FlintTrade/commit/acf0d1953bad78e5da5207df811914057d7d2d96))
* **desktop:** verify source content after builds ([2dc5592](https://github.com/navaneeshnagarajan/FlintTrade/commit/2dc5592ba9f4c971fd4906a7f4214aae86d2f6a4))
* **dhan:** add native LTP, OHLC and quote details ([#152](https://github.com/navaneeshnagarajan/FlintTrade/issues/152)) ([e95b390](https://github.com/navaneeshnagarajan/FlintTrade/commit/e95b390dafcb3e2d53b5f46f61a5cf3b8c3ba8e1))
* **ditto:** guarantee mirror deactivation when emergency flatten is declined ([157241d](https://github.com/navaneeshnagarajan/FlintTrade/commit/157241d398bb5de94108c709581d4b5746f48d71))
* **ditto:** thread operator trading mode into the mirror, fail closed on non-live ([f239893](https://github.com/navaneeshnagarajan/FlintTrade/commit/f23989356ec17f6aa63ac01a2c4e43d807937ad9))
* **engine,core:** never let a dead intent journal veto the emergency flatten ([ad108fd](https://github.com/navaneeshnagarajan/FlintTrade/commit/ad108fdb568f8ec86abb40d1da3c15feb32b0486))
* **engine,desktop:** own strategy process lifecycles ([eb749fc](https://github.com/navaneeshnagarajan/FlintTrade/commit/eb749fc1f2a373cf775716029592949922c11c1d))
* **engine,terminal:** reject fabricated 0.0 sandbox fills (G14) ([ef67d64](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef67d643383ebe87cef25d03c19e389b21003fcc))
* **engine:** fail-close interrupted Action Centre dispatches on restart ([82741b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/82741b809000a251f5c975b5fcf95db9756b0157))
* **engine:** make basket/split executors synchronous (WSGI parity, adversarial finding) ([bf514d2](https://github.com/navaneeshnagarajan/FlintTrade/commit/bf514d25e521bcf05e0a91fdb122f7912f60f5d7))
* **engine:** preserve scheduled market context ([7cd648d](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cd648d933b7f9a48c4dd1424c9b3e89527ca813))
* **gateway:** preserve Upstox special sessions ([76fcfb2](https://github.com/navaneeshnagarajan/FlintTrade/commit/76fcfb24a47a30aa9db7fc61ac9462d8191c41d3))
* **gateway:** revoke stale router generations ([6b3e54a](https://github.com/navaneeshnagarajan/FlintTrade/commit/6b3e54a8b2552dabd6fd4fc907380fb78d1ad567))
* **gateway:** stage native credential changes ([d010d63](https://github.com/navaneeshnagarajan/FlintTrade/commit/d010d63669c4f08fe9f4f54cf743c5b594c519cb))
* **honesty:** sample data declares itself + WS unsubscribe refcounting ([6fdc6a8](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fdc6a880a1c22ebaa94b79ee97fcde595ad1fc7))
* **infra,docs:** unstrand beta installs, add RPM depends, fix Sequoia install steps ([118ac20](https://github.com/navaneeshnagarajan/FlintTrade/commit/118ac20deb97e726d20d8c021ea7458687f37e9c))
* **infra:** make the macOS one-command install actually mount and install the DMG ([d071860](https://github.com/navaneeshnagarajan/FlintTrade/commit/d071860b74459ed185e3df5d1abfe25faece957c))
* **infra:** make the one-command installs survive real machines ([74add58](https://github.com/navaneeshnagarajan/FlintTrade/commit/74add582603ab9c54ad00621975c689ae148ecdd))
* **install:** close the Codex review findings merged unread on [#102](https://github.com/navaneeshnagarajan/FlintTrade/issues/102) and [#103](https://github.com/navaneeshnagarajan/FlintTrade/issues/103) ([#105](https://github.com/navaneeshnagarajan/FlintTrade/issues/105)) ([902107e](https://github.com/navaneeshnagarajan/FlintTrade/commit/902107ebf52a097598d828a6b01bdfd2416bbb11))
* **install:** harden headless consent() + trusted-URL windows dry-run fixture ([41831e2](https://github.com/navaneeshnagarajan/FlintTrade/commit/41831e2a4c4599304ec46e6517a4ebab545a92ff))
* **install:** harden Windows admission and cross-platform reinstalls ([#118](https://github.com/navaneeshnagarajan/FlintTrade/issues/118)) ([9640e4c](https://github.com/navaneeshnagarajan/FlintTrade/commit/9640e4cf0bea5666011e735fede0d18640785d87))
* **install:** native Windows install path, zero-prereq web installer, unified install/uninstall contract ([#102](https://github.com/navaneeshnagarajan/FlintTrade/issues/102)) ([9929461](https://github.com/navaneeshnagarajan/FlintTrade/commit/9929461a6d3905b5806cb3a482b56dc9a5650bd7))
* **install:** systemd unit vs setup-production.sh mismatch ([#158](https://github.com/navaneeshnagarajan/FlintTrade/issues/158)) ([6075b61](https://github.com/navaneeshnagarajan/FlintTrade/commit/6075b61e7efdfd8422b677530c496fc1355e389c))
* **journal:** thread-safety + P&L/date/import correctness (G31 verify) ([1108437](https://github.com/navaneeshnagarajan/FlintTrade/commit/11084378ccdd522d47a9a15da4301c408f76d602))
* **kotakneo:** require explicit write acknowledgements ([#150](https://github.com/navaneeshnagarajan/FlintTrade/issues/150)) ([0ba4d2e](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ba4d2e8c2960bcd26e65e00a26ac061278b7f29))
* **openalgo:** align with v2.0.2.2 contracts ([#153](https://github.com/navaneeshnagarajan/FlintTrade/issues/153)) ([a31040a](https://github.com/navaneeshnagarajan/FlintTrade/commit/a31040ae63c0fa65bb99dd52dd1cb427348f375b))
* **orders:** align native GTT management ([6e9fe3c](https://github.com/navaneeshnagarajan/FlintTrade/commit/6e9fe3cf24b30815ed8888ef2fd1d5b67772b231))
* **orders:** close the GTT review findings — SL prefill, honest refusals, flag verification ([ef22654](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef226547f3bfb2b02db650417a1df32e5411fb38))
* **probe:** mark Upstox analytics tokens read-only ([20f535c](https://github.com/navaneeshnagarajan/FlintTrade/commit/20f535cc3949f06d30797fb79bb884b0c7bae5ef))
* **probe:** resolve Dhan symbols for live reads ([58ba9e2](https://github.com/navaneeshnagarajan/FlintTrade/commit/58ba9e29f8b770bb379fdb9241db5826c5733a35))
* **release,site:** case-correct readme guard path and complete the fallback shape ([370319f](https://github.com/navaneeshnagarajan/FlintTrade/commit/370319f3366dd0b4e58669f8b6b4505cc9ece3b7))
* **release:** keep uv.lock and NOTICE in step with version propagation ([3f8721a](https://github.com/navaneeshnagarajan/FlintTrade/commit/3f8721a84911473a2f5a38289065f2b2b5c7f64f))
* **release:** stamp the stability disclaimer into generated release notes ([730c580](https://github.com/navaneeshnagarajan/FlintTrade/commit/730c5801e0f1e901a93bc7bcb72b90c53e15816f))
* remediate the wave audit — learning-loop retrieval/timing, Telegram atomicity/redaction, honest provenance banners ([567bd67](https://github.com/navaneeshnagarajan/FlintTrade/commit/567bd67dd244e80a20b09e55c340ff12806c3a23))
* resolve the nine verified Codex review findings ([#94](https://github.com/navaneeshnagarajan/FlintTrade/issues/94)) ([a243f89](https://github.com/navaneeshnagarajan/FlintTrade/commit/a243f89f2f3ccf7189fd4d9c24acf8aed54caf18))
* **runtime:** gate emergency flatten and retain order flow ([1f13b3b](https://github.com/navaneeshnagarajan/FlintTrade/commit/1f13b3b7d0026ceff988256414a957e138be15b8))
* **runtime:** preserve mutable state ownership ([ff20423](https://github.com/navaneeshnagarajan/FlintTrade/commit/ff2042355904efd578460170b83c5786dd628eb2))
* **runtime:** share exchange calendar state ([2b5caee](https://github.com/navaneeshnagarajan/FlintTrade/commit/2b5caeee98c9ad4e234d2376355f8bce5fb1b399))
* **scheduling:** honour effective market sessions ([257a967](https://github.com/navaneeshnagarajan/FlintTrade/commit/257a967390a362591b58d443247e3c4074e440bf))
* **screener:** apply the Straddle P&L widget's adjustment legs ([eba9ae4](https://github.com/navaneeshnagarajan/FlintTrade/commit/eba9ae4ff9f30c66dd34d9fe41679eab1869b0a4))
* **screener:** breadth sample data can no longer carry future dates ([5daa7fc](https://github.com/navaneeshnagarajan/FlintTrade/commit/5daa7fc62bf63577a674acf15391ec2c8bc3d29c))
* **sdk:** omit empty broker digest metadata ([a02b32f](https://github.com/navaneeshnagarajan/FlintTrade/commit/a02b32f17e048b55740bfa0c6b3da8de147f5c05))
* **security:** clear all 14 open code-scanning alerts ([0b2bc18](https://github.com/navaneeshnagarajan/FlintTrade/commit/0b2bc18d14cc27fad3cf9c3a187792556418f714))
* **security:** constrain chart-prefs user_id to a safe identifier charset ([715da56](https://github.com/navaneeshnagarajan/FlintTrade/commit/715da562779df8333311b7e15e4b79fb8b579044))
* **security:** stop bracket-cancel 503 reflecting exception text ([e814198](https://github.com/navaneeshnagarajan/FlintTrade/commit/e814198530a5b04933d75a2e1f0bb4cdcd7edbb0))
* **setup:** block read-only native primary promotion ([e8f7007](https://github.com/navaneeshnagarajan/FlintTrade/commit/e8f700795311dfc53277bdc8f86c7eae0c1f5367))
* **setup:** require write-capable broker for native completion ([c425fc5](https://github.com/navaneeshnagarajan/FlintTrade/commit/c425fc5122014300cfb3185c057a0074fdbb9653))
* **site,terminal:** isolate public-demo dotenv and fail-closed /explore ([#161](https://github.com/navaneeshnagarajan/FlintTrade/issues/161)) ([c6a293a](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6a293a269ddeaa6bc2f370d4cdfa36031fb126e))
* **site:** align homepage install cards with the AppImage-only Linux reality ([f6c39c9](https://github.com/navaneeshnagarajan/FlintTrade/commit/f6c39c9543c5eebaa2303228b7d10377e91319ae))
* **site:** make the site domain a single source of truth, and kill an Electron flake ([#108](https://github.com/navaneeshnagarajan/FlintTrade/issues/108)) ([41b2f23](https://github.com/navaneeshnagarajan/FlintTrade/commit/41b2f235babf36a02716ebe5fac76c84b032e2cf))
* **site:** rewrite repo-relative docs links to GitHub ([#159](https://github.com/navaneeshnagarajan/FlintTrade/issues/159)) ([b8c7c24](https://github.com/navaneeshnagarajan/FlintTrade/commit/b8c7c244a95a643aed3c0b13042a570ca969eff6))
* **site:** stop selling an unpublished desktop app on the homepage ([#157](https://github.com/navaneeshnagarajan/FlintTrade/issues/157)) ([cb8790a](https://github.com/navaneeshnagarajan/FlintTrade/commit/cb8790a2a282c796b3c7cd5c95cc4e9fd3fdfa7c))
* **site:** tag-agnostic download fallback and thin-shell copy ([38f8008](https://github.com/navaneeshnagarajan/FlintTrade/commit/38f800896f414ac297026bb52540052d71b2a042))
* **site:** update widget-count assertions to 102 after the G36 doc fix ([13927d7](https://github.com/navaneeshnagarajan/FlintTrade/commit/13927d7e41cd879c5adee2efb836ea0ab29f529f))
* **supply-chain:** bind audits to current locks ([00f6ea1](https://github.com/navaneeshnagarajan/FlintTrade/commit/00f6ea1489ca7c63388bdc0e9df3c32492a5eef3))
* **supply-chain:** bump crossbeam-epoch 0.9.18 -&gt; 0.9.20 (RUSTSEC-2026-0204) ([33f48d0](https://github.com/navaneeshnagarajan/FlintTrade/commit/33f48d0ef8595d35427445fb8fb9101882b89aeb))
* **supply-chain:** close 4 deferred audit gaps in the SDK provenance gates ([996fd0c](https://github.com/navaneeshnagarajan/FlintTrade/commit/996fd0cdae7c6528a64bfc260dcd3cade76b2eb6))
* **supply-chain:** regenerate stale NOTICE bundle ([18d063d](https://github.com/navaneeshnagarajan/FlintTrade/commit/18d063d272932d7640bb28c9d9e2a397796ae267))
* **terminal,core:** make OpenAlgo config backend-authoritative ([172fecc](https://github.com/navaneeshnagarajan/FlintTrade/commit/172fecc7a1116fc7f20b4928a17b83b3110eff12))
* **terminal,core:** rehydrate OpenAlgo apiKey + fail-closed live-order routing after reload ([4d1d676](https://github.com/navaneeshnagarajan/FlintTrade/commit/4d1d6769f2819db7506f0228d335298cb32b477e))
* **terminal,desktop:** post-audit — no fabricated P&L, persistent unprotected-bracket, webview origin confinement ([dd96710](https://github.com/navaneeshnagarajan/FlintTrade/commit/dd96710f265cb2eab6ceb32ff534c7e6f7210b9e))
* **terminal:** align live market signal state ([fd01278](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd012784e35c33e539877181f393cc99ef1c847a))
* **terminal:** align order-flow exchange sessions ([3cce8b2](https://github.com/navaneeshnagarajan/FlintTrade/commit/3cce8b2fab403fd29d848afe6a23993d433c9a22))
* **terminal:** badge and stabilise the Explore home account cards ([766d26a](https://github.com/navaneeshnagarajan/FlintTrade/commit/766d26a5db0f1ebf150f2b74853c448df60af03f))
* **terminal:** book partial-close realised P&L from the tradebook ([11cc78c](https://github.com/navaneeshnagarajan/FlintTrade/commit/11cc78c20d93e6b3fd296e035b7a7e83c5ffcd46))
* **terminal:** clear the demo session on a real login ([eb3a058](https://github.com/navaneeshnagarajan/FlintTrade/commit/eb3a0589f47a80c5f9025875af9eb68294d41031))
* **terminal:** close the second verify round on the migration fixes ([e7f438f](https://github.com/navaneeshnagarajan/FlintTrade/commit/e7f438f62ab1cfc401e5d028e6b6006d4476de23))
* **terminal:** close the seventeen review findings on the migration wave ([49564c0](https://github.com/navaneeshnagarajan/FlintTrade/commit/49564c069c22e5f3b29f466554a8a9ba4a8c2ddd))
* **terminal:** disclose order-flow provenance ([6d6ae67](https://github.com/navaneeshnagarajan/FlintTrade/commit/6d6ae67704a722429b72b7f7d2129b40d8d5f5b5))
* **terminal:** enable LegBuilder strategy placement over the gated basket route ([6918662](https://github.com/navaneeshnagarajan/FlintTrade/commit/691866228c61d1e7ade07ea5bc9bc1b6ce1fd196))
* **terminal:** fail closed on broker-management writes during OpenAlgo config hydration ([e0cbfda](https://github.com/navaneeshnagarajan/FlintTrade/commit/e0cbfdad812a9c4583fb42c254988659e5d73e96))
* **terminal:** give the MCX ticker commodities sample prices in Explore ([ffe59a5](https://github.com/navaneeshnagarajan/FlintTrade/commit/ffe59a5afdc4a134c3cb91b9f675d945cd0419c9))
* **terminal:** keep order-flow canvases truthful ([2770f38](https://github.com/navaneeshnagarajan/FlintTrade/commit/2770f3872260aba0c20289434c5f2e687ecfd764))
* **terminal:** keep order-flow instruments aligned ([6fefdf5](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fefdf5842b47d179edd6896220c6fee0e37d233))
* **terminal:** keep the fresh 2FA QR seed through setup and show a manual key ([af60bcd](https://github.com/navaneeshnagarajan/FlintTrade/commit/af60bcd8c58f84c3fc0c13eb7390eea9b64ed694))
* **terminal:** keep the kill switch available on a failed safety refresh ([d7f4e4b](https://github.com/navaneeshnagarajan/FlintTrade/commit/d7f4e4bc9a8aa25aeb4ea28581593ce456b1ae8e))
* **terminal:** make AI Advisor approvals gated, authenticated and honest ([49a4fdd](https://github.com/navaneeshnagarajan/FlintTrade/commit/49a4fddc0741801a05166c5861b3cda389c54017))
* **terminal:** make the daily trading loop honest and operable ([dc63373](https://github.com/navaneeshnagarajan/FlintTrade/commit/dc63373249b93e9d23b742098faa4c2e04891c7d))
* **terminal:** merge setup broker label flow ([81818c7](https://github.com/navaneeshnagarajan/FlintTrade/commit/81818c7f6ed849711b72ebe1c2e9a8a45f8fe8fc))
* **terminal:** name the Action Centre's producer in its empty state ([e2060e1](https://github.com/navaneeshnagarajan/FlintTrade/commit/e2060e12b2615ab88d88f52b4509ffe7caf88ce4))
* **terminal:** preserve authenticated live feeds ([7f42fce](https://github.com/navaneeshnagarajan/FlintTrade/commit/7f42fce64ccb74d7815b90290682f4727def0778))
* **terminal:** preserve compact market-data controls ([afe1afb](https://github.com/navaneeshnagarajan/FlintTrade/commit/afe1afb8c16e09d07826dfd0ac1fdfff1dac7ef1))
* **terminal:** preserve live data provenance ([d9beefd](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9beefda17c4c2a56e274be6d22e50d44d0156c7))
* **terminal:** purge persisted 'Broker gateway connected' spam on load ([a54fa89](https://github.com/navaneeshnagarajan/FlintTrade/commit/a54fa8977a30e8e1da60fd958d36c43529aa136e))
* **terminal:** read index LTPs from their *_INDEX atom keys in OrderPad ([d83a67e](https://github.com/navaneeshnagarajan/FlintTrade/commit/d83a67e1dd33714cbec29ca7fbf1df8541ea8bdf))
* **terminal:** reconcile emergency runtime state ([7c4cf6a](https://github.com/navaneeshnagarajan/FlintTrade/commit/7c4cf6a6863780f3181d41f674c2ac978d3ce3fa))
* **terminal:** restore usable chrome, contrast, and overflow ([1f04d61](https://github.com/navaneeshnagarajan/FlintTrade/commit/1f04d61259197ca56534911a3e5cc3675ac38db6))
* **terminal:** route native ltp quote details ([904ceaa](https://github.com/navaneeshnagarajan/FlintTrade/commit/904ceaa6295dd5460d9804347fa2603a675684b9))
* **terminal:** serve sample expiries and option chain in Explore ([b5483cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/b5483cf947531e92fea228c95e209f2e2cc436dd))
* **terminal:** setup and settings traps — honest defaults, no premature commits ([48f2498](https://github.com/navaneeshnagarajan/FlintTrade/commit/48f249844c794e7cb8044121ba0a5d5c67d5f26d))
* **terminal:** share the index tick-key normalisation with OrderLadder ([99ed101](https://github.com/navaneeshnagarajan/FlintTrade/commit/99ed101192b9d6424cffa2e3dd35793ca202efe7))
* **terminal:** stop the false 'broker gateway connected' spam in Explore ([3ecd23f](https://github.com/navaneeshnagarajan/FlintTrade/commit/3ecd23f53918eea10a7773a4f3e2f660e676301a))
* **terminal:** validate market-data provenance ([0625e90](https://github.com/navaneeshnagarajan/FlintTrade/commit/0625e903dfb9d112b01174e5e758145c61f066e6))
* **test:** seed the test master password from one hardened implementation ([#113](https://github.com/navaneeshnagarajan/FlintTrade/issues/113)) ([072a228](https://github.com/navaneeshnagarajan/FlintTrade/commit/072a228ee313b710a899fd325acec0df09479a63))
* **test:** stop the scratch sweeper deleting live workers' workspaces ([#115](https://github.com/navaneeshnagarajan/FlintTrade/issues/115)) ([d31c43c](https://github.com/navaneeshnagarajan/FlintTrade/commit/d31c43cb682fc86182350f02ff2f83fe73d35a52))
* **ticks:** preserve PyO3 extraction contracts ([59fbc67](https://github.com/navaneeshnagarajan/FlintTrade/commit/59fbc676502092b88ed71e805d15a9b61b99575c))
* **ticks:** reject unsafe spread arithmetic ([569dad7](https://github.com/navaneeshnagarajan/FlintTrade/commit/569dad74715f074e0fdbaf6238de1462fa3f8044))
* **ticks:** validate spread batches before parallel work ([c90d246](https://github.com/navaneeshnagarajan/FlintTrade/commit/c90d2461d4c5e8c358092d0e87cb777e149576a7))
* **ticks:** validate spread batches before rayon ([7aeb937](https://github.com/navaneeshnagarajan/FlintTrade/commit/7aeb937cdb3a17cb604c16edcf6d3d30f693b555))
* **ticks:** validate spread batches deterministically ([f54ae95](https://github.com/navaneeshnagarajan/FlintTrade/commit/f54ae95ed19647372577574535acabe8568fb2fb))
* **web:** serve installed frontend assets cross-platform ([#119](https://github.com/navaneeshnagarajan/FlintTrade/issues/119)) ([dec2393](https://github.com/navaneeshnagarajan/FlintTrade/commit/dec2393c980bf63b1138f70461df9aafa66baa88))
* Windows correctness bugs, toolchain refresh, and the gates that would have caught them ([#112](https://github.com/navaneeshnagarajan/FlintTrade/issues/112)) ([506f180](https://github.com/navaneeshnagarajan/FlintTrade/commit/506f18018a221601fc11dc2d3f13e95ca644bf43))


### Changed

* **ai:** retire duplicate memory manager logic ([c4b9686](https://github.com/navaneeshnagarajan/FlintTrade/commit/c4b9686d51268d66fae3a57cf32f286a53f393a5))
* **ai:** retire duplicate ML advisor chain ([73880fa](https://github.com/navaneeshnagarajan/FlintTrade/commit/73880fa0daac503845650c08489cc2eb3753653c))
* **ai:** retire duplicate ML advisor chain ([068084c](https://github.com/navaneeshnagarajan/FlintTrade/commit/068084ca98378837a89aa86bc6a38883e829b986))
* **ai:** retire duplicate sentiment modules ([5876e1f](https://github.com/navaneeshnagarajan/FlintTrade/commit/5876e1fcd265f031719c6573f8d1dcf2139725ef))
* **ai:** retire duplicate team orchestrators ([472a852](https://github.com/navaneeshnagarajan/FlintTrade/commit/472a8521a05fd3076da764492b5311e99fc97c23))
* **ai:** retire duplicate trade reflector ([cad1f58](https://github.com/navaneeshnagarajan/FlintTrade/commit/cad1f58ede90f62839030abe0ae402585b3b967e))
* **ai:** retire empty signal routes ([4d78b15](https://github.com/navaneeshnagarajan/FlintTrade/commit/4d78b15e96b3d60e44ba0d21b938cfcf9fef9bd4))
* **ai:** retire the duplicate RAG implementation ([e385ff6](https://github.com/navaneeshnagarajan/FlintTrade/commit/e385ff6ba9c6de88ca6a230beaf6d74fee3caaaa))
* **automation:** one sliding-window alert rate limiter — U16 dedup ([2a2b6be](https://github.com/navaneeshnagarajan/FlintTrade/commit/2a2b6beb9ad30e79a3dacd6c4d1f1ca316e2768b))
* **core:** drop the unused ollama loopback-port helper ([770998c](https://github.com/navaneeshnagarajan/FlintTrade/commit/770998ccedad673d316368b37b19ed364c9b0e4e))
* **core:** one canonical expiry parser — U15 closed ([6c2e2f2](https://github.com/navaneeshnagarajan/FlintTrade/commit/6c2e2f2dd4d564adf9befa6e995e39c3963c2acc))
* **data:** remove the redundant audit-export blueprint after verifying the merge ([d100312](https://github.com/navaneeshnagarajan/FlintTrade/commit/d100312673e891a66e207bb3839caa54b1d08938))
* **desktop:** cut the electron bootstrap suite's fixture tax ([#91](https://github.com/navaneeshnagarajan/FlintTrade/issues/91)) ([ae1d59a](https://github.com/navaneeshnagarajan/FlintTrade/commit/ae1d59a3f6452aa45a053255eb1495b8cf6fce6b))
* **ditto:** store account api_keys in the canonical credential vault ([31eae8e](https://github.com/navaneeshnagarajan/FlintTrade/commit/31eae8e698bf7954c9b879078d659210bc5e37a8))
* **engine:** drop the superseded legacy emergency dispatcher ([8cd2e2b](https://github.com/navaneeshnagarajan/FlintTrade/commit/8cd2e2b284a912f5e001f5ce178b1a4ee65c238d))
* **gateway:** add BrokerRouter.default_selector accessor ([0ab2c6c](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ab2c6c3723beac9cd24cabe49bd308af3e8f177))
* **infra,core:** merge deploy scripts and retire the v1_compat shim ([3e934c2](https://github.com/navaneeshnagarajan/FlintTrade/commit/3e934c2183e504e23017944bad894830a70454cb))
* **orders:** collapse order routing to the single gated surface ([b1c66b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b1c66b83d29c564e8a9f3f0c149fdbc38af7c6a7))
* **terminal:** dedupe getFtBase onto the shared ftApi helper (U8 tail) ([62ed4ff](https://github.com/navaneeshnagarajan/FlintTrade/commit/62ed4ffb21fd8ac42e6023dee23238b5787696d8))
* **terminal:** IntradayPnL consumes the shared positions/tradebook caches (U10 complete) ([afbf504](https://github.com/navaneeshnagarajan/FlintTrade/commit/afbf504c5c054aa6e7d231841b60995038901ed4))
* **terminal:** merge duplicate widgets 102 → 69, retire five integrations ([#71](https://github.com/navaneeshnagarajan/FlintTrade/issues/71)) ([b585be8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b585be88e560439f87819060c714b473c6c3ada1))
* **terminal:** route the last hardcoded /ft-api fetches through getBase ([a6ee786](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6ee786e721b316fe0a130a6ff860873ba52d6d4))

## [Unreleased]

### Fixed

- **Production systemd install.** `infra/scripts/setup-production.sh` hardcodes
  `/opt/flinttrade` (the prefix `flinttrade.service` already uses), refuses
  `FLINTTRADE_DIR`, symlink targets and non-git trees, and requires Python
  >= 3.12 before creating `$INSTALL_DIR/.venv`. The unit exports
  `FLINTTRADE_WORKSPACE_DIR=/opt/flinttrade/.flinttrade` so Workspace writes
  stay inside `ReadWritePaths`, `FLINTTRADE_BACKEND_PORT`, and starts
  `python -m flinttrade_core.app` with every workspace package on
  `PYTHONPATH`. First-time setup (and later deploys) build
  `packages/apps/terminal/dist` with the pinned pnpm and run
  `python -m flinttrade_core.cli init --provision-master-password` as
  `www-data`, so the non-interactive backend can start and serve the UI.
  Checkout-mode normalisation skips `.flinttrade` and `data` so hardened
  `0600` secrets stay owner-only. Code and `.venv` stay root-owned; only
  runtime workspace/data/log paths are `www-data`. `infra/scripts/deploy.sh`
  updates that tree with `sudo git` and does not take ownership.



- **Workspace path unification.** Nineteen modules resolved their own storage as
  the literal `~/.flinttrade` instead of asking `flinttrade_core.workspace`. On
  Linux that happens to be the workspace, so it never failed in CI; on macOS
  (`~/Library/Application Support/flinttrade`) and Windows (`%APPDATA%\flinttrade`)
  every one of them wrote to a second, invisible directory that the rest of the
  app did not read and the uninstaller could not find. Affected state included
  the TOTP secret store and its install key, the trade journal and its
  screenshots, saved presets, keyboard shortcuts, quantity-freeze limits, the
  pending-order approval queue, the watchlist, expiry and FII/DII stores, and the
  operator's own FlowBuilder flows, trained signal models and strategy files.

  Every module now resolves its path inside a function body at call time, so
  `FLINTTRADE_WORKSPACE_DIR` and `FLINTTRADE_HOME` are honoured on every
  construction rather than frozen at import. On a default install each artefact
  is **copied** into the platform workspace once, under a cross-process lock; the
  pre-workspace original is left untouched, so the upgrade is reversible. Where a
  workspace copy already exists it wins and no merge is attempted — an
  approval-queue merge could dispatch the same order twice. The TOTP store and
  its install key move as one unit, verified by a decrypt round-trip before the
  legacy pair is trusted, and the trade journal moves with its screenshot
  directory or not at all. Migration probes are skipped entirely when a workspace
  environment override is in force.

- Both uninstallers now enumerate every pre-workspace dropping written directly
  at `~/.flinttrade/<name>` — flows, models, strategies, journal screenshots,
  presets, the TOTP pair and the remaining stores — as named `--purge`/`-Purge`
  candidates. They were deleted before, but only as part of the managed root, so
  the confirmation list never mentioned the operator's own strategy code.

- `FlowBuilder` and the trade journal no longer fall back to a home-directory
  path when `flinttrade_core` cannot be imported. A broken install now fails
  loudly and the affected routes degrade to 503, instead of silently opening an
  empty shadow store.

### Changed

- Vulnerable ChromaDB persistence is replaced by FlintTrade's local
  SQLite/NumPy vector store. Existing vector directories are deliberately not
  auto-migrated because Chroma's on-disk index and embedding space are not
  compatible with the replacement. If `chroma.sqlite3` is present, FlintTrade
  refuses to create `flinttrade_vectors.sqlite` beside it: the database and
  vector-segment files are left untouched, RAG stays disabled, and agent
  learning uses its logged in-process fallback. To recover existing lessons or
  custom documents, export them with the previous release. To intentionally
  start empty, move the complete legacy directory aside as a backup before
  restarting; do not delete individual segment files. Each collection now
  persists one embedding dimension and refuses mixed-width writes after the
  first vector, inner-product distance stays unnormalised, and shutdown joins
  the optional background RAG indexer before closing the store.

- The traffic and latency observability logs (`traffic_log.duckdb`,
  `latency_log.duckdb`) are not migrated: they are disposable, and both were
  already workspace-routed in production. On macOS and Windows their history
  restarts from empty.

## [0.0.1] — 2026-07-23

Clean-slate baseline. Pre-1.0, pre-usable, and marked as a pre-release: anything
may change without notice until the project reaches a stable 1.0.0.
