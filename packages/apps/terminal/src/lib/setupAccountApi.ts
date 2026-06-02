export interface AccountSetupInput {
  username: string;
  email: string;
  password: string;
  pin?: string;
}

export interface AccountSetupResult {
  totpUri: string;
  backupCodes: string[];
}

export type AccountSetupErrorKind = "account-exists" | "network" | "server";

export class AccountSetupError extends Error {
  kind: AccountSetupErrorKind;
  status?: number;

  constructor(message: string, kind: AccountSetupErrorKind, status?: number) {
    super(message);
    this.name = "AccountSetupError";
    this.kind = kind;
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

async function parseJsonBody(response: Response): Promise<unknown> {
  const raw = await response.text();
  if (!raw.trim()) return null;

  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

function extractMessage(payload: unknown): string | null {
  if (!isRecord(payload)) return null;
  const message = payload.message ?? payload.error;
  return typeof message === "string" && message.trim() ? message : null;
}

function httpMessage(response: Response): string {
  const statusText = response.statusText.trim();
  return `FlintTrade backend responded with HTTP ${response.status}${statusText ? ` ${statusText}` : ""}.`;
}

export async function setupFlintTradeAccount(input: AccountSetupInput): Promise<AccountSetupResult> {
  let response: Response;

  try {
    response = await fetch("/ft-api/v1/auth/setup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: input.username,
        email: input.email,
        password: input.password,
        pin: input.pin || "",
      }),
    });
  } catch {
    throw new AccountSetupError(
      "Cannot reach server. Is the FlintTrade backend running?",
      "network",
    );
  }

  const payload = await parseJsonBody(response);

  if (!response.ok) {
    throw new AccountSetupError(
      extractMessage(payload) ?? httpMessage(response),
      response.status === 409 ? "account-exists" : "server",
      response.status,
    );
  }

  if (!isRecord(payload) || !isRecord(payload.data)) {
    throw new AccountSetupError(
      "FlintTrade backend returned an unexpected setup response.",
      "server",
      response.status,
    );
  }

  const totpUri = typeof payload.data.totp_uri === "string" ? payload.data.totp_uri : "";
  const backupCodes = Array.isArray(payload.data.backup_codes)
    ? payload.data.backup_codes.filter((code): code is string => typeof code === "string")
    : [];

  return { totpUri, backupCodes };
}
