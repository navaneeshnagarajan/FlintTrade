# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

Tracking only. This pull request does not change the wizard, routes, mode
selection, or broker behaviour.

First-run Setup still counts optional work as required steps, still places
Trading Defaults, Risk, and Broker ahead of mode, and still offers Live
unlock before the operator reaches a desk. The locked path is shorter:
create the operator, open the vault, affirm Practice, and land on the
Practice desk. Later steps come after that.

## Locked behaviour

1. The mandatory first-run path is only **Create operator → vault →
   Practice desk**. Nothing else blocks that path.
2. After the vault, the operator affirms Practice and lands on the
   Practice desk, or sees one Mode step that defaults to Practice. That
   affirm happens **before** Trading Defaults, Risk, and Broker.
3. **Trading Defaults**, **Risk**, and **Broker** stay Later/Skip. They
   must never appear ahead of the Mode or Practice affirm.
4. **Continue without a broker** is a primary Later path. It is not
   buried under Native, OpenAlgo, or MCP.
5. **TOTP**, **broker connect**, **LLM**, and **Monitoring** are
   Later/Skip on first run. They are not required gates. Choosing Later
   or Skip does not block the Practice desk.
6. First run does not unlock **Live**. The Practice desk is the finish.
   A later Live unlock, outside this path, keeps the existing
   authenticator and PIN gate. Live place stays fail-closed.
7. **Step N of M** labels cover required steps only. Later/Skip steps do
   not increment N or M.
8. Weekday and pack names in operator copy are a separate finding,
   **FT-SETUP-COPY-001** ([#281](https://github.com/navaneeshnagarajan/FlintTrade/pull/281)).
   This finding does not edit those strings.

Persona is not on the mandatory path. The follow-up must not leave it as
a required first-run gate, and must not add it to the Step N of M count.

## Current first-run path

Checked on the tree this note was added to. The mounted wizard is
`/setup` (`CanonicalSetupRoute` → `SetupAccountRoute`). The legacy
preferences wizard is not the first-run authority.

`SetupAccountRoute` labels seven steps and uses that seven as M:

1. Account Security
2. Two-Factor Auth
3. Persona
4. Broker Connection
5. Trading Defaults
6. Risk Limits
7. Choose Mode

The shell subtitle is `Step N of 7`, including Two-Factor Auth, Broker
Connection, Trading Defaults, and Risk Limits. Two-Factor Auth already
has Set up later, and Broker Connection can continue without a broker,
but both still count. Trading Defaults and Risk Limits are required
steps. All three of Broker Connection, Trading Defaults, and Risk Limits
sit ahead of Choose Mode.

Choose Mode still offers Explore, Practice, and Live. Selecting Live can
finish setup through the PIN and authenticator unlock. Practice selection
mints a Practice session and then leaves setup for sign-in, rather than
opening the Practice desk before the later steps.

On the broker step, **Continue without a broker** is the first button,
above the FlintTrade Native and OpenAlgo Bridge tabs. Broker MCP
assistants render inside the Native panel. That skip is not yet a Later
path after a Practice affirm, because the whole broker step precedes
Choose Mode.

LLM configuration sits on the unmounted legacy wizard, not as a
Later/Skip control on `/setup`. Monitoring is a Settings section, not a
first-run Later/Skip control. The vault is not a required step between
operator creation and the desk.

## Out of scope

- Any wizard, route, or mode change in this pull request.
- Operator-copy scrub for weekday or pack names (**FT-SETUP-COPY-001** /
  #281).
- Which brokers can connect, the native broker HTTP freeze, and funded
  Live place. Those stay on their existing acceptance tips.
- Renaming modules, tests, or internal identifiers.

## Acceptance (follow-up implementation)

This pull request is done when the tracking note exists. The product
fix, in a later change, is done when all of the following hold:

1. A new operator can finish first-run Setup only by creating the
   operator, opening the vault, and landing on the Practice desk.
2. Immediately after the vault, the operator affirms Practice and lands
   on the Practice desk, or completes one Mode step that defaults to
   Practice. Trading Defaults, Risk, and Broker are not on screen yet.
3. Trading Defaults, Risk, and Broker are Later/Skip, and none of them
   can appear ahead of that affirm.
4. **Continue without a broker** is the primary control on the broker
   Later path. Native, OpenAlgo, and MCP do not sit above it or hide it.
5. TOTP, broker connect, LLM, and Monitoring are Later/Skip. Skipping
   any of them still leaves the operator on the Practice desk.
6. First run has no Live unlock control and cannot mint a Live session.
7. Step N of M counts only Create operator, vault, and Practice desk.
   Later/Skip controls are absent from that fraction.
8. Persona is not a required gate and is not part of M.
9. British English. No personal details, hostnames, account names, or
   fund amounts in the change.
10. FT-SETUP-COPY-001 copy is untouched.

## Status

Open. The first-run wizard is unchanged. Ordering clarification recorded.
