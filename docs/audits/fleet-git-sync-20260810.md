# FlintTrade fleet Git synchronisation — 2026-08-10

This manifest records the remote-preservation pass across Linux, macOS and Windows. Archive refs preserve work; they do **not** imply review acceptance, merge readiness, or deployment approval. The public `main` branch was not changed.

## Primary nightly branches

| Platform | Remote branch | Exact SHA | State |
|---|---|---|---|
| Linux | `fix/nightly-ubuntu-31293999155` | `62f79391df28c9d67b777f563f218dd2d1a4c83e` | reviewed branch |
| macOS | `fix/mac-nightly-ci-148b5795` | `b9381f571527a723682ddadfcb64334b7482d528` | native PASS branch |
| Windows | `fix/nightly-windows-ci-31293999155` | `5946668b2e2dc2ffeb14b5352e0b15accf44199c` | preserved for independent acceptance |

## Exact committed archive refs

These refs publish exact local commit graphs after a deterministic credential/privacy scan.

| Host | Local branch label | Remote archive ref | Exact tip |
|---|---|---|---|
| linux | `agent/codex-operational-status` | `archive/fleet-20260810/linux/agent/codex-operational-status` | `a17f58f7b61bf040a4f12a883c62b9c6e247ad61` |
| linux | `agent/grok-orders-positions-state` | `archive/fleet-20260810/linux/agent/grok-orders-positions-state` | `f28d6b17a303b69d19c92109db36ee5d783cb233` |
| linux | `agent/grok-symbol-search-error` | `archive/fleet-20260810/linux/agent/grok-symbol-search-error` | `69f97ded9601ed76cbe29b6f230f62720e8cf25c` |
| linux | `feature/ai-symbol-context` | `archive/fleet-20260810/linux/feature/ai-symbol-context` | `6124f2a4455aa24f094b4bb370f0ceaf887d50b5` |
| linux | `feature/practice-order-review` | `archive/fleet-20260810/linux/feature/practice-order-review` | `3c7beb54981d60bf1fa3f1855c620468f18cc02b` |
| linux | `feature/setup-canonical` | `archive/fleet-20260810/linux/feature/setup-canonical` | `2c6bbcc4064095be6eb84b16838b3e04a731ff8b` |
| linux | `feature/site-threejs-enrichment-pilot` | `archive/fleet-20260810/linux/feature/site-threejs-enrichment-pilot` | `4066e1ea1e0bf78113ea851b1e97caaa10f5d069` |
| linux | `feature/terminal-e2e-foundation-e039` | `archive/fleet-20260810/linux/feature/terminal-e2e-foundation-e039` | `087313ccb32482241f4049fc5774f6d613c3c515` |
| linux | `fix/operational-refresh-a17f58f7` | `archive/fleet-20260810/linux/fix/operational-refresh-a17f58f7` | `81bc7ce005618b2969d38ca1c7a2ed26bc95f5bd` |
| linux | `fix/orders-query-truth-7974b44f` | `archive/fleet-20260810/linux/fix/orders-query-truth-7974b44f` | `8d76cc3ef57e974ef11b4857f1decf4d9b81fd79` |
| linux | `fix/workspace-failclosed-ddc64756` | `archive/fleet-20260810/linux/fix/workspace-failclosed-ddc64756` | `c5e1fe60dfd6d8099fe4dc8c58f6b103a7720e26` |
| linux | `integration/unfinished-jobs-20260809` | `archive/fleet-20260810/linux/integration/unfinished-jobs-20260809` | `6ea819d3c71281e93c0e5c3bd729fb7d285b3cb6` |
| linux | `review/mac-docs-truth-2ec994c4` | `archive/fleet-20260810/linux/review/mac-docs-truth-2ec994c4` | `2ec994c4bd2d82cfe11e37b0b482d45a1777f609` |
| linux | `review/mac-docs-truth-a981500c` | `archive/fleet-20260810/linux/review/mac-docs-truth-a981500c` | `a981500c2fd68fca79e0073dd7ee18e6ba7aa612` |
| linux | `review/mac-public-site-c6839fbd` | `archive/fleet-20260810/linux/review/mac-public-site-c6839fbd` | `c6839fbdd8bf7dac87ba10842f21b7802771a473` |
| linux | `review/mac-public-site-c8b3e4f0` | `archive/fleet-20260810/linux/review/mac-public-site-c8b3e4f0` | `c8b3e4f0a5713b7a051d661b55c109588b116758` |
| linux | `review/mac-public-site-f0bb8b68` | `archive/fleet-20260810/linux/review/mac-public-site-f0bb8b68` | `f0bb8b68adb57c7178e9093aeaa98bc5db61ded4` |
| linux | `review/mac-public-site-truth-cta-c8b3e4f0` | `archive/fleet-20260810/linux/review/mac-public-site-truth-cta-c8b3e4f0` | `c8b3e4f0a5713b7a051d661b55c109588b116758` |
| linux | `review/mac-workspace-ddc64756` | `archive/fleet-20260810/linux/review/mac-workspace-ddc64756` | `ddc647565c9ecf78def63d545e9237109b5ee01c` |
| linux | `review/pnl-explore-provenance-6beb063b` | `archive/fleet-20260810/linux/review/pnl-explore-provenance-6beb063b` | `6beb063b4a64aeab8c2fcadbf28f29f54e34f668` |
| linux | `review/windows-graphite-a1-35145553` | `archive/fleet-20260810/linux/review/windows-graphite-a1-35145553` | `3514555307286667d8a5c9d48e0b6dfef35ed924` |
| linux | `review/windows-graphite-a1-a4bebe07` | `archive/fleet-20260810/linux/review/windows-graphite-a1-a4bebe07` | `a4bebe0774bac36c8dba7814ecf0d740e455e087` |
| linux | `review/windows-orders-7974b44f` | `archive/fleet-20260810/linux/review/windows-orders-7974b44f` | `7974b44fa18c24914ee4e88f30ff18dc79c8da58` |
| linux | `review/windows-slice3-1c22bd01` | `archive/fleet-20260810/linux/review/windows-slice3-1c22bd01` | `1c22bd01f8e85ef72450d7e35dd695ad9448c43f` |
| linux | `review/windows-ux-slice1-13f4bcbb` | `archive/fleet-20260810/linux/review/windows-ux-slice1-13f4bcbb` | `13f4bcbb311d767cd6a25b4664041f24bedae2a1` |
| linux | `review/windows-ux-slice1-23dfdf50` | `archive/fleet-20260810/linux/review/windows-ux-slice1-23dfdf50` | `23dfdf50e88bb9aa6a224a4f30d0c139d306f93a` |
| linux | `review/windows-ux-slice1-2aaaa6ab` | `archive/fleet-20260810/linux/review/windows-ux-slice1-2aaaa6ab` | `2aaaa6ab254b451c856f2204d3a188c839f2a345` |
| linux | `review/windows-ux-slice1-5635b592` | `archive/fleet-20260810/linux/review/windows-ux-slice1-5635b592` | `5635b592a5caf3c5cf245a3067183aafc319aee3` |
| linux | `review/windows-ux-slice1-5a5c160e` | `archive/fleet-20260810/linux/review/windows-ux-slice1-5a5c160e` | `5a5c160e3e7883fe270d42153b46cafd1f1a1e32` |
| linux | `review/windows-ux-slice2` | `archive/fleet-20260810/linux/review/windows-ux-slice2` | `4f5823c914a2f141e71a627ce3b0649a01c70ad1` |
| linux | `review/windows-ux-slice2-a5a291a9` | `archive/fleet-20260810/linux/review/windows-ux-slice2-a5a291a9` | `a5a291a94c01a9a260b881f5b10f557579c54941` |
| mac | `wt/flinttrade-operational-refresh-account-truth-v1` | `archive/fleet-20260810/mac/wt/flinttrade-operational-refresh-account-truth-v1` | `a17f58f7b61bf040a4f12a883c62b9c6e247ad61` |
| mac | `wt/flinttrade-workspace-correction-ddc64756-v1` | `archive/fleet-20260810/mac/wt/flinttrade-workspace-correction-ddc64756-v1` | `ddc647565c9ecf78def63d545e9237109b5ee01c` |
| mac | `wt/linux-t_1a9142b9-workspace-impl` | `archive/fleet-20260810/mac/wt/linux-t_1a9142b9-workspace-impl` | `ddc647565c9ecf78def63d545e9237109b5ee01c` |
| mac | `wt/linux-t_aacfbecd-docs-truth` | `archive/fleet-20260810/mac/wt/linux-t_aacfbecd-docs-truth` | `a981500c2fd68fca79e0073dd7ee18e6ba7aa612` |
| mac | `wt/nightly-macos-ci-31293999155` | `archive/fleet-20260810/mac/wt/nightly-macos-ci-31293999155` | `7ff49dd0407c7fdb2b7715bc172d28e94e06522f` |
| mac | `wt/public-site-truth-cta` | `archive/fleet-20260810/mac/wt/public-site-truth-cta` | `f0bb8b68adb57c7178e9093aeaa98bc5db61ded4` |
| windows | `codex/fix-cross-platform-web-installs` | `archive/fleet-20260810/windows/codex/fix-cross-platform-web-installs` | `2d9bcbdd3e33d2d524562c743335986ce613fc79` |
| windows | `feat/mcp-2026-dual-era` | `archive/fleet-20260810/windows/feat/mcp-2026-dual-era` | `a35cc4796f6238c5196f2961a5d9e24310cd3615` |
| windows | `wt/docs-page-pilot-1377794f` | `archive/fleet-20260810/windows/wt/docs-page-pilot-1377794f` | `c75c4979982fc55a12742ffb48d915b845439d35` |
| windows | `wt/orders-positions-correction-7974b44f` | `archive/fleet-20260810/windows/wt/orders-positions-correction-7974b44f` | `7974b44fa18c24914ee4e88f30ff18dc79c8da58` |
| windows | `wt/orders-positions-sol-impl` | `archive/fleet-20260810/windows/wt/orders-positions-sol-impl` | `7974b44fa18c24914ee4e88f30ff18dc79c8da58` |
| windows | `wt/pnl-explore-provenance-main-20260810` | `archive/fleet-20260810/windows/wt/pnl-explore-provenance-main-20260810` | `1f85d989e1569ec25837e3d83f580783240e0e42` |
| windows | `wt/ux-slice1-modes-labels` | `archive/fleet-20260810/windows/wt/ux-slice1-modes-labels` | `23dfdf50e88bb9aa6a224a4f30d0c139d306f93a` |
| windows | `wt/ux-slice2-home-trade` | `archive/fleet-20260810/windows/wt/ux-slice2-home-trade` | `a5a291a94c01a9a260b881f5b10f557579c54941` |
| windows | `wt/workspace-hybrid-clone-failclosed-c5e1` | `archive/fleet-20260810/windows/wt/workspace-hybrid-clone-failclosed-c5e1` | `ae35d388c6e5a13036e16b20876733484b047a4f` |

