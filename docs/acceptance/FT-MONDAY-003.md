# FT-MONDAY-003 — AI on live broker reads

Product tip for GitHub issue [#254](https://github.com/navaneeshnagarajan/FlintTrade/issues/254)
on tracking PR #256. AI Chat may use Practice SandboxEngine fills and
native Dhan/Neo Connected (read) feeds when an LLM is configured.
Suggest stays labelled illustrative. Live place stays fail-closed.

## Finding

Wire AI to Practice + native live-read feeds for analysis (not
“guaranteed profitable alphas”).

## Locked (2026-09-20)

- **Chat live-reads** — when an LLM is configured, AI Chat may use
  Practice SandboxEngine fills and native live-read feeds for analysis
- **Suggest stays labelled illustrative** — local filter UI; not the
  Chat live-read path; never sold as live alpha
- **Never green Connected without a real LLM** — same honesty bar as
  FT-AI-002 / FT-AI-004
- **Not a “profitable alphas” ship criterion** — analysis context only;
  measure later
- AI may consume Dhan/Neo Connected (read) / Practice SandboxEngine
  data for context — not place Live orders
- This does **not** lift the native broker HTTP freeze and does not
  invent Neo Practice

## Acceptance

1. With LLM configured: Chat can read Practice + native read feeds for
   answers (no fake Connected).
2. Without LLM: Not configured / Not installed honesty; composer gated.
3. Suggest remains illustrative labelling.
4. No Live place from AI path.
5. Tests covering honesty + read-context wiring + fail-closed place.
6. Changelog Unreleased FT-MONDAY-003.
7. British English.

## Out of scope

- Native HTTP cutover (Task 9D / Task 7C.2) — freeze stays.
- Funded Live order placement.
- Inventing Neo Practice.
- Forge overnight harness.
- Profitable-alpha measurement.
