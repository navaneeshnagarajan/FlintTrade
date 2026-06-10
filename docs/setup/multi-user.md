# Multi-User Mode — removed (out of scope)

FlintTrade is a **personal-use, single-operator** trading workstation: the
operator is the user is the data principal. The multi-user CRUD scaffold
(`/api/v1/users/*`, an `admin`/`trader`/`viewer` account manager) was **removed
on 2026-06-10 as overscope** — it added a hosted-SaaS surface this project
deliberately does not have, and it was opt-in code that nothing enabled.

If multi-user / multi-tenant support is ever needed, it should be **redesigned
around the gated-principal model** (the selector-bound `RequestContext` +
broker `account_acls` that already authorise every order) rather than restored
as a parallel user table — full per-user workspace, secret, and broker-credential
isolation, plus audit review and operational runbooks, would be prerequisites
before any live-broker multi-user deployment.

The removed code is archived (in-repo history) at
`.local/archive/user-multi-2026-06-10/` for reference.