## Sanitised archival snapshots

The exact local history for these lines contains machine-specific paths. Because this repository is public, that history was **not** published. A new snapshot commit preserves the final tree after replacing machine-specific strings. These snapshots are archival only.

| Host | Local branch label | Source local tip (not public) | Remote snapshot ref | Snapshot SHA | Sanitised files |
|---|---|---|---|---|---|
| linux | `feature/phase4-practice-proof` | `5db973904024c0c37cf2abfbfe48d57dfa2d0d10` | `archive-sanitized/fleet-20260810/linux/feature/phase4-practice-proof` | `759db85a8d4e9855f18a33d5b7b7788eba6ba33a` | 1 |
| linux | `feature/phase4-practice-proof-v2` | `c33d96561bdd16dff030bc3bc23ed87ec0fc57ae` | `archive-sanitized/fleet-20260810/linux/feature/phase4-practice-proof-v2` | `afb7dc8f620c5b16dc41f9bdb4aa6f124331b1e2` | 1 |
| linux | `fix/hostinger-staging-8d31a9a8` | `dea645973fc126d6e495c2ec57f320d16cc8a0a9` | `archive-sanitized/fleet-20260810/linux/fix/hostinger-staging-8d31a9a8` | `6cfd742c77469e7e2ec7509b4d6db1c364bfb6c9` | 0 |
| linux | `integration/site-3d-staging-20260809` | `d483ebc3c9b9c9927a2a027305f22999ded86b34` | `archive-sanitized/fleet-20260810/linux/integration/site-3d-staging-20260809` | `db11df2f018759ef33f8080a6b86f4f3e68b79f8` | 0 |
| linux | `integration/terminal-accepted-core-20260809` | `c83656e46314896b55a2206e789f8ba898741365` | `archive-sanitized/fleet-20260810/linux/integration/terminal-accepted-core-20260809` | `3e3eed1dcdbe3457a2f10185ae3f308fc80d8299` | 0 |
| linux | `review/windows-hostinger-8d31a9a8` | `8d31a9a80a3c39df757a157da06e058f175082a1` | `archive-sanitized/fleet-20260810/linux/review/windows-hostinger-8d31a9a8` | `6bf8bcae6e0ec231c1879630633e87d683a82a67` | 3 |
| windows | `wt/hostinger-local-staging-prep-e039` | `350335bfc3a5874466d054cf2cf80ba0b5e76053` | `archive-sanitized/fleet-20260810/windows/wt/hostinger-local-staging-prep-e039` | `e22f935af4fe3922643b71cd5f79fbe9fba6cd44` | 1 |

