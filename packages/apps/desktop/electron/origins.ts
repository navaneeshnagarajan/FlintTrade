export type RendererOrigin = "splash" | "terminal" | "untrusted";

export interface RendererOriginPolicy {
  splashUrl: string;
  terminalOrigin: string | null;
}

export interface IpcSenderEvent {
  senderFrame?: {
    url?: string;
  } | null;
}

export function normaliseLoopbackOrigin(rawUrl: string): string | null {
  try {
    const parsed = new URL(rawUrl);
    if (
      parsed.protocol !== "http:" ||
      parsed.hostname !== "127.0.0.1" ||
      parsed.port === "" ||
      parsed.username !== "" ||
      parsed.password !== ""
    ) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

export function classifyRendererUrl(rawUrl: string, policy: RendererOriginPolicy): RendererOrigin {
  if (rawUrl === policy.splashUrl) {
    return "splash";
  }

  const senderOrigin = normaliseLoopbackOrigin(rawUrl);
  const selectedOrigin = policy.terminalOrigin ? normaliseLoopbackOrigin(policy.terminalOrigin) : null;
  if (senderOrigin !== null && selectedOrigin !== null && senderOrigin === selectedOrigin) {
    return "terminal";
  }

  return "untrusted";
}

export function assertIpcSender(event: IpcSenderEvent, policy: RendererOriginPolicy): Exclude<RendererOrigin, "untrusted"> {
  const senderUrl = event.senderFrame?.url ?? "";
  const origin = classifyRendererUrl(senderUrl, policy);
  if (origin === "untrusted") {
    const error = new Error("Rejected untrusted IPC sender.") as Error & { code: string };
    error.code = "ERR_UNTRUSTED_IPC_SENDER";
    throw error;
  }
  return origin;
}
