# FT-SETUP-FLOW-001 — Simplify first-run Setup to the Practice desk

The mandatory first-run path creates the operator, affirms Practice, and
lands on the Practice desk. The vault step is included when the vault is
not yet secured, and skipped when the backend has already secured it.
Later steps come after the affirm.

## Locked behaviour

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

## Out of scope

- Operator-copy scrub for weekday or pack names (**FT-SETUP-COPY-001** /
  #281).
- Which brokers can connect, the native broker HTTP freeze, and funded
  Live place. Those stay on their existing acceptance tips.
- Renaming modules, tests, or internal identifiers.

## Acceptance

## Status

Implemented. When the vault is already secured, required progress is
**Step 1 of 2 - Create operator**, then **Step 2 of 2 - Practice desk**,
and the Practice step shows **Your vault is set up and
secured on this machine.** above **Open Practice desk**. When the vault
is not yet secured, required progress is **Step 1 of 3 - Create
operator**, **Step 2 of 3 - Vault**, and **Step 3 of 3 - Practice
desk**. The Practice desk is Step 2 or 3. With no operator yet, Setup
starts at Create operator. When an operator already exists and Setup is
unfinished, `/setup` resumes at Step 2 or 3. Reloading `/setup` resumes the unfinished setup and keeps
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
affirm lands on the Practice desk before the optional strip. The
strip reads `Optional setup · N of 4 done`, and adds `· M skipped` only
when at least one card is skipped. Monitoring and risk limits stay in
Settings. The strip does not gate the desk, and first run does not
unlock Live.
