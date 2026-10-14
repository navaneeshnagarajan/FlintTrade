# Bounded live capture (private candidate)

The package/protocol version remains 3.6.0. This source delta adds opt-in retention and paginated live-buffer export; it does not certify a whole browser session, reconstruct SDK losses, or change ordinary observe budgets.

## Daemon configuration

`start` and `startDaemon` accept `captureRetention: {maxEvents, maxAgeMs, maxBytes}`. The CLI reads the same complete JSON object from `RETICLE_CAPTURE_RETENTION` **before startup**. The owned daemon applies the frozen budget to each new session. Omission preserves 2,000 events, 60,000 ms and 8 MiB. Every supplied field must be a positive safe integer. Unknown, missing, nonnumeric or excessive fields refuse startup.

The explicit ceilings are 100,000 events, 600,000 ms and 64 MiB. They do not replace the existing session-count, transport-rate, message-size, redaction, origin or authentication limits. The existing bounded armed-wait allowance and single oversized-event retention behavior are unchanged. Full-capture export refuses a sole event exceeding the configured byte budget rather than calling that window complete.

Use an owned daemon and explicit budget only for the capture needing it. Do not increase an application's accepted request counts or shorten its assertion window.

## Export protocol

Call the existing `reticle_observe` with `since: 0`, `max_events` (at most 2,000), and `export_page: {}`. No filters, `until`, action filter or alternate window may be combined with export. Each page returns the ordinary events/summary/cost envelope plus:

- `capture.id`, `source: "live"`, `since`, `until`, `total` and `offset`;
- `count`, `event_bytes`, frozen retention budget and `dropped`;
- `next_cursor` if another page remains; `complete` only on the terminal page.

Repeat the **same request** with `export_page.cursor` set to `next_cursor`. The default JSON event-array byte budget is 262,144; `max_bytes` may explicitly select 256–1,048,576. An event that cannot fit is refused, never trimmed. The envelope itself has additional bounded metadata overhead.

The cursor authenticates an immutable live prefix, expires after 120 seconds and is tied to the session instance, document and page budgets. Appends do not extend that prefix. Eviction, idle age expiry, replacement/disconnection, end/revival, document round trips, tampering or mismatched budgets refuse continuation. No snapshot journal or per-export event copies are retained between requests. Restarting an export is not permission to discard an earlier failed capture.

A terminal page alone is not a complete witness. Collect every offset from zero through total, preserve each exact page, and compare the complete unfiltered sequence with an independent producer witness. Keep output truncation, hot-buffer eviction, journal recovery and SDK observation/transport loss separate. Require both `verified: "yes"` and `pass: true`, plus a valid full capture. Default `observe` remains a bounded recent-events view.

## Known qualification boundary

The original whole-application replay remains rejected. The upstream SDK emits DOM truncation markers, the daemon intentionally omits `hud.used` from its evidence stream, and normal capability reannouncement sends a second HELLO on one socket. None is fixed or hidden by larger daemon retention. The strict application witness also rejects a producer event arriving after a frozen export prefix. Resolving these contracts requires a separate decision; do not filter events, suppress emissions, alter the presenter, relax the witness or report whole-app acceptance from this delta.

## Local regression

After the normal public package build, run `node --test server/test/full-window.test.mjs` from the repository root. Tests use owned loopback WebSockets, temporary state and no browser or account. Run with external egress denied, `RETICLE_CONNECT=0` and `RETICLE_TELEMETRY=0`. The separate exact-count honesty change retains the native predicate pass bit but refuses proof after loss; a genuinely proved independent `anyOf` branch remains valid.

Server source remains FSL-1.1-ALv2. Engine/core licenses remain unchanged. No contributor identity, DCO certification or permission to publish is supplied by this document.
