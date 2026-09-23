# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

The mandatory first-run path is create the operator, open the vault, affirm
Practice, and land on the Practice desk. Later steps come after that.

## Locked behaviour

1. The mandatory first-run path is only **Create operator → vault →
   Practice desk**. Nothing else blocks that path.
2. After the vault, the operator affirms Practice and lands on the
   Practice desk. That affirm happens **before** Trading Defaults, Risk,
   and Broker.
3. **Trading Defaults**, **Risk**, and **Broker** stay Later/Skip. They
   must never appear ahead of the Practice affirm.
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

Persona is not on the mandatory path. It is not a required first-run
gate, and it is not part of the Step N of M count.

## First-run path

The mounted wizard is `/setup` (`CanonicalSetupRoute` →
`SetupAccountRoute`). Required steps, and the only Step N of M labels:

1. Create operator
2. Vault
3. Practice desk

The Practice step is the affirm only. It offers **Open Practice desk**
and does not render TOTP, broker connect, LLM, Monitoring, Trading
Defaults, or Risk. Opening the desk mints a Practice session and leaves
setup for `/trade`.

Those later panels open on the Practice desk after landing. Skip or
Later stays on the desk and does not change Step N of 3. On broker
connect, **Continue without a broker** is the first control, above
FlintTrade Native and OpenAlgo Bridge. There is no Live unlock control
on this path.

## Out of scope

- Operator-copy scrub for weekday or pack names (**FT-SETUP-COPY-001** /
  #281).
- Which brokers can connect, the native broker HTTP freeze, and funded
  Live place. Those stay on their existing acceptance tips.
- Renaming modules, tests, or internal identifiers.

## Acceptance

1. A new operator can finish first-run Setup only by creating the
   operator, opening the vault, and landing on the Practice desk.
2. Immediately after the vault, the operator affirms Practice and lands
   on the Practice desk. Trading Defaults, Risk, and Broker are not on
   screen yet.
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

Implemented. Required progress is Step N of 3. The affirm lands on the
Practice desk before later setup. Optional panels do not gate that desk,
and first run does not unlock Live.
