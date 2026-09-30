# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

The mandatory first-run path creates the operator, affirms Practice, and
lands on the Practice desk. The vault step is included when the vault is
not yet secured, and skipped when the backend has already secured it.
Later steps come after the affirm.

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

1. The mandatory first-run path ends on the Practice desk. When the
   vault is not yet secured, that path is **Create operator → vault →
   Practice desk**. When the vault is already secured, Setup skips the
   vault step. Nothing else blocks the path.
2. The operator affirms Practice and lands on the Practice desk. That
   affirm happens **before** Trading Defaults, Risk, and Broker. When
   the vault step is shown, the affirm comes after it.
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
   not increment N or M. M is 2 when the vault is already secured, and
   3 when the vault step is required. The separator in the title is
   ` - `.
8. Weekday and pack names in operator copy are a separate finding,
   **FT-SETUP-COPY-001** ([#281](https://github.com/navaneeshnagarajan/FlintTrade/pull/281)).
   This finding does not edit those strings.

Persona is not on the mandatory path. It is not a required first-run
gate, and it is not part of the Step N of M count.

## First-run path

The mounted wizard is `/setup` (`CanonicalSetupRoute` →
`SetupAccountRoute`). Required steps:

1. Create operator
2. Vault — only when this machine's vault is not yet secured
3. Practice desk

When the vault is already secured, the total is fixed before step 1.
The titles are **Step 1 of 2 - Create operator** and **Step 2 of 2 -
Practice desk**. That path never shows "of 3". On that Practice step
only, **Your vault is set up and secured on this machine.** appears
above **Open Practice desk**.

When the vault is not yet secured, the titles are **Step 1 of 3 -
Create operator**, **Step 2 of 3 - Vault**, and **Step 3 of 3 -
Practice desk**. The vault step asks for a master password and **Open
vault**.

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

A failed setup-status check stays on that failure, with **Retry**, and
does not open the fresh-install form.

- HTTP 429: **FlintTrade is busy**. **FlintTrade is busy right now. Wait
  a moment, then retry.**
- Any other HTTP error, or a response that cannot be read or is
  incomplete: **Can't check setup status**. **FlintTrade answered, but
  setup status couldn't be read. Retry in a moment.**
- Only when nothing answered: **FlintTrade backend unavailable**, with
  **Retry**. Before Setup fields mount, the detail is **Start or
  restart the local FlintTrade backend, then retry. Setup has not
  advanced and no account, broker, or credential details were submitted
  from this screen.** **Return to welcome** sits beside **Retry**. On
  the later status read the detail is **The FlintTrade backend did not
  answer. Start or restart the local FlintTrade backend, then retry.**
  and the only button is **Retry**.

Reloading `/setup` mid-flow resumes the unfinished setup and keeps the
same step title. A run whose vault was not secured at the start still
shows **Step 3 of 3 - Practice desk** after the vault opens and after a
reload. The same browser tab restores the setup session and continues
the current step. A fresh browser, or a reload on the vault step that
needs a setup session, shows **Continue setup** and **This machine
already has an operator. Sign in to finish setup.** Enter the
password and choose **Continue setup** to carry on. That screen does
not open the create-operator form. **Start over (deletes this
unfinished operator)** asks once: **Enter your password to delete this
unfinished operator.** The red **Delete and start over** button
confirms it and restarts at step 1. **Cancel** dismisses that
confirmation. That is the start-over control on the vault step. A
workspace data wipe is not required.

After Setup completes, opening `/setup` does not restart step 1. A
signed-in operator is sent to `/trade`. A signed-out operator sees
**Setup is complete. Sign in to open the desk.** **Sign in** is the
primary button and opens `/welcome`.

Those later panels open on the Practice desk after landing. Skip or
Later stays on the desk and does not change the step total fixed
above. On the broker card, **Continue without a broker** is the primary
control. Native, OpenAlgo, and MCP stay behind Set up, and inside that
panel the same control remains above them. There is no Live unlock
control on this path.


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

1. A new operator finishes first-run Setup by creating the operator and
   landing on the Practice desk. The vault step is required only when
   the vault is not yet secured.
2. The operator affirms Practice and lands on the Practice desk before
   Trading Defaults, Risk, and Broker appear. When the vault step is
   shown, that affirm comes immediately after it.
3. Trading Defaults, Risk, and Broker are Later/Skip, and none of them
   can appear ahead of that affirm.
4. **Continue without a broker** is the primary control on the broker
   Later path. Native, OpenAlgo, and MCP do not sit above it or hide it.
5. TOTP, broker connect, LLM, and Monitoring are Later/Skip. Skipping
   any of them still leaves the operator on the Practice desk.

6. First run has no Live unlock control and cannot mint a Live session.
7. Step N of M counts only the required steps. When the vault is already
   secured, M is 2 (**Step 1 of 2 - Create operator**, **Step 2 of 2 -
   Practice desk**) and the path never shows "of 3". When the vault is
   not yet secured, M is 3 and includes **Step 2 of 3 - Vault**.
   Later/Skip controls are absent from that fraction.
8. Persona is not a required gate and is not part of M.
9. British English. No personal details, hostnames, account names, or
   fund amounts in the change.
10. FT-SETUP-COPY-001 copy is untouched.

## Status

Implemented. When the vault is already secured, required progress is
Step N of 2 and the Practice step shows **Your vault is set up and
secured on this machine.** above **Open Practice desk**. When the vault
is not yet secured, required progress is Step N of 3 and includes the
vault step. Reloading `/setup` resumes the unfinished setup and keeps
the same step title (for example **Step 3 of 3 - Practice desk**). A
fresh browser, or a reload on the vault step that needs a setup
session, shows **Continue setup** and **This machine already has an
operator. Sign in to finish setup.** A failed status check stays on
**Retry** and does not open the fresh-install form: **FlintTrade is
busy** on HTTP 429, **Can't check setup status** for any other HTTP
error or an unreadable or incomplete response, and **FlintTrade backend
unavailable** only when nothing answered. **Start over (deletes this
unfinished operator)** asks once for the password (**Enter your password
to delete this unfinished operator.**) and the red **Delete and start
over** button restarts at step 1. After Setup completes, a signed-in
operator opening `/setup` is sent to `/trade`, and a signed-out
operator sees **Setup is complete. Sign in to open the desk.** The
affirm lands on the Practice desk before later setup. Optional panels
do not gate that desk, and first run does not unlock Live.
