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

## 0.0.1 (2026-10-01)


### Added

* **agent:** add durable autonomous Practice harness ([#325](https://github.com/navaneeshnagarajan/FlintTrade/issues/325)) ([340bdff](https://github.com/navaneeshnagarajan/FlintTrade/commit/340bdffcd7033f3aa1423903a7dc4f58261cbe4b))
* **ai:** make the componentised RAG pipeline canonical ([850ad29](https://github.com/navaneeshnagarajan/FlintTrade/commit/850ad298e2de389cf7de0b94ec9b25a4c906fa2b))
* **ai:** operator-approved skill drafts from post-session review — AI1 ([d73fd8b](https://github.com/navaneeshnagarajan/FlintTrade/commit/d73fd8b1e02d3a4a36afd9b17cc39dbcdee224ac))
* **ai:** persist and search AI chat sessions — AI2 cross-session recall ([2a61339](https://github.com/navaneeshnagarajan/FlintTrade/commit/2a6133969f48f5e91e623fb8fa043d27c4b62c87))
* **ai:** persist the Obsidian vault path from the UI (U18 slice) ([63ae047](https://github.com/navaneeshnagarajan/FlintTrade/commit/63ae047821b5073574ae646ff4ea5218fd0945df))
* **ai:** preserve legacy advisor refinements ([548e56e](https://github.com/navaneeshnagarajan/FlintTrade/commit/548e56e7222a49053c719c6005dc26103ea437d4))
* **ai:** publish reviewed native harness foundations ([#218](https://github.com/navaneeshnagarajan/FlintTrade/issues/218)) ([e8b9c15](https://github.com/navaneeshnagarajan/FlintTrade/commit/e8b9c157b3cf5a45f505413f8e9f71b766741a1f))
* **ai:** secure canonical signal models ([3b0a5d3](https://github.com/navaneeshnagarajan/FlintTrade/commit/3b0a5d3d1f730f469f539567d4953257e52d39d6))
* **ai:** ship Chat Practice + native live-read context (FT-MONDAY-003) ([#256](https://github.com/navaneeshnagarajan/FlintTrade/issues/256)) ([0049691](https://github.com/navaneeshnagarajan/FlintTrade/commit/004969183fa1e4c75097cfbf640f72626378ce2c))
* **ai:** stream configurable team analyses ([8d49cc0](https://github.com/navaneeshnagarajan/FlintTrade/commit/8d49cc06cc019799a490a49515b92542cb1a8f78))
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
* **backtest:** fold the WFE ratio into the routed walk-forward path — U13 partial ([5c1a6d0](https://github.com/navaneeshnagarajan/FlintTrade/commit/5c1a6d0de174b5cfa5e3484fabcac3416203ec3e))
* **ci:** automate version bumps and releases with release-please ([2dc1e3d](https://github.com/navaneeshnagarajan/FlintTrade/commit/2dc1e3dc2a91495d28f1d06eddf87bc1691ae73b))
* **ci:** publish the frozen backend as a hash-verified payload asset ([51e0901](https://github.com/navaneeshnagarajan/FlintTrade/commit/51e0901b69726f2a6101b213d76686ced466f957))
* **ci:** sign, notarise, and emit updater artifacts when secrets exist ([44627aa](https://github.com/navaneeshnagarajan/FlintTrade/commit/44627aa658f867395a02457bad3e6ccf9ad44964))
* **core,terminal:** persist n8n bridge settings from the UI (U18 slice) ([cb8b0e9](https://github.com/navaneeshnagarajan/FlintTrade/commit/cb8b0e9a5709652a9c5fc01e413b5222ea82a5fb))
* **core,terminal:** persist Telegram bot settings from the UI (U18 slice) ([dc28c04](https://github.com/navaneeshnagarajan/FlintTrade/commit/dc28c045c66879c199f0772c1122b47d82196cbd))
* **core,terminal:** persist WhatsApp alert settings from the UI (U18 slice) ([d0bddf4](https://github.com/navaneeshnagarajan/FlintTrade/commit/d0bddf4336764a215d88ab032de9a8074eb353f0))
* **core:** add service connections and in-process BrokerReadPort ([7ac9feb](https://github.com/navaneeshnagarajan/FlintTrade/commit/7ac9feb7728f9dd85c75cc8fc6418b588bc39994))
* **core:** first-class web surface with a fail-closed remote bind ([43ca26c](https://github.com/navaneeshnagarajan/FlintTrade/commit/43ca26cef35d3a76138a0e0b937f4cea8336078e))
* **core:** migrate every module off the hardcoded ~/.flinttrade literal ([#106](https://github.com/navaneeshnagarajan/FlintTrade/issues/106)) ([ef6f3d1](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef6f3d169bcf7ec95704f537b8b80ae691ed74c6))
* **core:** pin managed Ollama sidecar to v0.35.0 ([#317](https://github.com/navaneeshnagarajan/FlintTrade/issues/317)) ([e111043](https://github.com/navaneeshnagarajan/FlintTrade/commit/e1110436592b014583049a5c63f06451f075752d))
* **core:** serve traffic stats from the persistent store — U12 complete ([555a198](https://github.com/navaneeshnagarajan/FlintTrade/commit/555a198df70633d14962bd565489b7c5a99004e8))
* **core:** stream captured ticks into live signals ([64bb985](https://github.com/navaneeshnagarajan/FlintTrade/commit/64bb985652e70c27e521904fc23ce0a897110cae))
* **data:** authenticated gated-audit PDF/CSV export + summary (G37 A3) ([2bd443c](https://github.com/navaneeshnagarajan/FlintTrade/commit/2bd443c6a687457e55e6d8f1440e945e2b70f4a8))
* **desktop:** add journalled source updater ([f3af162](https://github.com/navaneeshnagarajan/FlintTrade/commit/f3af162c1b62d8a349960f6c88ec527e6cd70dcc))
* **desktop:** add source guardian lifecycle ([3199dda](https://github.com/navaneeshnagarajan/FlintTrade/commit/3199dda695f2bc16432d8970e817691ebd0153c0))
* **desktop:** add verified source bootstrap ([c7dd3f4](https://github.com/navaneeshnagarajan/FlintTrade/commit/c7dd3f4e886a14de5291105c5cb5fa8068339078))
* **desktop:** cut over Electron distribution ([c19991b](https://github.com/navaneeshnagarajan/FlintTrade/commit/c19991bf133e3f57e6ceaae1a35e0baf92e5a54a))
* **desktop:** Electron source-bootstrap migration + clean v0.0.1 release reset ([a6f9246](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6f92464977ab03a6049ebbaf7f579c31bcf69fd))
* **desktop:** harden source mutation with native atomicity and attested updates ([0723835](https://github.com/navaneeshnagarajan/FlintTrade/commit/0723835f9e591b2575eed5bfd52fb9b65a6233ae))
* **desktop:** let the native Windows uninstaller remove all app data ([3b31935](https://github.com/navaneeshnagarajan/FlintTrade/commit/3b31935b253f503a209189469bc0064dbfdea813))
* **desktop:** manage the backend payload like the Ollama runtime ([08344ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/08344ef56deffb8947707c8ab4d82f4fb747814a))
* **desktop:** one-click native updates via tauri-plugin-updater ([5eb43c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/5eb43c81f7a1d27305c7acc92405d0ea9274a625))
* **desktop:** port Electron update experience ([44bab17](https://github.com/navaneeshnagarajan/FlintTrade/commit/44bab172324c849dacdf3de822f08833b0d93e03))
* **desktop:** retire legacy runtime ([ec01663](https://github.com/navaneeshnagarajan/FlintTrade/commit/ec01663851e71a833bcf04ac3d233eec36f6090a))
* **desktop:** scaffold Electron security waist ([296039e](https://github.com/navaneeshnagarajan/FlintTrade/commit/296039e77dc16ca027255b6addd637c78a2fd62e))
* **desktop:** ship clean uninstall scripts for macOS, Linux, and Windows ([2100234](https://github.com/navaneeshnagarajan/FlintTrade/commit/2100234491fdc68568d111fe2eab10bfd77542f1))
* **desktop:** thin-shell installers with first-run payload bootstrap ([fc6c716](https://github.com/navaneeshnagarajan/FlintTrade/commit/fc6c716ec1238d0f7126dd1883f19792be539ab1))
* **engine:** admit operator and automate orders before the safety gate ([#277](https://github.com/navaneeshnagarajan/FlintTrade/issues/277)) ([915fd40](https://github.com/navaneeshnagarajan/FlintTrade/commit/915fd409ec16d6b51b67635540510bfb62229474))
* **engine:** admit places with the Laya decision sidecar ([#296](https://github.com/navaneeshnagarajan/FlintTrade/issues/296)) ([f4093ff](https://github.com/navaneeshnagarajan/FlintTrade/commit/f4093ffa2bb6b21685936e14676f4184166879aa))
* **engine:** admit proposals through Laya before the safety gate ([#276](https://github.com/navaneeshnagarajan/FlintTrade/issues/276)) ([4aa3bb7](https://github.com/navaneeshnagarajan/FlintTrade/commit/4aa3bb793598d8aa2114b74ceb0e52cad217b00e))
* FINOS-stack migration — FlexLayout, FDC3, Perspective + full indicator restoration ([#88](https://github.com/navaneeshnagarajan/FlintTrade/issues/88)) ([94e1c50](https://github.com/navaneeshnagarajan/FlintTrade/commit/94e1c506b54699d2acf194ed405108d754e32ea9))
* **gateway:** add strict Dhan cash depth for Practice ([#327](https://github.com/navaneeshnagarajan/FlintTrade/issues/327)) ([5e34ef3](https://github.com/navaneeshnagarajan/FlintTrade/commit/5e34ef3a87aed692c2ca0b2beb6c82c88deee726))
* **infra:** one installer per OS — universal macOS DMG, per-user Windows exe, AppImage-backed Linux command ([ac918f8](https://github.com/navaneeshnagarajan/FlintTrade/commit/ac918f8d4604a6a555efaeb80098e7990c55e4bf))
* **install:** fetch release metadata from GitHub release URLs ([fd3d6cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd3d6cf98eac978c0df31b9799de96db121dd8e8))
* **kotakneo:** migrate native adapter to SDK v3 ([#285](https://github.com/navaneeshnagarajan/FlintTrade/issues/285)) ([97acf50](https://github.com/navaneeshnagarajan/FlintTrade/commit/97acf507ed464a7b7b0d8610ae39f9d6181b3807))
* **monday:** ship native Dhan + Neo Connected (read) smoke (FT-MONDAY-002) ([#257](https://github.com/navaneeshnagarajan/FlintTrade/issues/257)) ([8fc6066](https://github.com/navaneeshnagarajan/FlintTrade/commit/8fc6066150f104ebc28d8fddaba00e51aca97383))
* **practice:** ship SandboxEngine Monday fills E2E (FT-MONDAY-001) ([#255](https://github.com/navaneeshnagarajan/FlintTrade/issues/255)) ([759f31e](https://github.com/navaneeshnagarajan/FlintTrade/commit/759f31e2f73610f8d07485210e5683ff4c3cfcfe))
* **repo:** converge completed non-release work ([#132](https://github.com/navaneeshnagarajan/FlintTrade/issues/132)) ([77deb79](https://github.com/navaneeshnagarajan/FlintTrade/commit/77deb79b5cc9d35bf7fc0f50d02581bcda55a398))
* **repo:** converge completed non-release work ([#142](https://github.com/navaneeshnagarajan/FlintTrade/issues/142)) ([7712623](https://github.com/navaneeshnagarajan/FlintTrade/commit/7712623651e528e8019eb5603713fc45d89e48ed))
* **setup:** OpenAlgo-style password-first Explore; TOTP only before Live ([#185](https://github.com/navaneeshnagarajan/FlintTrade/issues/185)) ([8390d45](https://github.com/navaneeshnagarajan/FlintTrade/commit/8390d45517179c26dfe10fe656620bc2eb21acb5))
* **site:** port Graphite A1 motion with default-off Three.js ([#162](https://github.com/navaneeshnagarajan/FlintTrade/issues/162)) ([2bdad95](https://github.com/navaneeshnagarajan/FlintTrade/commit/2bdad9510b3c082dab32a2626e05530c48e9c8c6))
* **site:** web-first download page with one installer per OS ([f11e86e](https://github.com/navaneeshnagarajan/FlintTrade/commit/f11e86e2a0ed84bb494944f99ea482fd4ac0a2fa))
* **terminal:** add configurable AI team runs ([5bf61d9](https://github.com/navaneeshnagarajan/FlintTrade/commit/5bf61d935e534a7e00ebeb4d938b618d6ccc999f))
* **terminal:** apply the font-size setting to the terminal typography ([2b49957](https://github.com/navaneeshnagarajan/FlintTrade/commit/2b499574fb4852834251dbc41e95ca2890161e97))
* **terminal:** browse and search past AI sessions from the Advisor widget ([a6d8430](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6d84303f36ca6e0e76f6103f662946606fa6ef7))
* **terminal:** compute Session Stats from today's real trades ([ecd8c16](https://github.com/navaneeshnagarajan/FlintTrade/commit/ecd8c16a7610cc4018a440b23a09183e5af98384))
* **terminal:** drive the Scanner widget from real scans ([c8be818](https://github.com/navaneeshnagarajan/FlintTrade/commit/c8be818b7c278abeecd09e309a8fd5ebeaad60ea))
* **terminal:** live-back the Market Summary widget with per-section provenance ([9d73658](https://github.com/navaneeshnagarajan/FlintTrade/commit/9d736585a3ced7ffb7136ccfc4b229d21f9c63dc))
* **terminal:** make the Scanner's OI Change tab live — all four tabs now real ([cc2f28f](https://github.com/navaneeshnagarajan/FlintTrade/commit/cc2f28fbb37a55451d9a808b595590a71edcd324))
* **terminal:** move in-app saved content from WebView localStorage to the workspace ([1d1f253](https://github.com/navaneeshnagarajan/FlintTrade/commit/1d1f2537b165b263c2495a00c2a7287f5dabf9f9))
* **terminal:** one Mode honesty bar; retire per-widget Sample chips ([#273](https://github.com/navaneeshnagarajan/FlintTrade/issues/273)) ([f4de75a](https://github.com/navaneeshnagarajan/FlintTrade/commit/f4de75ac3e14491f1d5054db73d0cc1d3420ab35))
* **terminal:** operator incident strip and Live fail-closed chrome ([#272](https://github.com/navaneeshnagarajan/FlintTrade/issues/272)) ([dbf9bd1](https://github.com/navaneeshnagarajan/FlintTrade/commit/dbf9bd17b85de0bc6e5403616abac4376f3235ba))
* **terminal:** review, approve and reject skill drafts from Settings ([97cb9ce](https://github.com/navaneeshnagarajan/FlintTrade/commit/97cb9cec1023407b3189ee3ba2cab0fdf70b2d38))
* **terminal:** set the Obsidian vault path from the widget ([30b50fe](https://github.com/navaneeshnagarajan/FlintTrade/commit/30b50fe209818779c9ac6e8db0bb655981a80ef6))
* **terminal:** UI/UX overhaul — clear navigation, one page frame, readable tokens ([#309](https://github.com/navaneeshnagarajan/FlintTrade/issues/309)) ([1ce2b13](https://github.com/navaneeshnagarajan/FlintTrade/commit/1ce2b13d2f4a5bd87e334ceb8a06493d41c953ac))
* **trade:** Option Chain OI/PCR strip (FT-TRADE-012) ([#243](https://github.com/navaneeshnagarajan/FlintTrade/issues/243)) ([a58653b](https://github.com/navaneeshnagarajan/FlintTrade/commit/a58653b0d4d8b50ee2b32b7e1b3a3efcc292534a))
* **trade:** shared symbol bus from Watchlist (FT-TRADE-011) ([#240](https://github.com/navaneeshnagarajan/FlintTrade/issues/240)) ([208539e](https://github.com/navaneeshnagarajan/FlintTrade/commit/208539ec2bf8cf4bc6879708f246be9755cd8be7))
* **ux:** Mode vocabulary + desk density (FT-UX-001) ([#213](https://github.com/navaneeshnagarajan/FlintTrade/issues/213)) ([369783b](https://github.com/navaneeshnagarajan/FlintTrade/commit/369783bda26c036d0d135731706a486572abe382))
* **ux:** TopBar + ticker flex chrome (FT-UX-002) ([#241](https://github.com/navaneeshnagarajan/FlintTrade/issues/241)) ([bbb8051](https://github.com/navaneeshnagarajan/FlintTrade/commit/bbb80515a9ee01c5206d320d5a351716941b343d))


### Fixed

* **ai,terminal:** harden unified signal feed ([c35c310](https://github.com/navaneeshnagarajan/FlintTrade/commit/c35c31054ce7939849ad6792815726ce05bfef6d))
* **ai:** bind agents and training to market sessions ([e5962c4](https://github.com/navaneeshnagarajan/FlintTrade/commit/e5962c486773bed1c0dec99cbaf2191111d4f8ba))
* **ai:** Connected badge matches LLM install state (FT-AI-004) ([#250](https://github.com/navaneeshnagarajan/FlintTrade/issues/250)) ([cb0136a](https://github.com/navaneeshnagarajan/FlintTrade/commit/cb0136a21307bacb23995fe9b90655e9b6b65140))
* **ai:** harden canonical RSS compatibility ([f4ff126](https://github.com/navaneeshnagarajan/FlintTrade/commit/f4ff12698a166e336a234999d8ecaeee40a42978))
* **ai:** harden legacy signal compatibility ([91d7f48](https://github.com/navaneeshnagarajan/FlintTrade/commit/91d7f48cac8afaed3f550ce36daf3c28bfe5e605))
* **ai:** harden live signal replay and filtering ([593b787](https://github.com/navaneeshnagarajan/FlintTrade/commit/593b7870f80461f3fde62fd42e0701344b5176c3))
* **ai:** harden live signal state ([c30bd3a](https://github.com/navaneeshnagarajan/FlintTrade/commit/c30bd3a98a4a353e0be13c74aea980db3e26cb84))
* **ai:** honest unconfigured LLM state on /ai ([#205](https://github.com/navaneeshnagarajan/FlintTrade/issues/205)) ([99b3b3f](https://github.com/navaneeshnagarajan/FlintTrade/commit/99b3b3f06388b269e000024dc3957f396a20ac8f))
* **ai:** make signal model publication atomic ([07eb94d](https://github.com/navaneeshnagarajan/FlintTrade/commit/07eb94d1da64ece88b863aeed5b6680f89ca07ce))
* **ai:** preserve pre-entry agent stops ([7d6fed2](https://github.com/navaneeshnagarajan/FlintTrade/commit/7d6fed27fcfa885d0e1fd176ed5036c41ca39a0b))
* **ai:** preserve retraining policy and guards ([7501acd](https://github.com/navaneeshnagarajan/FlintTrade/commit/7501acd6046b19192cd6b7344c3fa9e70c8d005d))
* **ai:** preserve signal model integrity migration ([61fc5e5](https://github.com/navaneeshnagarajan/FlintTrade/commit/61fc5e59572f34222f903b5e88f6551cfb395604))
* **ai:** preserve source-time market semantics ([101db87](https://github.com/navaneeshnagarajan/FlintTrade/commit/101db87585da00e098303302f5a51d35ca192308))
* **ai:** preserve source-time signal integrity ([97250fa](https://github.com/navaneeshnagarajan/FlintTrade/commit/97250fa644cc2759d25b3c9c6bdb998bd6efc489))
* **ai:** preserve trustworthy signal state ([594111f](https://github.com/navaneeshnagarajan/FlintTrade/commit/594111f1584f0ed657667c8f718d9e7687b3b90c))
* **ai:** qualify live signal identities ([aa51dab](https://github.com/navaneeshnagarajan/FlintTrade/commit/aa51dabb4b72d5f2db662b73277b4888e20c5a96))
* **ai:** refresh Suggest recommendations on mood change ([#206](https://github.com/navaneeshnagarajan/FlintTrade/issues/206)) ([1403b35](https://github.com/navaneeshnagarajan/FlintTrade/commit/1403b35be6315d51f6b8fe8389f5b5e56932785f))
* **ai:** replace vulnerable ChromaDB persistence ([#154](https://github.com/navaneeshnagarajan/FlintTrade/issues/154)) ([b615d2c](https://github.com/navaneeshnagarajan/FlintTrade/commit/b615d2c8f4b97723cac0d4f68dd4251db8a6c108))
* **ai:** respect exchange lifecycle ownership ([debeb3c](https://github.com/navaneeshnagarajan/FlintTrade/commit/debeb3cac961c04dd40ce41409ae6b1b49135b44))
* **ai:** respect instrument market hours ([193275d](https://github.com/navaneeshnagarajan/FlintTrade/commit/193275dab76a39176c71f2e41f3a6eccc367636f))
* **ai:** restore assistant replies in Explore /ai chat ([#186](https://github.com/navaneeshnagarajan/FlintTrade/issues/186)) ([a4527ea](https://github.com/navaneeshnagarajan/FlintTrade/commit/a4527ea39215328c71e41a3fc9a495dad4659d43))
* **ai:** restore Connected honesty (FT-AI-004 hotfix) ([#259](https://github.com/navaneeshnagarajan/FlintTrade/issues/259)) ([4133335](https://github.com/navaneeshnagarajan/FlintTrade/commit/41333353d72ec45cde4723f1e53fe38248efb759))
* **ai:** serialise autonomous agent startup ([3416187](https://github.com/navaneeshnagarajan/FlintTrade/commit/34161877e9fb7c669cab42dedd74797b9a83e98c))
* **ai:** synchronise scheduled signal rosters ([244ba85](https://github.com/navaneeshnagarajan/FlintTrade/commit/244ba857f9e04212aaa724052da10b58a9a1998e))
* **ai:** train only on closed market data ([c863673](https://github.com/navaneeshnagarajan/FlintTrade/commit/c863673f97f4110c53b8ce6cf89dc1d02d72c2af))
* **api:** enforce session auth on all non-public routes ([#307](https://github.com/navaneeshnagarajan/FlintTrade/issues/307)) ([e029847](https://github.com/navaneeshnagarajan/FlintTrade/commit/e0298470e836e1f0a733bb45ac750b6a13ab44aa))
* **auth:** unlock restores the existing session ([#306](https://github.com/navaneeshnagarajan/FlintTrade/issues/306)) ([056f548](https://github.com/navaneeshnagarajan/FlintTrade/commit/056f548c2327139e0ed36cf2eb9a18bf700de3e9))
* **automate:** add Strategy Builder/Lab CTA on empty Monitors state ([#194](https://github.com/navaneeshnagarajan/FlintTrade/issues/194)) ([0c2638f](https://github.com/navaneeshnagarajan/FlintTrade/commit/0c2638f7cc91ec3a4f5f70e5ff04d14b134ecea3))
* **automate:** block Telegram Send Test in Explore ([#204](https://github.com/navaneeshnagarajan/FlintTrade/issues/204)) ([f0c1ab0](https://github.com/navaneeshnagarajan/FlintTrade/commit/f0c1ab0c8c2e173ddd151fea08cde1e0b55c793a))
* **automate:** Explore Execution Logs empty ≠ outage (FT-AUTO-003) ([#236](https://github.com/navaneeshnagarajan/FlintTrade/issues/236)) ([ad6a5e9](https://github.com/navaneeshnagarajan/FlintTrade/commit/ad6a5e98713ff9bdcdc2bade255fa260eb9b442b))
* **automate:** Explore Schedules Pause gated for sample jobs (FT-AUTO-004) ([#246](https://github.com/navaneeshnagarajan/FlintTrade/issues/246)) ([8eb4e11](https://github.com/navaneeshnagarajan/FlintTrade/commit/8eb4e11d3e4111a1ba1ffd5b318b41be221ee846))
* **automation,core:** quiet the no-broker market-calendar log spam + provision master password for start ([2e9c788](https://github.com/navaneeshnagarajan/FlintTrade/commit/2e9c788d90abbfc550dda6bf109c90309fbf7fe1))
* **automation:** retain live calendar references ([da2014f](https://github.com/navaneeshnagarajan/FlintTrade/commit/da2014f78987cb9a0afdbf16d0706b766647a56b))
* **chrome:** progressive TopBar collapse at ~390px ([#207](https://github.com/navaneeshnagarajan/FlintTrade/issues/207)) ([7769d57](https://github.com/navaneeshnagarajan/FlintTrade/commit/7769d57f0856fbffb25cdb4f2f64f8945c89f3f2))
* **ci:** arch-qualify the macOS updater bundle before publishing ([b513941](https://github.com/navaneeshnagarajan/FlintTrade/commit/b513941ccc3d2ec455bdb2015d077028ae1bb904))
* **ci:** clear pnpm audit and fail-closed e2e blockers ([#311](https://github.com/navaneeshnagarajan/FlintTrade/issues/311)) ([0a9cf36](https://github.com/navaneeshnagarajan/FlintTrade/commit/0a9cf36a7d4f4be8886002bc8b9abedf09840c07))
* **ci:** keep release-please on the 0.0.x line and make v0.0.1 the first cut release ([#92](https://github.com/navaneeshnagarajan/FlintTrade/issues/92)) ([386d4ab](https://github.com/navaneeshnagarajan/FlintTrade/commit/386d4ab30f9c8355e755a546bbec398d38d523cc))
* **ci:** keep required Test checks reachable ([#148](https://github.com/navaneeshnagarajan/FlintTrade/issues/148)) ([af8b501](https://github.com/navaneeshnagarajan/FlintTrade/commit/af8b5012200ef17e8b06b7760444e1e168ae94a1))
* **ci:** pin release-please's initial release to v0.0.1 ([#93](https://github.com/navaneeshnagarajan/FlintTrade/issues/93)) ([a287241](https://github.com/navaneeshnagarajan/FlintTrade/commit/a28724192be8f1726471832690542d3320ddc9b0))
* **ci:** seal macOS bundles, guard installer sizes, drop sidecar stubs ([4539607](https://github.com/navaneeshnagarajan/FlintTrade/commit/4539607679945123d7095e146a268c4298ce3a0a))
* **ci:** skip Identity H8 on push-to-main and harden nightly platform tests ([#140](https://github.com/navaneeshnagarajan/FlintTrade/issues/140)) ([6da0510](https://github.com/navaneeshnagarajan/FlintTrade/commit/6da0510e95a697edc97473a25cd5b479bd42f4ff))
* **ci:** unblock installer rebuilds for the current release tag ([5d9b66c](https://github.com/navaneeshnagarajan/FlintTrade/commit/5d9b66c50234761fbc17abd9d83d227b81aa1a5e))
* close the re-audit residuals — abandonable reflection thread, recursive redaction, safe clear-token ordering ([b0422aa](https://github.com/navaneeshnagarajan/FlintTrade/commit/b0422aa636eb97e718982a9d400fc40743bd86c5))
* **cmdk:** Explore Ctrl+K symbol search false unavailable error ([#189](https://github.com/navaneeshnagarajan/FlintTrade/issues/189)) ([f9df6e0](https://github.com/navaneeshnagarajan/FlintTrade/commit/f9df6e0e4901a96c203694f0e6105d4e0542f120))
* **core,terminal:** feed the persistent latency monitor and label session-scoped stats (U12) ([8ecde17](https://github.com/navaneeshnagarajan/FlintTrade/commit/8ecde178817e362615c7e5b7361f501360ca4149))
* **core:** bind authenticated rate limits to verified JWT ([#160](https://github.com/navaneeshnagarajan/FlintTrade/issues/160)) ([ceb936a](https://github.com/navaneeshnagarajan/FlintTrade/commit/ceb936aa16b34fbed261ad706b43bade8f3cba72))
* **core:** bind native mutations to generations ([17c4018](https://github.com/navaneeshnagarajan/FlintTrade/commit/17c4018bcd0ebea1d3f75c110650118091d33a21))
* **core:** close runtime ownership safely ([b870f0e](https://github.com/navaneeshnagarajan/FlintTrade/commit/b870f0e6bdca3613573e401fb23d433b56416930))
* **core:** close shutdown publication races ([def547d](https://github.com/navaneeshnagarajan/FlintTrade/commit/def547d4815b2a77a7c48da12940025166603c5b))
* **core:** defer unrecovered recorder failures ([a347803](https://github.com/navaneeshnagarajan/FlintTrade/commit/a3478039deb7e9f8ba31263b30bf354722a51257))
* **core:** drain admitted requests on shutdown ([18f27ef](https://github.com/navaneeshnagarajan/FlintTrade/commit/18f27ef00b311c64a3401bcd6113ecd124a1832f))
* **core:** fail closed on stale market calendars ([90e3f10](https://github.com/navaneeshnagarajan/FlintTrade/commit/90e3f10f1dd7190377bc9e0bc07366f283b68c6b))
* **core:** feed-freshness Live Delayed Sample chips (FT-CORE-002) ([#244](https://github.com/navaneeshnagarajan/FlintTrade/issues/244)) ([c3ebfad](https://github.com/navaneeshnagarajan/FlintTrade/commit/c3ebfad9852752552eb4888d8237a8c836db8771))
* **core:** isolate leaked API keys in proofless factory tests ([#229](https://github.com/navaneeshnagarajan/FlintTrade/issues/229)) ([7a2a02b](https://github.com/navaneeshnagarajan/FlintTrade/commit/7a2a02bca39d432b712f7b7b7b183c4cc405d71c))
* **core:** make native account mutations transactional ([710d698](https://github.com/navaneeshnagarajan/FlintTrade/commit/710d69817568e8c663a1f43a213129874ea6c71d))
* **core:** make native account swaps transactional ([c6a51a1](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6a51a150c1b77123fdce487fa6619f7ab2126a9))
* **core:** own autonomous agent market sessions ([37e313b](https://github.com/navaneeshnagarajan/FlintTrade/commit/37e313bec7b38ec0d4472db5f4ecefe2b63148ac))
* **core:** preserve shared OpenAlgo lifecycle ([134d305](https://github.com/navaneeshnagarajan/FlintTrade/commit/134d30555b3743a7c1c25def10f83e4b52e21fa0))
* **core:** quiesce live-order owners before retirement ([2fa486b](https://github.com/navaneeshnagarajan/FlintTrade/commit/2fa486b3bdfe3e9c4adb36c0d51b3e0d09ddec36))
* **core:** quiesce runtime before request drain ([fd5f923](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd5f923e6d0f7ca91ef6b5c75f62aae88350c215))
* **core:** require a session JWT on Ditto management writes ([86b5871](https://github.com/navaneeshnagarajan/FlintTrade/commit/86b5871bcf54324fdd213c70f39f21ab60ed45fe))
* **core:** retain late-session retraining work ([7facb68](https://github.com/navaneeshnagarajan/FlintTrade/commit/7facb689c4505bcb450b5ef110275046d78a638c))
* **core:** retire runtime generations safely ([10749b1](https://github.com/navaneeshnagarajan/FlintTrade/commit/10749b1cf4b98fc7e46d6d752b90c8e6c9fcf67a))
* **core:** SEBI CAS session clock / TopBar phases (FT-CORE-001) ([#235](https://github.com/navaneeshnagarajan/FlintTrade/issues/235)) ([b42e375](https://github.com/navaneeshnagarajan/FlintTrade/commit/b42e375d0842e5018c615cb6a44c20bb05f116d8))
* **core:** serialise runtime ownership shutdown ([28799b9](https://github.com/navaneeshnagarajan/FlintTrade/commit/28799b9d34a60114ce34af49f41c273b9b029015))
* **core:** serialise workspace updates ([ebe0710](https://github.com/navaneeshnagarajan/FlintTrade/commit/ebe071061257ba02e06ecfc93800a6ad9e2cf7d0))
* **core:** stop clear-text logging of secrets in service connection tests ([#177](https://github.com/navaneeshnagarajan/FlintTrade/issues/177)) ([0caa239](https://github.com/navaneeshnagarajan/FlintTrade/commit/0caa2391108ab6aca8b6a0e4723ce074bb330e09))
* **core:** Windows DACL and ollama-runtime root causes, docker profiles, log writer, repo-wide follow-ups ([#103](https://github.com/navaneeshnagarajan/FlintTrade/issues/103)) ([e870071](https://github.com/navaneeshnagarajan/FlintTrade/commit/e8700713d43b8b2e30ad08f9412baf9de95da017))
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
* **demo:** align invest dashboard holdings count with listed sample stocks ([#182](https://github.com/navaneeshnagarajan/FlintTrade/issues/182)) ([7cfbbaa](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cfbbaa654cc3bcf295609ce92a26896b1d7cb7c))
* **demo:** hydrate Strategy Lab from ?strategy= when deploying from AI ([#183](https://github.com/navaneeshnagarajan/FlintTrade/issues/183)) ([09e03e6](https://github.com/navaneeshnagarajan/FlintTrade/commit/09e03e6cbf35a29aa8ee22ad068fd99656787ffe))
* **deps:** bump next to 16.3.6 ([#322](https://github.com/navaneeshnagarajan/FlintTrade/issues/322)) ([d9c9fe6](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9c9fe6963fcabf06de76829c4bdf20c6e807af4))
* **deps:** bump qs 6.16.0 and fflate 0.6.11 ([#178](https://github.com/navaneeshnagarajan/FlintTrade/issues/178)) ([7cff40a](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cff40a0aa686ed37de1544d059e0cebc15d0776))
* **deps:** bump urllib3 to clear the Python audit ([#320](https://github.com/navaneeshnagarajan/FlintTrade/issues/320)) ([7ee9afe](https://github.com/navaneeshnagarajan/FlintTrade/commit/7ee9afedaa2acd6e04b30251f3861fa9b3fb528b))
* **deps:** clear Node audit blockers on main ([#173](https://github.com/navaneeshnagarajan/FlintTrade/issues/173)) ([837ff25](https://github.com/navaneeshnagarajan/FlintTrade/commit/837ff25adf30cd5eccf1d4de4e7651e72a094ce8))
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
* **ditto:** disable Kill All Positions when Explore has zero accounts ([#193](https://github.com/navaneeshnagarajan/FlintTrade/issues/193)) ([84b0791](https://github.com/navaneeshnagarajan/FlintTrade/commit/84b0791a6c9cd047a8c74091435bcf99223499d5))
* **ditto:** guarantee mirror deactivation when emergency flatten is declined ([157241d](https://github.com/navaneeshnagarajan/FlintTrade/commit/157241d398bb5de94108c709581d4b5746f48d71))
* **ditto:** Kill All fail-closed when runtime unavailable (FT-DITTO-003) ([#247](https://github.com/navaneeshnagarajan/FlintTrade/issues/247)) ([e1b2138](https://github.com/navaneeshnagarajan/FlintTrade/commit/e1b2138016b2b0be06f1aeaeb60e507c58c62eaa))
* **ditto:** Position Mirror Start fail-closed (FT-DITTO-002) ([#233](https://github.com/navaneeshnagarajan/FlintTrade/issues/233)) ([b3192b6](https://github.com/navaneeshnagarajan/FlintTrade/commit/b3192b616332701c85d8fec326d315dcd071476f))
* **engine,core:** never let a dead intent journal veto the emergency flatten ([ad108fd](https://github.com/navaneeshnagarajan/FlintTrade/commit/ad108fdb568f8ec86abb40d1da3c15feb32b0486))
* **engine,desktop:** own strategy process lifecycles ([eb749fc](https://github.com/navaneeshnagarajan/FlintTrade/commit/eb749fc1f2a373cf775716029592949922c11c1d))
* **engine:** fail-close interrupted Action Centre dispatches on restart ([82741b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/82741b809000a251f5c975b5fcf95db9756b0157))
* **engine:** keep lifecycle deadlines off loop observation lag ([#318](https://github.com/navaneeshnagarajan/FlintTrade/issues/318)) ([110102d](https://github.com/navaneeshnagarajan/FlintTrade/commit/110102d09c39d06484ca812f4673a5dd5c9063af))
* **engine:** preserve scheduled market context ([7cd648d](https://github.com/navaneeshnagarajan/FlintTrade/commit/7cd648d933b7f9a48c4dd1424c9b3e89527ca813))
* **gateway:** enforce concurrent broker read rate budgets ([#326](https://github.com/navaneeshnagarajan/FlintTrade/issues/326)) ([ba5dafb](https://github.com/navaneeshnagarajan/FlintTrade/commit/ba5dafbebee9591935dbebbc7ab650fb010628a6))
* **gateway:** preserve Upstox special sessions ([76fcfb2](https://github.com/navaneeshnagarajan/FlintTrade/commit/76fcfb24a47a30aa9db7fc61ac9462d8191c41d3))
* **gateway:** revoke stale router generations ([6b3e54a](https://github.com/navaneeshnagarajan/FlintTrade/commit/6b3e54a8b2552dabd6fd4fc907380fb78d1ad567))
* **gateway:** stage native credential changes ([d010d63](https://github.com/navaneeshnagarajan/FlintTrade/commit/d010d63669c4f08fe9f4f54cf743c5b594c519cb))
* **home:** authed /home skips password Welcome Back (FT-HOME-003) ([#248](https://github.com/navaneeshnagarajan/FlintTrade/issues/248)) ([dfbc95d](https://github.com/navaneeshnagarajan/FlintTrade/commit/dfbc95da952b113a57da02b1b13df90b5d92f6c8))
* **home:** greet with Asia/Kolkata time-of-day ([#198](https://github.com/navaneeshnagarajan/FlintTrade/issues/198)) ([9c587a2](https://github.com/navaneeshnagarajan/FlintTrade/commit/9c587a22eb7e05d8e5fe5fcc29a6f6673096ae10))
* **home:** prevent duplicate Watchlist widgets ([#200](https://github.com/navaneeshnagarajan/FlintTrade/issues/200)) ([c877955](https://github.com/navaneeshnagarajan/FlintTrade/commit/c8779559ef62ddadc1e007e666188d5736fd6ba6))
* **infra,docs:** unstrand beta installs, add RPM depends, fix Sequoia install steps ([118ac20](https://github.com/navaneeshnagarajan/FlintTrade/commit/118ac20deb97e726d20d8c021ea7458687f37e9c))
* **infra:** make the macOS one-command install actually mount and install the DMG ([d071860](https://github.com/navaneeshnagarajan/FlintTrade/commit/d071860b74459ed185e3df5d1abfe25faece957c))
* **infra:** make the one-command installs survive real machines ([74add58](https://github.com/navaneeshnagarajan/FlintTrade/commit/74add582603ab9c54ad00621975c689ae148ecdd))
* **install:** close the Codex review findings merged unread on [#102](https://github.com/navaneeshnagarajan/FlintTrade/issues/102) and [#103](https://github.com/navaneeshnagarajan/FlintTrade/issues/103) ([#105](https://github.com/navaneeshnagarajan/FlintTrade/issues/105)) ([902107e](https://github.com/navaneeshnagarajan/FlintTrade/commit/902107ebf52a097598d828a6b01bdfd2416bbb11))
* **install:** harden Windows admission and cross-platform reinstalls ([#118](https://github.com/navaneeshnagarajan/FlintTrade/issues/118)) ([9640e4c](https://github.com/navaneeshnagarajan/FlintTrade/commit/9640e4cf0bea5666011e735fede0d18640785d87))
* **install:** native Windows install path, zero-prereq web installer, unified install/uninstall contract ([#102](https://github.com/navaneeshnagarajan/FlintTrade/issues/102)) ([9929461](https://github.com/navaneeshnagarajan/FlintTrade/commit/9929461a6d3905b5806cb3a482b56dc9a5650bd7))
* **install:** systemd unit vs setup-production.sh mismatch ([#158](https://github.com/navaneeshnagarajan/FlintTrade/issues/158)) ([6075b61](https://github.com/navaneeshnagarajan/FlintTrade/commit/6075b61e7efdfd8422b677530c496fc1355e389c))
* **invest:** disable seeded Explore Stock Baskets Edit/Delete (FT-INVEST-002) ([#245](https://github.com/navaneeshnagarajan/FlintTrade/issues/245)) ([a197705](https://github.com/navaneeshnagarajan/FlintTrade/commit/a19770560b24d9d1d0cf90f7f683e4f50f7ed0db))
* **invest:** Holdings badge matches visible table (FT-TRADE-010) ([#239](https://github.com/navaneeshnagarajan/FlintTrade/issues/239)) ([9446bfe](https://github.com/navaneeshnagarajan/FlintTrade/commit/9446bfe4807dc2d21a78cf016ac2c2f3b7fe15ac))
* **invest:** honor deep-link hash tabs on load ([#201](https://github.com/navaneeshnagarajan/FlintTrade/issues/201)) ([50ad9df](https://github.com/navaneeshnagarajan/FlintTrade/commit/50ad9dfef56194540eb3d1e2a2944ad33f444402))
* **invest:** Mutual Fund NAV freshness honesty (FT-INVEST-001) ([#211](https://github.com/navaneeshnagarajan/FlintTrade/issues/211)) ([813114d](https://github.com/navaneeshnagarajan/FlintTrade/commit/813114d7608a0f4c14226c1a1bbec9cff038c1d5))
* **kotakneo:** require explicit write acknowledgements ([#150](https://github.com/navaneeshnagarajan/FlintTrade/issues/150)) ([0ba4d2e](https://github.com/navaneeshnagarajan/FlintTrade/commit/0ba4d2e8c2960bcd26e65e00a26ac061278b7f29))
* **lab:** Backtest headline vs trade-log P&L (FT-LAB-004) ([#216](https://github.com/navaneeshnagarajan/FlintTrade/issues/216)) ([0aaa58d](https://github.com/navaneeshnagarajan/FlintTrade/commit/0aaa58d64fe5ce4006fac1c617e8667841f5cd35))
* **lab:** Options Builder Explore sample premium (FT-LAB-003) ([#210](https://github.com/navaneeshnagarajan/FlintTrade/issues/210)) ([b9328ee](https://github.com/navaneeshnagarajan/FlintTrade/commit/b9328ee384ea62290adb4cb7a522b81f06fedfd5))
* **lab:** Options Builder position debit/max loss (FT-LAB-005) ([#217](https://github.com/navaneeshnagarajan/FlintTrade/issues/217)) ([76bb31e](https://github.com/navaneeshnagarajan/FlintTrade/commit/76bb31e5837a5879777a09f91ed910a1aa5e2b04))
* **lab:** remove duplicate zero placeholders on backtest metrics ([#190](https://github.com/navaneeshnagarajan/FlintTrade/issues/190)) ([8f9be3d](https://github.com/navaneeshnagarajan/FlintTrade/commit/8f9be3d3bd2de8f20a3c45fb05ba3adbb2e7e3f8))
* **lab:** zero-premium long-call payoff (unbounded max profit + breakeven) ([#188](https://github.com/navaneeshnagarajan/FlintTrade/issues/188)) ([e4067d9](https://github.com/navaneeshnagarajan/FlintTrade/commit/e4067d942218fe5a417050ab0ff89daff2850c94))
* **learn:** Glossary Lot Size freshness (FT-LEARN-002) ([#214](https://github.com/navaneeshnagarajan/FlintTrade/issues/214)) ([b334586](https://github.com/navaneeshnagarajan/FlintTrade/commit/b3345860eb38d3c9740cde32a195126737f77114))
* **learn:** Practice Trading CTA to OpenAlgo Gateway ([#203](https://github.com/navaneeshnagarajan/FlintTrade/issues/203)) ([8e3fd03](https://github.com/navaneeshnagarajan/FlintTrade/commit/8e3fd03013311be3207a4e408253155b606550ca))
* **learn:** Resource Hub User Guide first-open honesty (FT-LEARN-003) ([#242](https://github.com/navaneeshnagarajan/FlintTrade/issues/242)) ([e3fb8f1](https://github.com/navaneeshnagarajan/FlintTrade/commit/e3fb8f1108da3b3aa6eac5d8d2cd16d1529e3551))
* **openalgo:** align with v2.0.2.2 contracts ([#153](https://github.com/navaneeshnagarajan/FlintTrade/issues/153)) ([a31040a](https://github.com/navaneeshnagarajan/FlintTrade/commit/a31040ae63c0fa65bb99dd52dd1cb427348f375b))
* **orders:** align native GTT management ([6e9fe3c](https://github.com/navaneeshnagarajan/FlintTrade/commit/6e9fe3cf24b30815ed8888ef2fd1d5b67772b231))
* **orders:** close the GTT review findings — SL prefill, honest refusals, flag verification ([ef22654](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef226547f3bfb2b02db650417a1df32e5411fb38))
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
* **settings:** align Broker Gateway and Ditto default URLs ([#199](https://github.com/navaneeshnagarajan/FlintTrade/issues/199)) ([a659d92](https://github.com/navaneeshnagarajan/FlintTrade/commit/a659d92c69ba3a08e1c1a64b5e928d6d1163bdd9))
* **settings:** Leverage tab content or honest empty (FT-SET-004) ([#249](https://github.com/navaneeshnagarajan/FlintTrade/issues/249)) ([ef85045](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef850450912c01fcbfb777fc1a499f29271bbd50))
* **settings:** recover Explore Settings #llm as empty state ([#195](https://github.com/navaneeshnagarajan/FlintTrade/issues/195)) ([4d6b9d9](https://github.com/navaneeshnagarajan/FlintTrade/commit/4d6b9d9fc7d9098da7bdf422047657b465e79487))
* **settings:** require exactly six digits for Security PIN ([#208](https://github.com/navaneeshnagarajan/FlintTrade/issues/208)) ([76128ac](https://github.com/navaneeshnagarajan/FlintTrade/commit/76128acf45092f8497dd16092877fb1b439c86bc))
* **settings:** show install-host metrics on Monitoring ([#278](https://github.com/navaneeshnagarajan/FlintTrade/issues/278)) ([7fc8d8d](https://github.com/navaneeshnagarajan/FlintTrade/commit/7fc8d8df5c9c57522fbdad2c823334d761ea0ead))
* **setup:** allow Explore/Practice escape hatch before mandatory TOTP ([#184](https://github.com/navaneeshnagarajan/FlintTrade/issues/184)) ([ef5b574](https://github.com/navaneeshnagarajan/FlintTrade/commit/ef5b57494cc380f2a7c2b45926c03e9ec2d1bbcc))
* **setup:** survive reload, block re-entry, make the vault step honest (FT-SETUP-HARDEN-001) ([#297](https://github.com/navaneeshnagarajan/FlintTrade/issues/297)) ([097492b](https://github.com/navaneeshnagarajan/FlintTrade/commit/097492b98be352ddb9f8e70acea78ba333408331))
* **site,terminal:** isolate public-demo dotenv and fail-closed /explore ([#161](https://github.com/navaneeshnagarajan/FlintTrade/issues/161)) ([c6a293a](https://github.com/navaneeshnagarajan/FlintTrade/commit/c6a293a269ddeaa6bc2f370d4cdfa36031fb126e))
* **site:** align homepage install cards with the AppImage-only Linux reality ([f6c39c9](https://github.com/navaneeshnagarajan/FlintTrade/commit/f6c39c9543c5eebaa2303228b7d10377e91319ae))
* **site:** configurable origin, one GitHub control, Hostinger-ready ([#172](https://github.com/navaneeshnagarajan/FlintTrade/issues/172)) ([0dae13e](https://github.com/navaneeshnagarajan/FlintTrade/commit/0dae13e3fc82f5fa50f68bf30d8462a10ec063a8))
* **site:** make the site domain a single source of truth, and kill an Electron flake ([#108](https://github.com/navaneeshnagarajan/FlintTrade/issues/108)) ([41b2f23](https://github.com/navaneeshnagarajan/FlintTrade/commit/41b2f235babf36a02716ebe5fac76c84b032e2cf))
* **site:** polish narrow homepage nav to remove remaining horizontal overflow ([#181](https://github.com/navaneeshnagarajan/FlintTrade/issues/181)) ([2a5ce88](https://github.com/navaneeshnagarajan/FlintTrade/commit/2a5ce88cb76d3c8b510ab59996084196bd7b29ca))
* **site:** rewrite repo-relative docs links to GitHub ([#159](https://github.com/navaneeshnagarajan/FlintTrade/issues/159)) ([b8c7c24](https://github.com/navaneeshnagarajan/FlintTrade/commit/b8c7c244a95a643aed3c0b13042a570ca969eff6))
* **site:** stop duplicating docs page summary as first body paragraph ([57e27c8](https://github.com/navaneeshnagarajan/FlintTrade/commit/57e27c84749055b4ba7acaa975ce8e6deddcccbe))
* **site:** stop primary nav overflow clipping Contribute on narrow viewports ([#180](https://github.com/navaneeshnagarajan/FlintTrade/issues/180)) ([9a32523](https://github.com/navaneeshnagarajan/FlintTrade/commit/9a32523b8c785a401a95f093df083377d41481f8))
* **site:** stop selling an unpublished desktop app on the homepage ([#157](https://github.com/navaneeshnagarajan/FlintTrade/issues/157)) ([cb8790a](https://github.com/navaneeshnagarajan/FlintTrade/commit/cb8790a2a282c796b3c7cd5c95cc4e9fd3fdfa7c))
* **site:** tag-agnostic download fallback and thin-shell copy ([38f8008](https://github.com/navaneeshnagarajan/FlintTrade/commit/38f800896f414ac297026bb52540052d71b2a042))
* **supply-chain:** bind audits to current locks ([00f6ea1](https://github.com/navaneeshnagarajan/FlintTrade/commit/00f6ea1489ca7c63388bdc0e9df3c32492a5eef3))
* **terminal:** align live market signal state ([fd01278](https://github.com/navaneeshnagarajan/FlintTrade/commit/fd012784e35c33e539877181f393cc99ef1c847a))
* **terminal:** align order-flow exchange sessions ([3cce8b2](https://github.com/navaneeshnagarajan/FlintTrade/commit/3cce8b2fab403fd29d848afe6a23993d433c9a22))
* **terminal:** badge and stabilise the Explore home account cards ([766d26a](https://github.com/navaneeshnagarajan/FlintTrade/commit/766d26a5db0f1ebf150f2b74853c448df60af03f))
* **terminal:** clear the demo session on a real login ([eb3a058](https://github.com/navaneeshnagarajan/FlintTrade/commit/eb3a0589f47a80c5f9025875af9eb68294d41031))
* **terminal:** close the second verify round on the migration fixes ([e7f438f](https://github.com/navaneeshnagarajan/FlintTrade/commit/e7f438f62ab1cfc401e5d028e6b6006d4476de23))
* **terminal:** close the seventeen review findings on the migration wave ([49564c0](https://github.com/navaneeshnagarajan/FlintTrade/commit/49564c069c22e5f3b29f466554a8a9ba4a8c2ddd))
* **terminal:** dead routes, one Practice admission path, no self-inflicted 429s (FT-DESK-ROUTES-001) ([#298](https://github.com/navaneeshnagarajan/FlintTrade/issues/298)) ([4812129](https://github.com/navaneeshnagarajan/FlintTrade/commit/4812129595c68a4823d4d8444dc3fb36707a47fd))
* **terminal:** disclose order-flow provenance ([6d6ae67](https://github.com/navaneeshnagarajan/FlintTrade/commit/6d6ae67704a722429b72b7f7d2129b40d8d5f5b5))
* **terminal:** enable LegBuilder strategy placement over the gated basket route ([6918662](https://github.com/navaneeshnagarajan/FlintTrade/commit/691866228c61d1e7ade07ea5bc9bc1b6ce1fd196))
* **terminal:** give the MCX ticker commodities sample prices in Explore ([ffe59a5](https://github.com/navaneeshnagarajan/FlintTrade/commit/ffe59a5afdc4a134c3cb91b9f675d945cd0419c9))
* **terminal:** keep order-flow canvases truthful ([2770f38](https://github.com/navaneeshnagarajan/FlintTrade/commit/2770f3872260aba0c20289434c5f2e687ecfd764))
* **terminal:** keep order-flow instruments aligned ([6fefdf5](https://github.com/navaneeshnagarajan/FlintTrade/commit/6fefdf5842b47d179edd6896220c6fee0e37d233))
* **terminal:** keep the fresh 2FA QR seed through setup and show a manual key ([af60bcd](https://github.com/navaneeshnagarajan/FlintTrade/commit/af60bcd8c58f84c3fc0c13eb7390eea9b64ed694))
* **terminal:** keep the kill switch available on a failed safety refresh ([d7f4e4b](https://github.com/navaneeshnagarajan/FlintTrade/commit/d7f4e4bc9a8aa25aeb4ea28581593ce456b1ae8e))
* **terminal:** label sample data and simplify Invest tabs (FT-UX-HOME-INVEST-001) ([#300](https://github.com/navaneeshnagarajan/FlintTrade/issues/300)) ([824f9cc](https://github.com/navaneeshnagarajan/FlintTrade/commit/824f9cc2389af0cb8b188332368d3890492c8b85))
* **terminal:** make AI Advisor approvals gated, authenticated and honest ([49a4fdd](https://github.com/navaneeshnagarajan/FlintTrade/commit/49a4fddc0741801a05166c5861b3cda389c54017))
* **terminal:** migrate financial tables to TanStack Table v9 ([#269](https://github.com/navaneeshnagarajan/FlintTrade/issues/269)) ([0d1f7b0](https://github.com/navaneeshnagarajan/FlintTrade/commit/0d1f7b05a11e560ae17dbee570fd7fb081f9552a))
* **terminal:** name the Action Centre's producer in its empty state ([e2060e1](https://github.com/navaneeshnagarajan/FlintTrade/commit/e2060e12b2615ab88d88f52b4509ffe7caf88ce4))
* **terminal:** one Mode menu and one home for each status (FT-UX-CHROME-001) ([#299](https://github.com/navaneeshnagarajan/FlintTrade/issues/299)) ([807aeef](https://github.com/navaneeshnagarajan/FlintTrade/commit/807aeefddc4eb7f8c9ef57773ce3bf0af87149f2))
* **terminal:** one Order Pad, reliable symbol search, quieter Setup tray (FT-UX-DESK-001) ([#302](https://github.com/navaneeshnagarajan/FlintTrade/issues/302)) ([aeac9c5](https://github.com/navaneeshnagarajan/FlintTrade/commit/aeac9c5e7d22a2fbd365fed428fa9b9e3bf4d0d4))
* **terminal:** pin TanStack Table at 8.21.3 so the production bundle builds ([#268](https://github.com/navaneeshnagarajan/FlintTrade/issues/268)) ([4b0f737](https://github.com/navaneeshnagarajan/FlintTrade/commit/4b0f7372404b42adbec3045efc064a3bac503da9))
* **terminal:** preserve authenticated live feeds ([7f42fce](https://github.com/navaneeshnagarajan/FlintTrade/commit/7f42fce64ccb74d7815b90290682f4727def0778))
* **terminal:** preserve compact market-data controls ([afe1afb](https://github.com/navaneeshnagarajan/FlintTrade/commit/afe1afb8c16e09d07826dfd0ac1fdfff1dac7ef1))
* **terminal:** preserve live data provenance ([d9beefd](https://github.com/navaneeshnagarajan/FlintTrade/commit/d9beefda17c4c2a56e274be6d22e50d44d0156c7))
* **terminal:** purge persisted 'Broker gateway connected' spam on load ([a54fa89](https://github.com/navaneeshnagarajan/FlintTrade/commit/a54fa8977a30e8e1da60fd958d36c43529aa136e))
* **terminal:** read index LTPs from their *_INDEX atom keys in OrderPad ([d83a67e](https://github.com/navaneeshnagarajan/FlintTrade/commit/d83a67e1dd33714cbec29ca7fbf1df8541ea8bdf))
* **terminal:** reconcile emergency runtime state ([7c4cf6a](https://github.com/navaneeshnagarajan/FlintTrade/commit/7c4cf6a6863780f3181d41f674c2ac978d3ce3fa))
* **terminal:** restore Tools Quick Settings for desk controls ([#279](https://github.com/navaneeshnagarajan/FlintTrade/issues/279)) ([1e5f2d8](https://github.com/navaneeshnagarajan/FlintTrade/commit/1e5f2d8c8e57198a3c307d6c9bef0c0cd5ac6ae6))
* **terminal:** restore usable chrome, contrast, and overflow ([1f04d61](https://github.com/navaneeshnagarajan/FlintTrade/commit/1f04d61259197ca56534911a3e5cc3675ac38db6))
* **terminal:** scrub calendar-day operator copy from Setup ([#281](https://github.com/navaneeshnagarajan/FlintTrade/issues/281)) ([e7f324a](https://github.com/navaneeshnagarajan/FlintTrade/commit/e7f324a02be92304f651e98c00f1b2961a56cda0))
* **terminal:** serve sample expiries and option chain in Explore ([b5483cf](https://github.com/navaneeshnagarajan/FlintTrade/commit/b5483cf947531e92fea228c95e209f2e2cc436dd))
* **terminal:** share the index tick-key normalisation with OrderLadder ([99ed101](https://github.com/navaneeshnagarajan/FlintTrade/commit/99ed101192b9d6424cffa2e3dd35793ca202efe7))
* **terminal:** show live venue badges on the ticker strip ([#280](https://github.com/navaneeshnagarajan/FlintTrade/issues/280)) ([cf01bfb](https://github.com/navaneeshnagarajan/FlintTrade/commit/cf01bfb35db9b641f07465b34cb642f7a4c78f26))
* **terminal:** simplify first-run Setup to Practice desk ([#282](https://github.com/navaneeshnagarajan/FlintTrade/issues/282)) ([f52be9a](https://github.com/navaneeshnagarajan/FlintTrade/commit/f52be9ac2d784f2eeef9e6b705060dddbe6a99ce))
* **terminal:** stop the false 'broker gateway connected' spam in Explore ([3ecd23f](https://github.com/navaneeshnagarajan/FlintTrade/commit/3ecd23f53918eea10a7773a4f3e2f660e676301a))
* **terminal:** validate market-data provenance ([0625e90](https://github.com/navaneeshnagarajan/FlintTrade/commit/0625e903dfb9d112b01174e5e758145c61f066e6))
* **test:** seed the test master password from one hardened implementation ([#113](https://github.com/navaneeshnagarajan/FlintTrade/issues/113)) ([072a228](https://github.com/navaneeshnagarajan/FlintTrade/commit/072a228ee313b710a899fd325acec0df09479a63))
* **test:** stop the scratch sweeper deleting live workers' workspaces ([#115](https://github.com/navaneeshnagarajan/FlintTrade/issues/115)) ([d31c43c](https://github.com/navaneeshnagarajan/FlintTrade/commit/d31c43cb682fc86182350f02ff2f83fe73d35a52))
* **ticks:** preserve PyO3 extraction contracts ([59fbc67](https://github.com/navaneeshnagarajan/FlintTrade/commit/59fbc676502092b88ed71e805d15a9b61b99575c))
* **ticks:** reject unsafe spread arithmetic ([569dad7](https://github.com/navaneeshnagarajan/FlintTrade/commit/569dad74715f074e0fdbaf6238de1462fa3f8044))
* **ticks:** validate spread batches before parallel work ([c90d246](https://github.com/navaneeshnagarajan/FlintTrade/commit/c90d2461d4c5e8c358092d0e87cb777e149576a7))
* **ticks:** validate spread batches before rayon ([7aeb937](https://github.com/navaneeshnagarajan/FlintTrade/commit/7aeb937cdb3a17cb604c16edcf6d3d30f693b555))
* **ticks:** validate spread batches deterministically ([f54ae95](https://github.com/navaneeshnagarajan/FlintTrade/commit/f54ae95ed19647372577574535acabe8568fb2fb))
* **trade:** allow Practice orders in Explore without live broker ([#191](https://github.com/navaneeshnagarajan/FlintTrade/issues/191)) ([c76f495](https://github.com/navaneeshnagarajan/FlintTrade/commit/c76f4958f5c0b408cf6d867ffac27e99005155d7))
* **trade:** correct market status during NSE regular hours ([#197](https://github.com/navaneeshnagarajan/FlintTrade/issues/197)) ([e4e8ccf](https://github.com/navaneeshnagarajan/FlintTrade/commit/e4e8ccf855204d595c32f7f729e3d8fe068eef40))
* **trade:** Explore Scalper fail-closed order path (FT-TRADE-009) ([#232](https://github.com/navaneeshnagarajan/FlintTrade/issues/232)) ([aded66e](https://github.com/navaneeshnagarajan/FlintTrade/commit/aded66e059dcdd30912ff73d1ee8b3eb9d6aca52))
* **trade:** Heatmap Group by Exchange labels (FT-TRADE-005) ([#212](https://github.com/navaneeshnagarajan/FlintTrade/issues/212)) ([1c2eb69](https://github.com/navaneeshnagarajan/FlintTrade/commit/1c2eb6930d75e6eb513f08361c168e0c9e95c868))
* **trade:** OI Chart expiry honesty (FT-TRADE-007) ([#230](https://github.com/navaneeshnagarajan/FlintTrade/issues/230)) ([5276aea](https://github.com/navaneeshnagarajan/FlintTrade/commit/5276aeaed4ca1a18b45dccdd5aa385275873c959))
* **trade:** Performance follows Review range (FT-TRADE-006) ([#215](https://github.com/navaneeshnagarajan/FlintTrade/issues/215)) ([820ab69](https://github.com/navaneeshnagarajan/FlintTrade/commit/820ab6906fa0845bef886fcd84e228993163faa6))
* **trade:** refresh chart when timeframe selector changes ([#196](https://github.com/navaneeshnagarajan/FlintTrade/issues/196)) ([cd2747e](https://github.com/navaneeshnagarajan/FlintTrade/commit/cd2747e9f1ad735a874ba18dfd5966c54d6ecf84))
* **trade:** Trade Review date filter and mangled timestamps in Explore ([#187](https://github.com/navaneeshnagarajan/FlintTrade/issues/187)) ([1ed4961](https://github.com/navaneeshnagarajan/FlintTrade/commit/1ed496123e85ab84da0d696006a7c34c65688407))
* **trade:** Watchlist LTP/% columns (FT-TRADE-008) ([#231](https://github.com/navaneeshnagarajan/FlintTrade/issues/231)) ([149b702](https://github.com/navaneeshnagarajan/FlintTrade/commit/149b702d4d58e8c5a6fdd298404c7d7b6be051b4))
* **ui:** keep P&L columns usable at ~390px ([#202](https://github.com/navaneeshnagarajan/FlintTrade/issues/202)) ([5629080](https://github.com/navaneeshnagarajan/FlintTrade/commit/5629080a2641a41cd32215740eda2b1fb87387bd))
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
* **infra,core:** merge deploy scripts and retire the v1_compat shim ([3e934c2](https://github.com/navaneeshnagarajan/FlintTrade/commit/3e934c2183e504e23017944bad894830a70454cb))
* **orders:** collapse order routing to the single gated surface ([b1c66b8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b1c66b83d29c564e8a9f3f0c149fdbc38af7c6a7))
* **terminal:** dedupe getFtBase onto the shared ftApi helper (U8 tail) ([62ed4ff](https://github.com/navaneeshnagarajan/FlintTrade/commit/62ed4ffb21fd8ac42e6023dee23238b5787696d8))
* **terminal:** IntradayPnL consumes the shared positions/tradebook caches (U10 complete) ([afbf504](https://github.com/navaneeshnagarajan/FlintTrade/commit/afbf504c5c054aa6e7d231841b60995038901ed4))
* **terminal:** merge duplicate widgets 102 → 69, retire five integrations ([#71](https://github.com/navaneeshnagarajan/FlintTrade/issues/71)) ([b585be8](https://github.com/navaneeshnagarajan/FlintTrade/commit/b585be88e560439f87819060c714b473c6c3ada1))
* **terminal:** route the last hardcoded /ft-api fetches through getBase ([a6ee786](https://github.com/navaneeshnagarajan/FlintTrade/commit/a6ee786e721b316fe0a130a6ff860873ba52d6d4))

## [Unreleased]

### Fixed

- **Desk routes, one Practice place path, and desk polling.** `/positions`,
  `/holdings`, `/monitoring`, `/schedules`, and `/glossary` open the screen
  that owns that book. `/login` opens sign-in. Practice places go through
  the admitted order route only; Settings does not place. A missing price
  says so plainly, or fills at the last stored close. The Trade book starts
  open. Desk reads pause while the tab is hidden and back off after HTTP 429.

- **Laya chip, runtime key, and snapshot launch.** The desk polls
  `GET /api/v1/ping` every 1.5 seconds. That ping reconciles the pid
  file, the key file, and the runtime record the same way an order
  does, so the chip and the order gate read the same state. A
  command-line stop or start shows on the chip by the next 1.5-second check.
  After Start Laya, until that ping confirms the new state, the chip
  says Checking in the neutral colour and the popover says Checking
  Laya…. It does not show a stale Ready during that wait. An admitted
  place while the chip is not Ready or Degraded also shows Checking
  until the next ping. A confirmed
  first load still says Still loading. A place refused with exactly
  "Laya is Down. New orders are paused until it's Ready. You can still close positions." sets the chip to
  Down on that response. The refusal line is unchanged. When
  `LAYA_API_KEY_FILE` names `<workspace>/runtime/laya/api.key`, `start`
  replaces that file and does not treat it as missing. A different path
  that is not there still refuses with "The Laya API key file is
  missing." A model already in the standard Hugging Face cache is
  accepted. When that file is the cache symlink
  `snapshots/<revision>/model.safetensors`, the launch path is the
  snapshot file, not the blob. A blob path is still refused. An admitted
  Practice place with an empty note skips the model and writes one
  decision-log line, `effect=clamp` with `failure=note_absent` and no
  proof. When this run's record stood in, each model allow keeps its own
  `effect=allow` `proof=runtime` line.

### Added

- **Opt-in Laya decision sidecar for place admission (FT-LAYA-MODEL-001).**
  After the hard rules, the sidecar may deny or clamp a place only. It
  cannot raise a quantity or overturn a rule refusal, and it does not
  place the order. Laya starts Down. A ping does not invent Ready.
  Live stays fail-closed until a qualification record uses
  LIVE_DECISION evidence for the exact model revision, weight digest,
  and policy version. When Laya is actually Down, every mode is refused
  with "Laya is Down. New orders are paused until it's Ready. You can still close positions." A Practice
  refusal never says Live. A Live place without that qualification,
  while Ready or Degraded, says "Laya isn't qualified for Live yet.
  Practice orders are available." Opt in with
  `python -m flinttrade_core.laya_runtime install` or `start`.
  The CPU install pins `torch==2.14.0+cpu`, `laya==0.3.21`,
  `huggingface_hub==1.33.0`, and `tqdm==4.70.1`
  in `laya_sidecar_constraints.txt` (no extras; the install requirement
  is still `laya[serve]==0.3.21`). The download progress class subclasses
  that pinned `tqdm.auto.tqdm`. Torch is installed first from the CPU
  index, and the sidecar can share the base interpreter with FlintTrade.
  `LAYA_PORT` defaults to 8000. The host stays `127.0.0.1`.
  It is not Ready by default. A first start with the checkpoint missing
  or incomplete downloads the commit named by `[checkpoint] revision`
  (not the model repository's default branch) into `runtime/laya/staging`.
  That download sets `HF_HOME` to `<workspace>/runtime/laya/hf-home` and
  `HF_HUB_DISABLE_XET=1`, so transfer logs stay out of the shared cache.
  FlintTrade hashes the files there against the `[checkpoint]` and
  `[checkpoint.manifest]` pins, and on a full match moves that directory
  onto `runtime/laya/checkpoint` before the offline launch. When a new
  pin replaces a checkpoint already on disk, the next start downloads it
  the same way and the current copy stays in place until the new files
  match. On a full match that checkpoint is renamed aside to
  `checkpoint.old-<random>` in the same runtime directory, staging is
  renamed onto `checkpoint`, and the old copy is deleted. If that second
  rename fails, the old checkpoint is renamed back, the chip is
  `download_failed`, and the sidecar does not start. While the download
  runs, including a pin change, the status word is Down, not Still
  loading, and the chip reads "Downloading the model · 1.2 of 3.4 GB".
  The model is about 2.37 GB, and that size is reported once.
  There is no separate Updating label. Orders are refused with
  "Laya is Down. New orders are paused until it's Ready. You can still close positions." A dropped
  connection, a partial download, or a failed swap is `download_failed`
  ("Can't download the model"; tooltip "Check your connection, then
  Start Laya again.") and deletes only the staging directory. That chip
  stays `download_failed` even when an older snapshot is still on disk,
  whether that snapshot would be `wrong_revision` or `unverified`.
  `unverified` stays when this start did not download. `wrong_revision`
  is only a complete download whose files
  do not match the pin, a snapshot already on disk that this start is not
  replacing, or a running sidecar that reports another revision or digest.
  Leftover staging directories and `checkpoint.old-*` copies are removed
  at the start of `start` once a checkpoint is in place, with no chip change and
  no message. If `checkpoint` is missing after a crash between the two
  renames, the last `checkpoint.old-*` name is restored and checked
  against the pin.
  The sidecar does not start on files that do not match the pin, including
  that restored copy. The sidecar always runs offline. When its health
  document leaves the revision empty, FlintTrade fills the pinned
  revision from the verified manifest, so the chip leaves Still loading.

- **Mode honesty bar.** One line under the TopBar for Example, and for
  Practice and Live. Widgets no longer repeat a Sample chip. An incident, when
  one is showing, sits above that line and does not replace it.
- **Practice `SandboxEngine` primary fills (FT-MONDAY-001).**
  Practice places and records native `SandboxEngine`
  fills end-to-end as the primary paper path. The terminal
  and AI read that same Practice book. Example stays
  sample data. Live stays fail-closed until MSI
  native read smoke is trusted and funded unlock. Practice
  never leaks a live broker order. OpenAlgo is
  Settings fallback only — not the primary
  connect CTA. Kotak Neo has no sandbox — never offer
  Neo Practice.
- **Service connections and in-process `BrokerReadPort`.** The backend now
  ships a rights-aware service-provider catalogue, static LLM/data profiles,
  and an inert persisted service-connection control plane. Listing or saving a
  connection does not resolve, probe, authenticate to, or start that provider.
  Exact broker reads in this change are the in-process `BrokerReadPort`
  contract (quotes, depth, history, balances, books, and related methods) —
  not a restored terminal Brokers screen or a new public HTTP read family.

- **Shared symbol bus from Watchlist (FT-TRADE-011).**
  Selecting a symbol in `/trade` Watchlist retargets
  Chart, Option Chain, and Scalper to that symbol —
  no retype. Keyboard retarget is optional later.
  Example retarget is allowed. Disclosure stays the
  Mode honesty line, not a widget Sample chip.
  An empty watchlist never silently retargets.

- **Option Chain OI profile + PCR strip (FT-TRADE-012).**
  The Option Chain strip shows OI profile + PCR for
  the selected expiry/symbol. Example does not invent
  live OI. The Mode honesty line is the disclosure —
  there is no Sample chip on the chain strip. An empty
  expiry is an honest empty, not zeros-as-data.

### Changed

- **Desk Laya chip follows the current mode (FT-LAYA-MODEL-001).**
  Practice shows sidecar Ready, Degraded, Down, Still loading, or
  Checking. Live shows Live-facing status. "Not qualified for Live" is the tooltip
  and the popover line when Live lacks qualification. Ping
  publishes Live-facing `laya`, sidecar `laya_practice`, and
  `laya_live_qualified`, plus a reason code and port. During the first
  load the chip says Still loading and does not read Down. Orders stay
  refused with the Down sentence. A port clash says which port is in use.
  The Live Blocked strip follows Live-facing
  Down only. It mutes Live place and Position Mirror start. Practice
  is not muted by that strip. Clicking the chip opens a popover with the
  plain-words reason, the link "How to start Laya"
  (`docs/USER_GUIDE.md#start-laya`), and an operator-only "Start Laya"
  button. The chip tooltip carries
  `python -m flinttrade_core.laya_runtime start`. Reason codes are
  `not_started`, `stopped`, `port_in_use`, `still_loading`,
  `downloading` (Downloading the model · 1.2 of 3.4 GB),
  `download_failed` (Can't download the model),
  `unreachable` (Unreachable), `wrong_revision` (Wrong model version),
  `unverified` (Can't verify the model), `key_rejected` (Can't reach
  Laya), and `key_missing` (The Laya API key file is missing.). A health
  check does not replace `key_missing` with Not started. When
  `LAYA_API_KEY_FILE` names `<workspace>/runtime/laya/api.key`, `start`
  replaces that file and does not treat it as missing. A different path
  that is not there still refuses with that same sentence.
  `downloading` has no Next line. The `download_failed` tooltip is
  "Check your connection, then Start Laya again." A signed-in operator can start the sidecar from the popover
  (`POST /api/v1/laya/start`); the chip then says Checking in the
  neutral colour, and the popover says Checking Laya…, until the ping
  confirms Ready, Degraded, or a reason other than `not_started`. A
  confirmed first load still says Still loading. A dead sidecar is reaped
  and reported Stopped. A clamp says "Not placed. Laya allows
  up to N." with Place N and Cancel, and never auto-places. Place N
  sends that quantity, and the Practice review panel shows it. A Down
  refusal is "Laya is Down. New orders are paused until it's Ready. You can still close positions." and
  does not show a quantity ceiling. A Live place that
  is not qualified says "Laya isn't qualified for Live yet. Practice
  orders are available." The Order Pad note is the collapsed line "Add a
  reason (optional)" under Quantity. Once open, the field's accessible
  name is the same. Under a denial, the server reason is named
  "Laya decision" inside one alert (`role="alert"`). That alert is the
  only live region. The reason line is not its own status. A place with
  no note still gets
  Laya's policy decision: Practice clamps and Live denies. It is not a
  hard reject. Desk place
  surfaces go through this admission.

- **GTT is refused on every submit route.** `"variety": "gtt"`, in any
  case or separator spelling, is HTTP 422 `gtt_unsupported` on place,
  routed place, exit-all, and a bracket, before Laya, SafetySystem, and
  any broker call. The message is `Not placed. GTT orders aren't supported right now.`
  No submit route reaches a broker forever or super-order endpoint. The
  Kotak Neo adapter refuses a `gtt` place. Order Pad keeps GTT visible and
  disabled, with the tooltip `GTT orders aren't supported right now.`
  `POST /api/v1/orders/forever` does not place: a valid body is HTTP 501
  `Orders are placed through /api/v1/orders/place.` A Live bracket with
  exactly one stop-loss or one target submits on
  `POST /api/v1/orders/bracket` after admission. Practice on that route is
  HTTP 403 `practice_unsupported`. A broker-held variety, a stop-loss and
  a target together, and a trailing stop are refused before admission. A
  second exit on the same broker account, while this desk's exit on that
  contract is unfilled, is HTTP 409 `exit_pending`: `Not placed. An exit for <symbol> is already pending. Wait for it to fill, or cancel it and try again.`
  The row keeps **Exit pending**. The Live hold is
  for that broker account. When the broker
  order book cannot be read, that refusal is HTTP 409
  `exit_orders_unreadable`: `Not placed. One exit at a time for <symbol> until your broker's orders load.`
  A signed-out reset with no
  authenticator enrolled reads `Sign in to reset this account. You'll
  need your password.` With an authenticator enrolled it reads `Sign in
  to reset this account. You'll need your password and authenticator
  code.` Recovery asks for an authenticator code only once one is
  enrolled.

- **Session auth and probes.** A session JWT on
  `Authorization: Bearer` or `X-FlintTrade-Token` passes the global check.
  An API key on `X-FlintTrade-Token` does not. A reduce-only close can be admitted while
  new orders are paused. PIN unlock replaces the session token. Reset of
  a finished account needs a session and the password. A wipe ends other sessions. Practice restore marks fills and leaves them out
  of the Laya, strategy, benchmark, and training readers. `GET /healthz`
  and `GET /readyz` are public and return status only.

- **Home and Invest net worth, greeting, benchmark legend, and Example markers.**
  Home and Invest share one total: ledger cash, including blocked
  margin, plus holdings at market value, plus open positions. Opening
  an F&O position does not reduce the total by its margin. A Practice
  round trip at an unchanged price leaves it at the starting cash, for
  example ₹10,00,000. Options add signed market value. Futures add
  unrealised P&L. Dhan marks from the mark-to-market average, or from
  `costPrice` when that average is absent. Kotak Neo marks an open
  future from the open-leg average. Practice marks a future from the
  entry price. An estimated futures mark shows `≈`. Dhan does this for
  `costPrice`. Kotak Neo does this for an open future. Practice never
  does. The mark clears when that position is flat or the average
  arrives. The tooltip and `≈` sit on the Home Net Worth amount, the
  Known Total amount, and the Open Positions value. The Invest
  Dashboard label `Net Worth (Cash + Holdings + Positions)` carries
  the tooltip, and `≈` sits on the amount under it. Available Funds
  shows that `≈` with no tooltip. Dhan's tooltip, when the average was
  missing, is
  `Approximate. Your broker didn't send an average price for NIFTY-JUN2026-FUT, so profit or loss from earlier days may be counted twice.`
  Neo's is
  `Approximate. The price for NIFTY25JUNFUT is estimated from the open position's average, so profit or loss from earlier days may be counted twice.`
  Several positions of one kind say `N futures positions` instead of
  the symbol. The screen-reader name is `Net Worth, approximately …`.
  Allocation percentages are not marked. Home allocation stays on the
  Example split until funds, holdings, and positions have all loaded.
  Home and Invest both wait for the position book before they publish
  the total. The sample book does not. While that book is pending or
  has failed, Home shows `—` and does not draw cash alone. A negative
  total is the number, for example `-₹50,000`, or `≈ -₹50,000` when
  the mark is approximate. Home derives each open position's P&L
  percent from cost, and shows `—` when cost is missing or not above
  zero.
  The greeting uses the saved display name, then the username, and
  stays plain `Good morning` (or afternoon or evening) until a name
  is known. It never uses `Trader`. On Benchmark, real holdings use
  `Your holdings (unrealised)` instead of
  `Your Portfolio (since first buy)`. An empty book stays
  `Your Portfolio`. Example holdings stay `Your Portfolio` with an
  Example label, and the hard-coded index returns keep the Example
  chip. Dashboard Net Worth, Available Funds, Invested Value, and Day P&L
  show the final formatted value on the first frame in every mode, with
  no count-up from zero, including `≈`, `-₹50,000`, and `—`.
  The sample Dashboard XIRR is the inline `XIRR` figure plus
  one Example chip. Portfolio Allocation on that sample dashboard omits
  its broker sentence and does not carry its own Example chip. There
  is no Portfolio XIRR card. On sample figures, Net Worth reads
  `Example equity and cash. Connect a broker to see yours.`; the
  allocation label is `Allocation` with the Example chip. Equity
  Holdings and Cash leave their notes blank, and those rows do not
  carry their own Example chip. In Example, Baskets show one Example
  chip while quotes are loading and after they have loaded. ETFs show
  one Example chip and `Example prices. Connect a broker for live quotes.`;
  Practice and Live keep the live quote wording. Sector's header reads
  `Example sector split. Connect a broker to see yours.` and the footer
  reads `Example data. Not from your holdings.` Social shows exactly one
  Example chip. The sample XIRR chip and the Net Worth allocation chip
  paint only on example data. The Benchmark chip stays in Practice and
  Live. A connected
  book keeps the live equity sentence,
  `Allocation (live assets only)`, and `Live from broker`. Mutual
  Funds on example data reads
  `Example NAVs · as of 10-Sep-2026`. Example order review confirms
  with **Continue**. Practice review keeps **Confirm simulation**.
- **First-run Setup finishes on the Practice desk (FT-SETUP-FLOW-001).**
  When the vault is not yet secured, the required path is Create
  operator, then Vault, then the Practice desk (Step 3 of 3). When the
  vault is already secured, that vault step is skipped and the Practice
  desk is Step 2 of 2. The Practice desk is Step 2 or 3; see the
  step-count note below. Affirming Practice lands on `/trade`.
  Authenticator, broker connect, LLM, Monitoring, trading defaults,
  and risk are Later or Skip on that desk. They do not change the
  step count and do not block Practice. On the broker Later path,
  **Continue without a broker** is the primary control above
  FlintTrade Native and OpenAlgo Bridge. First run has no Live
  unlock. Live place stays fail-closed. Live still needs the
  authenticator and PIN later. Persona is not a required first-run
  gate. Refs #282.

- **First-run Setup resume, Start over, and a fixed vault step count
  (FT-SETUP-HARDEN-001).** Reloading `/setup` mid-flow resumes the
  unfinished setup session. **Start over (deletes this unfinished
  operator)** deletes that unfinished operator and restarts at step 1.
  A workspace data wipe is not required for either path. When the vault
  is already secured on this machine, the vault step is skipped and the
  count is fixed from the start: **Step 1 of 2 - Create operator**, then
  **Step 2 of 2 - Practice desk**. That path never shows "of 3". On that
  Practice step only, **Your vault is set up and secured on this
  machine.** appears above **Open Practice desk**. When the vault is not
  yet secured, Setup still shows **Step 1 of 3 - Create operator**,
  **Step 2 of 3 - Vault**, and **Step 3 of 3 - Practice desk**. After
  Setup completes, `/setup` does not restart step 1. A signed-in
  operator is sent to `/trade`. A signed-out operator sees **Setup is
  complete. Sign in to open the desk.** with **Sign in** as the primary
  button. Refs #297.

- **Native Dhan + Kotak Neo Connected (read) smoke (FT-MONDAY-002).**
  The path is native Dhan + Neo on the MSI
  static-IP host with non-funded live REST API smoke
  (quotes / depth / hist / chain where the SDK
  allows). That historical evidence covers REST reads only.
  Neo's v3 async SFeed and order-feed lifecycle is now
  wired and locally synthetic-tested, without claiming
  live-account or market-hours stream proof. Chrome is **Connected
  (read)** / **API smoke** only after persisted REST
  smoke evidence — never login-only, never placeable
  Live orders. Neo has no sandbox: never offer Neo
  Practice; copy is `Live read only until funded
  unlock.` Live place stays fail-closed. Prefer
  native; OpenAlgo is Settings / fallback only.
  `dhanhq` stays on latest stable 2.2.0 (not RC).
  Neo runs `kotakneoapi` 3.0.7 from exact upstream
  `main` `5bb34fae39c4a52a0e6b59d7e2d17090cafc340c`, with
  `v3.0.7` peeled to `53cccc45fe56a193b30ffce3c03c71c5c0378538`
  as the release baseline. The `neo_api_client` import namespace stays;
  the old `neo-api-client` distribution is prohibited. Sandbox proof is
  unavailable because Neo offers no sandbox; live-account/market-hours feed,
  funded-order, Live-promotion, and cross-platform proof remain outstanding.
  Native HTTP freeze
  (Task 9D / Task 7C.2) is not lifted. Refs #253.

- **AI Chat Practice + native live-read context (FT-MONDAY-003).**
  When an LLM is configured, AI Chat may use Practice
  SandboxEngine fills and native live-read feeds for analysis.
  Suggest stays labelled illustrative.
  Chat never shows green **Connected** without a real LLM.
  AI does not place Live orders — Live place stays fail-closed.
  Measure later: profitable alphas are not a release criterion.
  This does not lift the native broker HTTP freeze. Refs #254.

- **Desk chrome: one TopBar + one ticker + flex shell (FT-UX-002).**
  Dual TopBar index slots are replaced by one dedicated
  scrolling TickerStrip under TopBar. TopBar keeps Mode,
  status, and overflow — not a second quote rail. Three
  Settings/Tools entries collapse into one Tools overflow
  menu plus at most one primary Settings entry. App chrome
  is a flex column: TopBar, then the operator status strip when
  one is showing, then the Mode honesty line, then TickerStrip,
  then the route body.
  Trade ships first; the same shell then rolls to Invest,
  Automate, Learn, and Ditto. Not a silent widen of
  FT-UX-001 Compact-only-on-Trade, and not a big-bang
  rewrite.

- **Mode vocabulary and Trade desk density (FT-UX-001).**
  Example is sample data. Practice and Live are the Modes.
  Example Order Pad uses Example Buy / Example Sell; Practice
  keeps Practice Buy / Sell; Live uses Place BUY/SELL Order.
  TopBar session chips (Continuous · CAS · Matching ·
  Post-close · Closed) stay session status (FT-CORE-001).
  Comfortable is the new-install default. Compact Trade at
  ~1280 and wider keeps chart, order pad, and positions
  primary, with ticker, tool ribbon, and watchlist /
  indices collapsed behind one desk-tools toggle. Selecting Compact on Trade at ~1280 and wider always
  starts with that disclosure collapsed.
  At most one primary banner (Example sample > Practice sample >
  Live risk > feed disconnected). External-action gates stay fail-closed
  for Example. Phone product and the marketing site are unchanged.

- **OpenAlgo-style password-first Example; TOTP only before Live (FT-SETUP-002).**
  Setup and daily login are password-only for Example and Practice.
  Authenticator enrolment is optional (“Set up later”) on day one.
  Confirming a live authenticator code enables TOTP for later logins.
  Live unlock still requires that enrolment plus the PIN. The mid-step
  Reset / Start-over wipe from #184 is unchanged.

- **Native broker HTTP freeze (accepted product decision).** Merging this work
  onto `main` leaves native broker UX down until Task 9D and Task 7C.2. That
  is accepted. Broker-account mutations — `/v1` account and auth writes, native
  connect / login / set-primary / delete, OAuth start and callback, and the
  other guarded account-authority routes — return a stable `503` with
  `{error: broker_account_cutover_unavailable}` until Task 9D migrates the
  handlers and removes `guard_broker_account_http` atomically. Native HTTP
  account and market-data reads return `409` with zero provider calls until
  the Task 7C.2 / 8B read-port cutover. The terminal still calls those routes,
  so Setup → Brokers and Settings → Brokers will show the freeze rather than a
  working native session. Service connections remain inert only. OpenAlgo
  bridge setup and gated live writes (`SafetySystem` L1–L5 → `gate_order` /
  `gate_broker_write` → `BrokerRouter`) stay unchanged.

### Fixed

- **Ticker venue badges match the marquee (FT-CORE-TICKER-001).**
  Pinned badges follow the venues that feed the tape: NSE, BSE, and
  MCX on the default tape, and NFO when an F&O symbol feeds. A venue
  with no feeding symbol is omitted. Symbols that do not resolve to a
  venue show **Unavailable**. An empty tape omits the badge strip.
  The marquee runs continuously when motion is allowed. With
  `prefers-reduced-motion: reduce`, the tape freezes and shows
  **Reduced motion**. The Sample freshness chip may stay; it must
  not hide venue honesty.

- **Tools Quick Settings on the Trade desk (FT-UX-QUICK-SETTINGS-001).**
  Tools → Quick Settings opens density, theme, and similar controls
  without leaving the desk. Tools → Settings still opens the full
  Settings route for deep pages (Monitoring, brokers, auth). Compact
  Trade keeps Quick Settings on the TopBar when the tool ribbon is
  collapsed. Dropping Quick Settings so only full Settings remains
  fails desk-first. Refs #279.

- **Docs: correct GTT proxy, Practice walkthrough, and Live safety path.**
  `USER_GUIDE` Practice walkthrough no longer treats Example
  Buy as a sandbox Positions/Orders fill.
  `API.md` no longer claims `/orders/gtt-*` is gated like
  regular Live place — those verbs return HTTP 501 after unlock
  and do not place. `POST /api/v1/orders/forever` does not place.
  `API.md` documents
  `GET /api/v1/advisor/status` `source` (`env` / `stored` /
  `default`). `ARCHITECTURE.md` mode-guards Practice to
  `SandboxEngine` and runs L1–L5 only on Live.
  `DEVELOPER_GUIDE.md` no longer says every order is checked
  by L1–L5: those layers are Live-only. Practice goes to
  `SandboxEngine`. Example placement is `mode_blocked`;
  Example Buy is a local fill.

- **Restore Connected honesty on `/ai` (FT-AI-004 regression).**
  LLM readiness is global config truth (stored Settings
  `#llm` plus explicit `advisor/status`), not Mode-derived.
  Example and Practice share one source. A blank stored
  provider plus the empty→ollama default is **Not
  configured** / **Not installed** — never green
  **Connected**. An explicit `LLM_PROVIDER` env-only
  setup stays **Connected** when `advisor/status` reports
  it usable. Composer stays gated until a provider is
  actually configured.

- **Connected badge matches LLM install state (FT-AI-004).**
  `/ai` Chat (AI Hub) follows the real LLM status from
  Settings → AI / `#llm`, including Managed Ollama
  install state — not a green **Connected** while
  Settings shows **Not installed**. Managed Ollama
  **Not installed** shows **Not installed** (warning
  badge, not green) with a primary **Open Settings → AI**
  CTA to `/settings#llm`. Unconfigured stays
  **Not configured**. Composer input and Send stay
  disabled until the runtime is installed and
  configured — the same bar as FT-AI-002. A provider
  string of ollama is not Connected while the managed
  runtime is absent. A configured-but-broken probe still
  shows **Error** / **Disconnected** with Retry.
  Signals **Live** / **Polling** stay separate from
  Chat LLM readiness.

- **Authed `/home` skips password Welcome Back (FT-HOME-003).**
  `/home` is the canonical Home / Welcome dashboard.
  A signed-in operator who opens it (address bar,
  refresh, or same-tab bookmark) sees the same Home
  as SPA nav (sidebar, Alt+H, TopBar) — not the
  password Welcome Back gate. That gate stays on
  `/welcome` for unauthenticated visitors only.

- **Leverage tab content or honest empty (FT-SET-004).**
  `/settings#leverage` shows real leverage content when
  the broker snapshot is available. When leverage cannot
  be shown — unsupported broker, missing snapshot, or
  load failure — the pane shows the honest empty
  `Leverage settings unavailable.` plus **Retry**.
  Selecting the Leverage tab never leaves a highlighted
  tab over a blank content pane.

- **Kill All fail-closed when risk runtime unavailable (FT-DITTO-003).**
  Whenever the Ditto risk runtime is unavailable —
  including Example `/ditto` Risk — **Kill All
  Positions** stays muted and disabled. Helper:
  `Risk runtime unavailable — Kill All disabled.`
  The control is never the armed red emergency CTA
  in that state. The backend rejects a Kill All if
  the UI slips. Live and Practice with a live
  runtime and managed accounts still keep the
  armed control (empty-account disarm is
  FT-DITTO-001).

- **Log refs no longer create a missing workspace.**
  A cold `log_ref` salt cache no longer calls
  `workspace_dir()` in a way that mkdir's the default
  workspace. Isolated callers (explicit-path TOTP
  stores) stay off the default pair.

- **Example Schedules Pause gated for sample jobs (FT-AUTO-004).**
  Example `/automate` → Schedules seeded jobs: the
  Mode honesty line owns disclosure — no extra
  Sample chip once Pause is gated. Seeded
  Example jobs show status Sample/Demo (or muted),
  not a production-looking Active badge. Pause on
  those jobs is disabled, with title helper `Example
  schedule — control unavailable`.
  Practice/Live jobs keep Pause/Resume. The backend
  rejects Example pause/resume with `mode_blocked`.

- **Example Stock Baskets disable demo Edit/Delete (FT-INVEST-002).**
  Example `/invest#basket` seeded cards (NIFTY IT,
  Banking, and any other sample set): the Mode
  honesty line owns disclosure — no card-level
  Sample chip. Bare ₹ / P&L under that banner is
  acceptable once actions cannot look live.
  Edit and Delete on seeded Example baskets are
  disabled, with title helper `Example basket —
  editing unavailable`. User-created
  Practice/Live baskets keep full Edit/Delete.
  Empty Example is an honest empty or a clearly
  labelled sample set.

- **Feed-freshness honesty (FT-CORE-002).**
  Example disclosure is the Mode honesty line.
  Per-widget Sample chips are retired. Per-symbol
  ticker Sample chips are optional. The Market
  Clock freshness chip appears only when that
  widget is mounted. Practice / Live still need
  TopBar or the ticker: Live · Delayed · Sample
  (and muted Stale / Unknown plus age when
  known). Silent-stale is a fail. Feed provenance
  stays separate from Example and from the Practice and Live
  Modes (Mode honesty).

- **Resource Hub User Guide first-open honesty (FT-LEARN-003).**
  Example `/learn` → Resource Hub → User Guide shows
  `Loading document…` while the local backend/doc
  settles — never a red backend error on a cold race.
  A timeout or race is a muted soft fail:
  `Document isn’t ready yet.` plus a primary **Retry**
  (one automatic retry is allowed). Hard fail copy
  `Couldn’t load this document from the local backend.`
  plus **Retry** appears only after retry is exhausted.
  Order Safety Notes already loading in the same
  session does not mark User Guide permanently broken.

- **Holdings badge matches the visible table (FT-TRADE-010).**
  Practice/Example `/invest` → Holdings with no broker
  shows `N holdings` for the rows currently in the table
  — never `0 holdings` over a populated sample table.
  Dashboard and "N stocks" use the same N. Practice waits
  until the holdings query has settled empty before the
  sample fallback, so a cold load does not flash the
  wrong N. Dashboard `Net Worth (Cash + Holdings + Positions)` uses the
  same shared demo book as Holdings. There is no Sample
  chip on the Holdings table or header. When the sample
  book is shown — Example always, and Practice after that
  empty settle — Holdings and Dashboard keep `DemoBanner`
  (`Showing sample data — connect a broker for live data`)
  in Example as well as Practice. Example also has the
  Mode honesty line (`Example data. No broker is connected and no orders are sent.`). The Practice Mode
  line (`Practice — simulated fills, no real money.`) does not call that book sample;
  `DemoBanner` is the required Practice disclosure for it.
  A broker read failure shows muted `Failed to load holdings`
  plus `Refresh` —
  never `0 holdings`, `No holdings`, or a sample table
  under a failed load. A connected broker with no
  positions shows `0 holdings` and an honest empty state
  (no sample table under a zero badge). Connected
  positions use the live count only.

- **Example Execution Logs mode honesty (FT-AUTO-003).**
  Example `/automate` → Execution Logs shows the muted
  empty state `No execution logs for Example. Switch to Practice or Live to see real run history.`
  and never the outage line on a healthy sample session.
  Practice/Live with a 200 OK and 0 rows use
  `No execution logs for this date.` — not an outage.
  The red `Failed to load logs. Backend may be offline.`
  copy (with Retry) is reserved for a real load failure.
  Loading shows a spinner / `Loading logs…` and never
  flashes the outage line.

- **SEBI CAS session clock / TopBar phases (FT-CORE-001).**
  TopBar market-status chips are Continuous · CAS ·
  Matching · Post-close · Closed (one active).
  Tooltip/title is the window, e.g.
  `CAS · 15:15–15:35 (as of Aug 2026)`. When
  equity F&O still runs after cash continuous ends, a
  secondary `F&O open · till 15:40` chip appears.
  Market Clock follows Continuous (~09:15–15:15)
  → CAS 15:15–15:35 → Matching → Post-close
  15:50–16:00. Non-CAS cash still continuous to
  15:30. Cash is never green "open" after 15:15;
  CAS is not Closed. Flat "Market open until
  15:30" and "VWAP last 30 min" closing-price
  copy are gone. The September 2026 consultation
  stays out of the UI.

- **Position Mirror Start fail-closed gate (FT-DITTO-002).**
  Example `/ditto` → Position Mirror Start stays
  muted and disabled when unavailable — never
  the primary green armed CTA. Example is
  always disarmed (sample-only). Helper:
  `Mirroring is blocked for Example. Switch to Practice or Live with broker accounts connected.` Practice stays disarmed
  — the backend is Live-only. Helper:
  `Mirroring requires Live with broker accounts
  connected.` Live enables Start only with a
  source selected, at least one target, and
  broker accounts ready. Missing source/targets:
  `Select a source account and at least one
  target to start mirroring.` A successfully
  empty account list: `Connect a source and at
  least one target account to start mirroring.`
  Pending and failed account fetches stay muted
  with `Loading accounts...` / `Could not load
  accounts.` and never look like an empty
  connect state. The backend rejects Example,
  Practice, or incomplete starts
  (`mode_blocked` or equivalent).

- **Example Scalper fail-closed order path (FT-TRADE-009).**
  Example `/trade` → Scalper is disarmed —
  Buy CE / Sell / 1-CLICK never open Confirm
  Order and never place. Buy/Sell stay disabled.
  Helper: `Orders are blocked for Example. Switch to Practice or Live with a broker connected to trade.` 1-CLICK stays
  OFF / disabled; title `One-click is unavailable
  for Example`. Sample quote preview is allowed;
  Confirm BUY / Confirm SELL chrome is not.
  Practice and Live use Confirm only when the
  mode allows it and a gateway is configured.
  The backend rejects Example orders with
  `code: mode_blocked` if the UI slips.

- **OI Chart shares Option Chain expiries (FT-TRADE-007).**
  Example `/trade` Analysis layout → maximize OI Chart
  now shares Option Chain expiries for the
  symbol/exchange. A non-empty list shows the
  expiry control; charts and statistics cover
  only the selected expiry (the chain’s
  selection when both widgets are open;
  otherwise the nearest listed). Example sample
  expiries stay listed. The Mode honesty line is
  the disclosure — expiries are not badged Sample.
  No expiries or no OI is an honest empty —
  `No expiries for this symbol` or `No OI for
  this expiry` — with no bars and no PCR/max-pain
  stats, never “No expiries” over fake charts.

- **Watchlist LTP / % change use ticker sample quotes (FT-TRADE-008).**
  Example `/trade` → Watchlist with Sparkline + LTP +
  % change checked now paints those column headers
  and cells. LTP and % change read the same sample
  quote source as the ticker tape (Jotai tick atoms
  from the Example demo feed) for NIFTY, BANKNIFTY,
  SBIN, RELIANCE, HDFCBANK, and any other symbol on
  that feed. The Mode honesty line is the disclosure.
  Missing quotes show `—` (or a brief `…` while the
  first fetch is in flight), never silent blank
  chrome. Unchecking a column hides it; checking it
  again shows the sample value or the honest empty.

- **Options Builder Net Debit and Max Loss share a position ₹ basis (FT-LAB-005).**
  Example `/lab` Options Builder now shows Net
  Debit/Credit, Max Loss, and Max Profit on a
  shared position ₹ basis. Net Debit/Credit is
  the signed premium × lots × lot size. Max
  Loss and Max Profit are expiry-payoff results
  (intrinsic at the strikes, strike width, or
  unlimited) scaled to that same position basis
  — not premium × lots × lot size on every card.
  For a long call, Max Loss equals the Net Debit
  (the premium paid for the position). A muted
  sublabel `₹X per lot · N lots · lot size L`
  sits under those figures and is never the only
  number. Header and Legs chips use the same
  position basis as Payoff. When lots differ and
  a single per-lot breakdown cannot be formed,
  the primary figure is tagged `position` —
  never two unlabelled ₹ on mixed bases.
  Blank premiums still show `—` (FT-LAB-003).

- **Backtest headline P&L vs trade-log (FT-LAB-004).**
  Example `/lab` backtest results now show labelled
  dual metrics. **Total Return (%)** is initial
  capital → final equity (including a forced last-bar
  close), with subtitle `Initial capital → final
  equity`. Live `total_return` percentage points are
  not passed through `fmtPct` a second time.
  **Net trade P&L (₹)** sums Trade Log `net_pnl`
  when present; if `net_pnl` is missing the card is
  labelled **Trade log P&L** with `Gross — net P&L
  not in result` rather than calling a gross sum net.
  When that sum matches the equity change, a quiet
  `Reconciles with trade log` note appears; when
  they diverge (fees, open marks, partial fills)
  both numbers stay visible with
  `Trade log sum ≠ equity change — fees / open
  marks`. Monthly P&L stays trade-based so the
  chart matches the log.

- **Learn Glossary Lot Size freshness (FT-LEARN-002).**
  Example `/learn` → Glossary → Lot Size now teaches the
  Jan 2026 NSE-cycle index lots — NIFTY 65, BANKNIFTY 30,
  FINNIFTY 60, MIDCPNIFTY 120 — with an explicit “as of”
  date and a Verify on NSE link to circular NSE/FAOP/70616
  (3 Oct 2025). Stale `NIFTY=25` / `BANKNIFTY=15` copy is
  gone. Learn market facts that exchanges revise must ship
  dated, not as forever hardcodes. Independent of #213
  (FT-UX-001).

- **Performance follows the Review date range (FT-TRADE-006).**
  Trade Review **Performance** uses the same date range as
  Log and the other Review tabs. Changing Review dates
  updates Performance. A visible **Review range** | **YTD**
  control keeps YTD as an explicit choice; the active chip
  always shows the effective window (for example
  `YTD · 01 Jan–11 Sep 2026`). Opening Performance no longer
  auto-jumps to YTD. An empty range or no fills is an honest
  empty for that window, not a quiet YTD fallback. Metrics
  cover the labelled window up to the journal's 1,000-fill
  analytics page; a larger window is disclosed rather than
  silently sliced.

- **Heatmap Group by Exchange shows labelled group bands (FT-TRADE-005).**
  Example `/trade` Positions → Heat → Group by Exchange (and
  Group by Sector) now draws a labelled band per group: a
  name chip (`NSE`, `NFO`, …) plus an optional exposure
  sublabel, with a stronger gutter than the leaf-tile
  borders. A single group still carries its label. Positions
  with no exchange metadata show `No exchange groups in these
  positions` instead of an undifferentiated treemap. Flat
  stays leaf-only, with no group chrome.

- **Example Mutual Fund NAVs no longer claim a daily AMFI feed (FT-INVEST-001).**
  Example data on `/invest#mutual-funds` labels the fixture
  `Example NAVs · as of 10-Sep-2026` and drops “Updated daily
  after market close.” The sample date was refreshed once so
  the as-of is not months stale; it does not auto-update.
  Practice and Live keep the daily-update sentence when the
  live AMFI feed is in use.

- **Options Builder Example Long Call no longer looks zero-risk (FT-LAB-003).**
  Example `/lab` Options Builder now treats a blank premium as
  unknown: Payoff summary cards show `—` and
  `Enter premium to model payoff` instead of modelling ₹0.
  The Long Call template seeds the Example sample-chain ATM CE
  LTP, labelled `Sample premium — edit to model`, so Max Loss
  and breakeven follow FT-LAB-001 maths on a non-zero cost.
  Typing an explicit ₹0 still uses that maths and warns
  `Premium is ₹0 — payoff treats cost as free`.

- **Security PIN requires exactly six digits (FT-SET-003).**
  Example `/settings#security` keeps New and Confirm as digits-only
  fields with `maxLength` 6. Set/Change PIN stays disabled until the
  account password is present, both fields are exactly six digits,
  and they match. Blurring a field with 1–5 digits shows
  `PIN must be exactly 6 digits`; blurring Confirm when both are
  filled and different shows `PINs do not match`. A five-digit value
  no longer looks valid. `POST /v1/auth/pin/set` still rejects
  anything that is not `^\d{6}$`.

- **Progressive TopBar collapse at ~390px (FT-MOBILE-002).**
  The terminal chrome no longer clips workspace, status, or ticker
  behind a horizontal TopBar scroll at about 390px. Logo mark, the chip
  (Example, Practice, or Live), and compact session/status stay
  visible and tappable. The ticker strip hides first (default off
  under ~480px). Workspace, account, Tools, search, fullscreen, and
  clock move into a More overflow menu with hit targets of at least
  44px. Workspace and ticker stay reachable via More; no control is
  clipped and unreachable.

- **Suggest recommendations refresh when mood changes (FT-AI-003).**
  Example `/ai` Suggest treats market mood as a filter, not a draft.
  Changing mood (chip or **Next mood**) immediately replaces the
  recommendation list and the selected mood chip from one mood
  state. A previously focused strategy card is cleared, so a prior
  mood's card (for example Iron Condor after leaving Sideways)
  cannot remain. An empty mood + risk match shows an honest empty
  state with **Try another mood**.

- **Honest unconfigured LLM state on `/ai` (FT-AI-002).**
  `/ai` Chat probes `advisor/status` (including Example /
  `demo-user`) and aligns the badge and composer with Settings
  `#llm` hydration — not a stale local store, and not an
  env-default `configured: true` while Settings looks empty.
  Unconfigured shows a warning **Not configured** badge, empty
  **LLM not configured**, a primary **Open Settings → AI** CTA to
  `/settings#llm`, and an outline **Retry**. When a leftover
  transcript hides that empty state, the header still offers
  **Retry** and **Open Settings → AI**. Returning to Chat after
  saving Settings → AI re-checks readiness. The composer input and
  Send stay disabled, so there is no send-then-`no reply` path. A
  configured but broken probe shows **Error** / **Disconnected**
  with Retry — never a green Connected. Signals **Live** /
  **Polling** stay separate from Chat LLM readiness. Do not add a
  fake Connected sample advisor in Example; any later demo replies
  must be labelled **Sample replies**.

- **Telegram Send Test stays enabled in Example (FT-AUTO-002).**
  Example `/automate#settings` Telegram Alerts now disables Send Test
  and keeps the prefilled message as a preview-only sample. Helper:
  `Telegram tests are blocked for Example. Switch to Practice or Live with Telegram configured to send a real test.`
  Practice and Live enable Send Test only when Telegram is configured;
  otherwise the control stays disarmed with "Configure Telegram first".
  The backend rejects Example test sends with `mode_blocked`.

- **Practice Trading has no OpenAlgo Gateway setup CTA (FT-LEARN-001).**
  Example `/learn` Practice Trading now links to Settings → Broker
  Gateway (`/settings#api`) so operators can configure OpenAlgo.
  On ~390px the Learn section tabs stack above the page instead of
  a 224px side column, and Practice copy, lists, sandbox rows and
  the Gateway button wrap. The CTA does not send operators to
  native Brokers.

- **P&L columns unusable at ~390px (FT-MOBILE-001).**
  Example `/trade` Positions and Invest Holdings switch to stacked
  cards below 480px, so each row shows symbol, quantity, LTP, P&L
  and P&L% on one screen. The wide nowrap table no longer clips
  those figures off-screen behind a tiny scrollbar.

- **Invest deep-link hash tabs ignored on load (FT-ROUTE-001).**
  Opening `/invest#holdings` (and the other Invest tab hashes)
  now selects the matching tab on load. A direct `#holdings`
  URL no longer falls back to Dashboard.

- **Duplicate Watchlist widgets from Add widget picker (FT-HOME-002).**
  Example `/home` Add widget no longer adds a second Watchlist when
  one is already on the dashboard. Already-present widget types are
  disabled or hidden in the picker; choosing Watchlist focuses the
  existing card instead of duplicating it.

- **Broker Gateway and Ditto default URLs diverge (FT-SET-002).**
  Example `/settings#api` Broker Gateway and Example `/ditto` Add
  Account now share the OpenAlgo default `http://127.0.0.1:5000`.
  Add Account prefills the saved Gateway host and REST port
  without retaining the bridge API key, so the two forms no
  longer silently default to ports 5000 and 5001.

- **Home greeting uses local evening at noon IST (FT-HOME-001).**
  Example `/home` greets from the Asia/Kolkata clock, so ~12:01 IST
  is Good afternoon (or Good morning before noon), not Good evening
  from a non-IST browser clock.

- **Market status closed during NSE regular hours (FT-TRADE-004).**
  Example `/trade` header treats OpenAlgo/Example session timings
  as IST clock hours (09:15–15:30 on weekdays), not epoch
  milliseconds. Mid-session no longer shows a false
  “Market closed”. After hours and weekends stay closed.

- **Chart stays stale when timeframe selector changes (FT-TRADE-003).**
  Example `/trade` timeframe buttons now refresh the chart
  series and visible range to match the selected interval.
  Switching 5m → 1D no longer leaves candles and intraday
  timestamps on the prior range, or a brief blank that stays
  stale.

- **Empty Monitors has no Strategy Builder/Lab CTA (FT-AUTO-001).**
  Example `/automate` Monitors empty state now includes an
  "Open Strategy Builder" link to `/lab`. Operators no longer
  have to find Strategy Lab independently from copy-only text.

- **Settings `#llm` load failure with no recovery (FT-SET-001).**
  Example `/settings#llm` no longer treats a demo or unconfigured
  session as a broken load. It shows an empty LLM state with Retry
  and guidance that Example cannot persist LLM secrets. Live still
  fail-closes on a real load error to protect a saved configuration,
  and now offers Retry.

- **Kill All Positions armed on empty Example Ditto dashboard (FT-DITTO-001).**
  Example `/ditto` Risk Dashboard with ₹0 totals and no accounts
  listed now disables Kill All Positions and shows an empty
  state. The control is no longer a bright red armed emergency
  CTA on an empty dashboard. Live and Practice with managed
  accounts still keep the armed control.

- **Practice orders in Example without a live broker (FT-TRADE-002).**
  Example `/trade` Order Pad Practice Buy opens the Practice review and
  records a sample fill — no live broker is required. Live still
  uses the gated `placeOrder` path and still requires a broker
  connection. Native broker freeze is excluded.

- **Daily Sign In 2FA field while authenticator is deferred (FT-SETUP-002).**
  Login Sign In probes `/auth/status` every time it is shown and hides
  2FA unless `totp_enabled` is explicitly true. A stale Welcome
  `totpRequired={true}` after Sign Out can no longer keep the field.
  Enrolment still requires TOTP; Live still needs enrolment plus PIN.

- **Duplicate zero placeholders on backtest metrics (FT-LAB-002).**
  Example `/lab` backtest headline metrics (Sharpe ratio, max
  drawdown, win rate, profit factor) now show a single formatted
  value. The leftover count-up `0.00` / `0.00%` beside the real
  figure is gone.

- **Example Ctrl+K symbol search false unavailable error (FT-CMD-001).**
  Example `search` now uses the same sample-instrument catalogue as
  Example quotes and history. Ctrl+K → Symbols → NIFTY returns
  sample hits (NIFTY, BANKNIFTY, FINNIFTY) instead of a false
  connection error. Live and Practice still use native / OpenAlgo
  search.

- **Zero-premium long-call payoff (unbounded max profit + breakeven) (FT-LAB-001).**
  Options Builder Payoff now summarises expiry P&L from strike kinks
  and the right-hand slope, not the ±15% chart sample. A zero-premium
  long call shows Unlimited max profit, max loss equal to the premium
  (₹0), and breakeven at the strike. Paid-premium long calls and
  other unbounded legs (short calls, straddles) use the same rule.

- **Trade Review date filter and mangled timestamps in Example (FT-TRADE-001).**
  Example `/trade` Trade Review now clips the Log to the committed IST
  date range (the same predicate as the sample-journal badge) and
  renders fill timestamps as `D Mon YYYY HH:MM:SS` with a literal
  space, so `13 Apr 26` can no longer glue onto `14:55:42`. Live and
  Practice still use the journal/tradebook path; only the shared IST
  format and range helpers changed there.

- **Example /ai chat produces no assistant reply (FT-AI-001).**
  `/ai` and the floating tutor now share one advisor chat path:
  a short status probe (including Example/sample-data), SSE
  streaming, then the non-streaming fallback. A missing LLM, an
  unreachable backend, an empty completion, or an SSE error
  becomes a visible assistant error instead of a blank bubble.
  Empty assistant placeholders are no longer persisted, so a
  reload cannot restore the silent blank. The 45-second stream
  budget is first-token only: once a token arrives, a longer
  healthy completion is not aborted mid-reply. Native broker
  freeze is excluded. MF Optimizer and AI suggestions + deploy
  are unchanged.

- **Unfinished Setup recovery without the authenticator (FT-SETUP-001).**
  **Try with example data** marks a durable Example session so `/home`
  survives a refresh. **Start over** wipes the unfinished account via
  the account-create setup JWT, so a lost QR seed is recoverable
  without the TOTP secret. Daily-login session tokens cannot wipe the
  account. Daily login is password-only until an authenticator is
  enrolled. Live still needs that authenticator and the PIN.

- **Strategy Lab stays empty after AI Deploy (FT-DEMO-002).**
  Deploying a suggestion from `/demo-app/ai` (for example “Trend EMA
  Crossover”) opens `/demo-app/lab?strategy=TrendEMACrossover`. Strategy
  Lab now hydrates the Backtest selector from `?strategy=`, keeps a
  linked registry key in the catalogue when the loaded list does not
  include it, and enables Run Backtest once a strategy is selected.
  Sample demo backtests are unchanged; a Lab opened without the query
  is unchanged.

- **Invest dashboard holdings count vs listed sample stocks (FT-DEMO-001).**
  On `/demo-app/invest` the sample dashboard header now uses the example-data
  holdings book (`getDemoHoldings`) as its count source, so the
  badge matches the listed sample stocks and the Holdings tab. Live and
  Practice still read the live book — an empty funded account stays at
  0.

- **Remaining homepage nav overflow at ~390px (FT-SITE-003).** After
  #180, the primary nav wrapped without clipping Contribute, but at
  about 390px four chips still packed onto the first row and left
  “Demo (example data)” cramped against Docs/API. Below 480px the marketing
  nav now uses two-across chips with slightly smaller type and tighter
  padding, so every primary label stays on one line with slack. The
  900px wrap from #180 is unchanged.

- **Docs page summary duplicated as first body paragraph (FT-SITE-002).**
  On `/docs*` routes the page summary no longer appears twice. The
  generator still lifts the first body paragraph into frontmatter for
  SEO, but marks `hideDescription` when that extract matches the opening
  body paragraph. The docs page skips `DocsDescription` unless the page
  opts in with a distinct subtitle (fail-closed if the flag is missing).

- **Primary nav overflow clips Contribute (FT-SITE-001).** The marketing
  header no longer uses a shrinking `overflow-x: auto` row below 900px.
  Primary links wrap without shrinking, so Contribute and the other
  destinations stay fully visible on phones around 390px.

- **Dependabot qs and fflate (medium).** `qs` 6.15.2 (via `http-server` →
  `union`) is overridden to 6.16.0, clearing GHSA-4mjr / GHSA-px8p. `fflate`
  0.6.10 (via `three-stdlib`) is overridden to 0.6.11, clearing GHSA-x5fp.
  No new allowlist entries.

- **Node audit blockers on main.** Newly disclosed HIGH/CRITICAL advisories
  against the existing lock (next Windows/AVIF RCE, maplibre-gl XSS,
  `@xmldom/xmldom` name-injection/ReDoS, sharp libheif, js-yaml merge-key
  DoS, and four fast-uri host-confusion/SSRF issues) are cleared by real
  version bumps: next 16.3.4, and overrides for fast-uri 4.1.4, js-yaml
  4.3.2, sharp 0.35.4, maplibre-gl 6.8.0 and `@xmldom/xmldom` 0.8.15. No
  new allowlist entries.

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

### Security

- **Clear-text secret logging in service-connection tests.** CodeQL
  `py/clear-text-logging-sensitive-data` alerts
  [#420](https://github.com/navaneeshnagarajan/FlintTrade/security/code-scanning/420)
  and
  [#421](https://github.com/navaneeshnagarajan/FlintTrade/security/code-scanning/421)
  flagged `packages/core/core/tests/test_service_connections.py` for passing a
  `secret_version` object to `logger.debug`. The redaction contract still
  asserts that binding identity and supplied credential material never appear
  in `str`/`repr`, public DTOs, exception text, or captured logs; the logger
  now receives only the masked `ServiceSecretVersion(<redacted>)` fixture.

## [0.0.1] — 2026-07-23

Clean-slate baseline. Pre-1.0, pre-usable, and marked as a pre-release: anything
may change without notice until the project reaches a stable 1.0.0.
