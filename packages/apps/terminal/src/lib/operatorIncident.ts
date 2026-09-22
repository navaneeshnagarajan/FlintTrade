/**
 * Operator incident model (issue #270).
 *
 * One classifier drives the sticky strip under TopBar, broker Connected
 * honesty, and Live place/mirror muting. It reads signals we already have
 * (health, ping, broker rejects, account status, Dhan WS, advisor chrome,
 * the Task 9D freeze 503). It does not invent an exchange halt from the
 * session clock, and it does not invent a Kotak Neo stream class.
 *
 * Detectably wired:
 * - exchange — broker reject text (circuit / halt). Not the session clock.
 * - edge — public site / CDN fetch failed while local ping is ok. Info only.
 * - broker_auth / broker_rest / broker_stream / broker_rate_limit /
 *   broker_maintenance — account status, reject text, HTTP status, Dhan WS.
 * - host_unhealthy — `/health` overall status, or an HTTP error from our process.
 * - backend_unreachable — same-origin transport while the public site is up
 *   or still unknown, or the Task 9D native HTTP freeze 503.
 * - network_local — DNS, timeout, or transport while the public site is
 *   also unreachable (ISP / local uplink).
 * - llm_provider — advisor chrome error or disconnected. Not a Live-write gate.
 *
 * Strip priority inside this classifier: host tier (network_local,
 * host_unhealthy, backend_unreachable) then broker trust (exchange and
 * broker_*) then edge then llm_provider. Live risk and the feed sit in
 * `selectPrimaryBanner`. A hidden broker-trust fault under a host banner
 * still closes Live writes.
 *
 * Honest unknown / not invented:
 * - exchange while the only signal is the session clock or CAS
 * - Neo broker_stream until SFeed
 * - ISP while the public-site probe is still unknown (backend_unreachable)
 * - edge while the public-site probe has not returned
 */

export const FAILURE_CLASSES = [
  "exchange",
  "edge",
  "broker_auth",
  "broker_rest",
  "broker_stream",
  "broker_rate_limit",
  "broker_maintenance",
  "llm_provider",
  "host_unhealthy",
  "backend_unreachable",
  "network_local",
] as const;

export type FailureClass = (typeof FAILURE_CLASSES)[number];

export type OperatorStripLevel = "info" | "degraded" | "blocked";

export type TransportReason = "dns" | "timeout" | "connection_refused" | "failed_fetch";

export interface BrokerRejectSignal {
  message: string;
  httpStatus: number | null;
  broker: string | null;
}

export interface ActiveAccountSignal {
  broker: string;
  status: string;
  errorMessage: string | null;
  readSmokeOk: boolean;
  needsRelogin: boolean;
}

export interface OperatorSignals {
  feedDisconnected: boolean;
  localPing: "unknown" | "ok" | "transport" | "http_error";
  transportReason: TransportReason | null;
  health: "unknown" | "healthy" | "degraded" | "unhealthy";
  publicSite: "unknown" | "ok" | "unreachable";
  nativeHttpFreeze: boolean;
  brokerRateLimited: boolean;
  brokerReject: BrokerRejectSignal | null;
  activeAccount: ActiveAccountSignal | null;
  wsFailure: { kind: "auth" | "network"; reason: string } | null;
  llmChrome: string | null;
  /** Present so a closed or CAS session chip cannot become an exchange incident. */
  sessionClockClosed: boolean;
  observedHostDown?: boolean;
  observedBackendUnreachable?: boolean;
}

export interface OperatorIncident {
  failureClass: FailureClass;
  level: OperatorStripLevel;
  /** Darken Connected and mute Live place/mirror. */
  moneyPath: boolean;
  nativeHttpFreeze: boolean;
  /** Stop the broker-account poll until the operator retries once. */
  muteBrokerSmoke: boolean;
  plainClass: string;
  headline: string;
  rectify: string;
}

