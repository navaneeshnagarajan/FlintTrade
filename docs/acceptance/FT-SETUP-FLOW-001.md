# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

The mandatory first-run path is create the operator, open the vault, affirm
Practice, and land on the Practice desk. Later steps come after that.

## Locked behaviour

1. The mandatory first-run path is only **Create operator → vault →
   Practice desk**. Nothing else blocks that path.
2. After the vault, the operator affirms Practice and lands on the
   Practice desk. That affirm happens **before** the optional cards.
3. The optional cards are **Two-factor authentication**,
   **Broker connect**, **LLM**, and **Trading defaults**. Risk limits
   and Monitoring stay in Settings. None of these appear ahead of the
   Practice affirm.
4. **Continue without a broker** is the first control on the open
   broker panel. It sits above **FlintTrade Native** and
   **OpenAlgo Bridge**.
5. Those four cards are optional. They are not required gates.
   **Later** on a card row marks that card **Skipped** and does not
   block the Practice desk. **Later** inside an open authenticator,
   **LLM**, or trading-defaults panel only closes the panel. It does
   not mark the card **Skipped** or **Done**, and the strip does not
   change. A skipped card shows **Skipped** and only **Set up**. A
   finished card shows **Done** and only **Set up** (no **Later**).
   A finished **Broker connect** card does not show
   **Continue without a broker**. That control is on the card only
   while the card is neither done nor skipped. Card-row **Later**
   buttons, and **Later** in the open **LLM** and trading-defaults
   panels, are announced as `Later {title}`. The strip reads
   `Optional setup · N of 4 done`, and adds `· M skipped` only when M
   is at least 1. N counts finished cards only. **Dismiss** on the desk
   moves the strip into Settings. The Settings reminder has **Show**
   and **Hide**, and no **Dismiss**.
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
and does not render the optional cards, Monitoring, or Risk. Opening
the desk mints a Practice session and leaves setup for `/trade`.

The optional strip opens on the Practice desk after landing. **Later**
on a card row marks the card **Skipped** and does not change Step N of
3. **Later** inside an open authenticator, **LLM**, or trading-defaults
panel only closes the panel and leaves the card and the strip
unchanged. Card titles are plain: **Two-factor authentication**,
**Broker connect**, **LLM**, and **Trading defaults**. A finished
**Broker connect** card shows **Done** and **Set up** only. On the open
broker panel, **Continue without a broker** is the first control, above
**FlintTrade Native** and **OpenAlgo Bridge**, and choosing it marks
the card **Skipped**, the same as on the card. A successful native or
OpenAlgo connection still marks the card **Done**. There is no Live
unlock control on this path.

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
   on the Practice desk. The optional cards are not on screen yet.
3. **Two-factor authentication**, **Broker connect**, **LLM**, and
   **Trading defaults** come after that affirm. Risk limits and
   Monitoring stay in Settings. None of them can appear ahead of the
   affirm.
4. **Continue without a broker** is the first control on the open
   broker panel. **FlintTrade Native** and **OpenAlgo Bridge** do not
   sit above it.
5. Skipping any of the four optional cards still leaves the operator
   on the Practice desk. **Later** on the card row marks the card
   **Skipped** and updates the strip. **Later** inside an open
   authenticator, **LLM**, or trading-defaults panel only closes the
   panel and leaves the card and the strip unchanged. **Continue without
   a broker** on the open broker panel marks **Broker connect**
   **Skipped** and updates the strip. A finished
   **Broker connect** card shows **Done** and **Set up** only. The
   strip counts finished cards only, and omits `· M skipped` when
   nothing is skipped. Settings keeps the reminder after **Dismiss**,
   without a **Dismiss** of its own.
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
