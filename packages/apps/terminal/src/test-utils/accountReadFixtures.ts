import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";

/** Labelled Explore feed; account-backed queries must remain disabled. */
export const EXPLORE_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "explore",
    scopeKey: "explore:mock",
    brokerType: "mock",
    accountId: "default",
  }),
  enabled: false,
}) satisfies AccountReadContext;

/** Connected native account authority used by account-query unit fixtures. */
export const CONNECTED_NATIVE_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:native:dhan:A1",
    brokerType: "dhan",
    accountId: "A1",
  }),
  enabled: true,
}) satisfies AccountReadContext;

/** Fail-closed Live authority before a broker/account source is selected. */
export const UNCONFIGURED_LIVE_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:unconfigured",
    brokerType: "unconfigured",
    accountId: "none",
  }),
  enabled: false,
}) satisfies AccountReadContext;

/** Local Practice sandbox authority, independent of a Live broker session. */
export const PRACTICE_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "practice",
    scopeKey: "practice:sandbox:default",
    brokerType: "sandbox",
    accountId: "default",
  }),
  enabled: true,
}) satisfies AccountReadContext;