## Uncommitted-work snapshots

Existing worktrees were left unchanged. Real tracked/untracked work was copied into synthetic archival commits; generated dependency directories were excluded. Lockfile-only drift is preserved but not accepted.

| Host | Local branch label | Parent tip | Remote WIP ref | Snapshot SHA | Paths |
|---|---|---|---|---|---|
| linux | `feature/phase4-practice-proof-v3-real` | `dec2393c980bf63b1138f70461df9aafa66baa88` | `archive-wip/fleet-20260810/linux/feature/phase4-practice-proof-v3-real` | `c776602ff9e632f0d8d941f70ad25affb19e9075` | 2 |
| linux | `agent/grok-workspace-lifecycle` | `dec2393c980bf63b1138f70461df9aafa66baa88` | `archive-wip/fleet-20260810/linux/agent/grok-workspace-lifecycle` | `252e883e45e417b86ae0e4bf76436e123ef5de7b` | 12 |
| linux | `agent/grok-orders-positions-state` | `f28d6b17a303b69d19c92109db36ee5d783cb233` | `archive-wip/fleet-20260810/linux/agent/grok-orders-positions-state` | `390087fe1ebf3e9b7c27bd9505fd75e22e73a18c` | 9 |
| mac | `wt/graphite-continuity-a1-1b49ed1c` | `e5ae68074fe2d9ad2e0fde7eaa848570b4e2a53a` | `archive-wip/fleet-20260810/mac/wt/graphite-continuity-a1-1b49ed1c` | `909838de9b59d4e9f7fb8b61f6451b67577f9c29` | 3 |
| mac | `wt/flinttrade-workspace-correction-ddc64756-v1` | `ddc647565c9ecf78def63d545e9237109b5ee01c` | `archive-wip/fleet-20260810/mac/wt/flinttrade-workspace-correction-ddc64756-v1` | `8cae72b40cb5491d65e9970216efcfc3a8fc86c5` | 1 |
| windows | `wt/workspace-hybrid-clone-failclosed-c5e1` | `ae35d388c6e5a13036e16b20876733484b047a4f` | `archive-wip/fleet-20260810/windows/wt/workspace-hybrid-clone-failclosed-c5e1` | `ce268270c5485a3f318e1a1a8ffeb1f315bb8608` | 1 |

## Intentionally excluded material

- Generated `node_modules` directories were not archived.
- No credentials, secret files, broker/account/order state, logs, databases, local agent state, deployment state or Live-trading material was published.
- Exact histories containing machine-specific paths remain local; only their sanitised final-tree snapshots are public.
- No PR, merge, tag, release or deployment was created.

## Verification

- Exact committed archive refs: **46**, all verified by remote ref and SHA.
- Sanitised snapshot refs: **7**, all verified after scanning the published trees for the removed machine-specific strings.
- WIP snapshot refs: **6**, all verified by remote ref and SHA.
- Primary platform branches: **3**, each verified against GitHub.
- Protected `main`: `dec2393c980bf63b1138f70461df9aafa66baa88` locally and remotely.
