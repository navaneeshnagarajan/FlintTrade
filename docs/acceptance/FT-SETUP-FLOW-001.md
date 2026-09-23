# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

Tracking only. This pull request does not change the wizard, routes, mode
selection, or broker behaviour.

First-run Setup still counts optional work as required steps and still
offers Live unlock before the operator reaches a desk. The locked path is
shorter: create the operator, open the vault, land on the Practice desk.

## Locked behaviour

1. The mandatory first-run path is only **Create operator → vault →
   Practice desk**. Nothing else blocks that path.
2. **TOTP**, **broker connect**, **LLM**, and **Monitoring** are
   Later/Skip on first run. They are not required gates. Choosing Later
   or Skip continues the mandatory path.
3. First run does not unlock **Live**. The Practice desk is the finish.
   A later Live unlock, outside this path, keeps the existing
   authenticator and PIN gate. Live place stays fail-closed.
4. **Step N of M** labels cover required steps only. Later/Skip steps do
   not increment N or M.
5. Weekday and pack names in operator copy are a separate finding,
   **FT-SETUP-COPY-001** ([#281](https://github.com/navaneeshnagarajan/FlintTrade/pull/281)).
   This finding does not edit those strings.

Persona, trading defaults, and risk limits are not on the mandatory path.
The follow-up must not leave them as required first-run gates, and must
not add them to the Step N of M count.

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

The shell subtitle is `Step N of 7`, including Two-Factor Auth and Broker
Connection. Two-Factor Auth already has Set up later, and Broker
Connection can continue without a broker, but both still count.

Choose Mode still offers Explore, Practice, and Live. Selecting Live can
finish setup through the PIN and authenticator unlock. Practice selection
mints a Practice session and then leaves setup for sign-in, rather than
opening the Practice desk as the mandatory finish.

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
2. TOTP, broker connect, LLM, and Monitoring are offered as Later/Skip.
   Skipping any of them still reaches the Practice desk.
3. First run has no Live unlock control and cannot mint a Live session.
4. Step N of M counts only Create operator, vault, and Practice desk.
   Later/Skip controls are absent from that fraction.
5. Persona, trading defaults, and risk limits are not required gates and
   are not part of M.
6. British English. No personal details, hostnames, account names, or
   fund amounts in the change.
7. FT-SETUP-COPY-001 copy is untouched.

## Status

Open. The first-run wizard is unchanged.