export type ObservedFailure =
  | { kind: "freeze" }
  | { kind: "rate_limit"; message: string; httpStatus: number | null }
  | { kind: "reject"; failureClass: FailureClass; message: string; httpStatus: number | null };

const PLAIN_CLASS: Record<FailureClass, string> = {
  exchange: "exchange/session",
  edge: "public site / CDN",
  broker_auth: "broker sign-in",
  broker_rest: "broker connection",
  broker_stream: "broker stream",
  broker_rate_limit: "broker rate limit",
  broker_maintenance: "broker maintenance",
  llm_provider: "chat provider",
  host_unhealthy: "host unhealthy",
  backend_unreachable: "backend unreachable",
  network_local: "local network",
};

const RECTIFY: Record<FailureClass, string> = {
  exchange:
    "Wait for the session and check the exchange status page. Manage open risk in your broker app. FlintTrade cannot reverse a reject or file a dispute.",
  edge:
    "The public site / CDN is unreachable. This desk is local — a site outage does not cancel broker orders. Install from the repository if you need the desk. FlintTrade does not hold funds.",
  broker_auth:
    "Sign in again under Settings → Brokers. FlintTrade will not place a Live order until sign-in succeeds.",
  broker_rest:
    "The broker API did not answer. Check the broker status page, then retry once. FlintTrade cannot reclaim funds.",
  broker_stream:
    "The market stream is down, so quotes may be stale. Wait for it to reconnect. Live orders stay closed until then.",
  broker_rate_limit:
    "Wait for the broker rate-limit window to clear, then retry once. FlintTrade will not re-smoke on its own.",
  broker_maintenance:
    "The broker reports maintenance. Wait, then check the broker status page. Live orders stay closed. FlintTrade cannot file a dispute.",
  llm_provider:
    "Chat is unavailable. Retest or switch provider under Settings. Trading does not use Chat to place orders.",
  host_unhealthy:
    "Free disk space and restart the desk, then read the desk health detail. Live orders stay closed until the desk and broker trust are back. A restart does not recover broker fills. FlintTrade does not hold funds.",
  backend_unreachable:
    "Restart the desk and read the desk health detail before any Live order. A restart does not recover broker fills. FlintTrade does not hold funds.",
  network_local:
    "The local network or ISP link failed before any broker response. Check the link or switch network, then retry health. Live orders stay closed.",
};

const FREEZE_RECTIFY =
  "Native broker account changes stay frozen until the HTTP cutover. This is not a broker outage, and FlintTrade does not hold funds.";

const HOST_UNKNOWN_UPLINK_RECTIFY =
  "The desk did not answer, and the uplink check has not finished. Treat Live orders as closed until health recovers. FlintTrade does not hold funds.";

export function liveWritesMuted(incident: OperatorIncident | null): boolean {
  return incident !== null && incident.moneyPath && incident.level !== "info";
}

export function honestBrokerStatus(input: {
  connected: boolean;
  connectedRead: boolean;
  nativeMonday: boolean;
  incident: OperatorIncident | null;
}): string | null {
  const incident = input.incident;
  if (incident?.nativeHttpFreeze && input.nativeMonday) {
    return "Unavailable — backend unreachable";
  }
  if (
    incident
    && incident.moneyPath
    && incident.level !== "info"
    && (input.connected || input.connectedRead)
  ) {
    const word = incident.level === "blocked" ? "Unavailable" : "Degraded";
    return `${word} — ${incident.plainClass}`;
  }
  if (input.connectedRead) return "Connected (read)";
  if (input.connected) return "Connected";
  return null;
}

export function classifyObservedFailure(input: {
  message: string;
  httpStatus: number | null;
}): ObservedFailure | null {
  const failureClass = classFromText(input.message, input.httpStatus);
  if (failureClass === "freeze") return { kind: "freeze" };
  if (failureClass === "broker_rate_limit") {
    return { kind: "rate_limit", message: input.message, httpStatus: input.httpStatus };
  }
  if (
    failureClass === "exchange"
    || failureClass === "broker_auth"
    || failureClass === "broker_rest"
    || failureClass === "broker_maintenance"
    || failureClass === "host_unhealthy"
    || failureClass === "backend_unreachable"
  ) {
    return {
      kind: "reject",
      failureClass,
      message: input.message,
      httpStatus: input.httpStatus,
    };
  }
  return null;
}

const HOST_TIER: ReadonlySet<FailureClass> = new Set([
  "network_local",
  "host_unhealthy",
  "backend_unreachable",
]);

function brokerTrustLatched(signals: OperatorSignals): boolean {
  if (signals.brokerRateLimited) return true;
  const rejectClass = signals.brokerReject
    ? classFromText(signals.brokerReject.message, signals.brokerReject.httpStatus)
    : null;
  if (isBrokerTrustClass(rejectClass)) return true;
  if (isBrokerTrustClass(accountFailure(signals.activeAccount))) return true;
  const broker = signals.activeAccount?.broker ?? "";
  return signals.localPing === "ok" && broker === "dhan" && signals.wsFailure?.kind === "network";
}

function isBrokerTrustClass(value: FailureClass | "freeze" | null): boolean {
  return value === "exchange"
    || value === "broker_auth"
    || value === "broker_rest"
    || value === "broker_stream"
    || value === "broker_rate_limit"
    || value === "broker_maintenance";
}

export function classifyOperatorSignals(signals: OperatorSignals): OperatorIncident | null {
  const incident = pickIncident(signals);
  if (!incident) return null;
  if (signals.brokerRateLimited) incident.muteBrokerSmoke = true;
  if (HOST_TIER.has(incident.failureClass) && brokerTrustLatched(signals)) {
    incident.moneyPath = true;
  }
  return incident;
}

function pickIncident(signals: OperatorSignals): OperatorIncident | null {
  const transport = transportIncident(signals);
  if (transport) return transport;

  if (signals.health === "unhealthy" || signals.observedHostDown || signals.localPing === "http_error") {
    return makeIncident("host_unhealthy", "blocked", true, false, "Host unhealthy — the desk health check failed");
  }
  if (signals.health === "degraded") {
    return makeIncident("host_unhealthy", "degraded", true, false, "Host unhealthy — the desk health check is degraded");
  }

  if (signals.nativeHttpFreeze) {
    return {
      ...makeIncident(
        "backend_unreachable",
        "degraded",
        false,
        true,
        "Backend unreachable — native broker HTTP is frozen",
      ),
      rectify: FREEZE_RECTIFY,
    };
  }
  if (signals.observedBackendUnreachable) {
    return makeIncident(
      "backend_unreachable",
      "blocked",
      true,
      false,
      "Backend unreachable — the FlintTrade backend is unreachable",
    );
  }

  const rejectClass = signals.brokerReject
    ? classFromText(signals.brokerReject.message, signals.brokerReject.httpStatus)
    : null;
  if (rejectClass === "exchange") {
    return makeIncident("exchange", "blocked", true, false, "Exchange/session — the exchange rejected the order");
  }

  if (signals.brokerRateLimited || rejectClass === "broker_rate_limit") {
    return makeIncident(
      "broker_rate_limit",
      "degraded",
      true,
      false,
      "Broker rate limit — the broker rate limit is in effect",
    );
  }

  const accountClass = accountFailure(signals.activeAccount);
  if (signals.wsFailure?.kind === "auth" || accountClass === "broker_auth" || rejectClass === "broker_auth") {
    return makeIncident("broker_auth", "blocked", true, false, "Broker sign-in — broker sign-in failed");
  }
  if (accountClass === "broker_maintenance" || rejectClass === "broker_maintenance") {
    return makeIncident(
      "broker_maintenance",
      "blocked",
      true,
      false,
      "Broker maintenance — the broker is in maintenance",
    );
  }
  if (accountClass === "broker_rest" || rejectClass === "broker_rest") {
    return makeIncident(
      "broker_rest",
      "degraded",
      true,
      false,
      "Broker connection — the broker connection failed",
    );
  }

  const broker = signals.activeAccount?.broker ?? "";
  if (
    signals.localPing === "ok"
    && broker === "dhan"
    && signals.wsFailure?.kind === "network"
  ) {
    return makeIncident("broker_stream", "degraded", true, false, "Broker stream — the broker stream is down");
  }

  if (signals.publicSite === "unreachable" && signals.localPing === "ok") {
    return makeIncident(
      "edge",
      "info",
      false,
      false,
      "Public site / CDN — the public site / CDN is unreachable",
    );
  }

  if (signals.llmChrome === "error" || signals.llmChrome === "disconnected") {
    return makeIncident("llm_provider", "info", false, false, "Chat provider — Chat is unavailable");
  }

  return null;
}

function transportIncident(signals: OperatorSignals): OperatorIncident | null {
  if (signals.localPing !== "transport") return null;
  const reason = signals.transportReason;
  if (reason === "dns" || reason === "timeout" || signals.publicSite === "unreachable") {
    return makeIncident(
      "network_local",
      "blocked",
      true,
      false,
      "Local network — the local network or ISP link failed",
    );
  }
  const headline = signals.publicSite === "unknown"
    ? "Backend unreachable — the desk did not answer"
    : "Backend unreachable — the FlintTrade backend is unreachable";
  const incident = makeIncident("backend_unreachable", "blocked", true, false, headline);
  if (signals.publicSite === "unknown") incident.rectify = HOST_UNKNOWN_UPLINK_RECTIFY;
  return incident;
}

function accountFailure(account: ActiveAccountSignal | null): FailureClass | "freeze" | null {
  if (!account) return null;
  const fromText = classFromText(account.errorMessage ?? "", null);
  if (fromText && fromText !== "freeze") return fromText;
  if (account.status === "token_expired" || account.needsRelogin) return "broker_auth";
  return null;
}

function classFromText(message: string, httpStatus: number | null): FailureClass | "freeze" | null {
  const text = message.toLowerCase();
  if (text.includes("broker_account_cutover_unavailable")) return "freeze";
  if (/rate limit|rate-limit|too many requests|order rate/.test(text)) {
    return "broker_rate_limit";
  }
  if (httpStatus === 429 && /broker|order/.test(text)) {
    return "broker_rate_limit";
  }
  if (/circuit|trading halt|exchange halt|exchange is down|exchange unavailable|market halted|scrip suspended|price band/.test(text)) {
    return "exchange";
  }
  if (/under maintenance|maintenance window|scheduled maintenance/.test(text)) {
    return "broker_maintenance";
  }
  if (/token expired|invalid token|invalid session|authentication failed|needs relogin|sign-in failed|login failed/.test(text)) {
    return "broker_auth";
  }
  if (/host unhealthy/.test(text)) return "host_unhealthy";
  if (/cannot reach the flinttrade backend|backend unreachable/.test(text)) {
    return "backend_unreachable";
  }
  // Status alone is not enough: FlintTrade itself returns 5xx for unrelated
  // desks (Chat, vault, cutover). Only broker-shaped copy is broker_rest.
  if (/bad gateway|broker rest|gateway timeout|internal server error/.test(text)) {
    return "broker_rest";
  }
  if (
    (httpStatus === 500 || httpStatus === 502 || httpStatus === 503 || httpStatus === 504)
    && /broker/.test(text)
  ) {
    return "broker_rest";
  }
  return null;
}

function makeIncident(
  failureClass: FailureClass,
  level: OperatorStripLevel,
  moneyPath: boolean,
  nativeHttpFreeze: boolean,
  headline: string,
): OperatorIncident {
  return {
    failureClass,
    level,
    moneyPath,
    nativeHttpFreeze,
    muteBrokerSmoke: failureClass === "broker_rate_limit",
    plainClass: PLAIN_CLASS[failureClass],
    headline,
    rectify: RECTIFY[failureClass],
  };
}
