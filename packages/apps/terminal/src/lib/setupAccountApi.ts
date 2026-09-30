import { buildHeaders, getBase } from "@/services/ftApi.helpers";

export interface AccountSetupInput {
  username: string;
  email: string;
  password: string;
  pin?: string;
}

export interface AccountSetupResult {
  totpUri: string;
  backupCodes: string[];
  /** Practice session token minted at account creation so the vault step
   * and any optional setup the operator chooses are authenticated. */
  token: string;
}

export interface VaultOpenResult {
  opened: true;
  alreadyPresent: boolean;
}

/** Public first-run facts from GET /v1/auth/status. No secrets. */
export interface SetupServerState {
  isSetup: boolean;
  /** True when this machine currently has a hardened vault secret. */
  vaultOpen: boolean;
  /**
   * Whether the vault was already secured when the operator was created.
   * Null before that fact exists. A later vault open does not change it.
   */
  vaultPresecured: boolean | null;
  /** True only after the operator has finished Setup. */
  setupFinished: boolean;
  /**
   * `two_operators` when an update paused because more than one operator
   * row exists. Null when the desk may open.
   */
  migrationBlocked: "two_operators" | null;
}

export interface SetupResumeResult {
  token: string;
  username: string;
}

export type AccountSetupErrorKind = "account-exists" | "network" | "server";

/** Lost or repeated setup-create. The setup screen maps this to sign-in. */
export const OPERATOR_EXISTS_CODE = "operator_exists";

export class AccountSetupError extends Error {
  kind: AccountSetupErrorKind;
  status?: number;
  code?: string;

  constructor(message: string, kind: AccountSetupErrorKind, status?: number, code?: string) {
    super(message);
    this.name = "AccountSetupError";
    this.kind = kind;
    this.status = status;
    this.code = code;
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
    response = await fetch(`${getBase()}/v1/auth/setup`, {
      method: "POST",
      headers: buildHeaders(true),
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
    const code = isRecord(payload) && typeof payload.code === "string" ? payload.code : undefined;
    const operatorExists = response.status === 409 && code === OPERATOR_EXISTS_CODE;
    throw new AccountSetupError(
      extractMessage(payload) ?? httpMessage(response),
      operatorExists ? "account-exists" : "server",
      response.status,
      code,
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
  const token = typeof payload.data.token === "string" ? payload.data.token : "";

  return { totpUri, backupCodes, token };
}

/** Open the credential vault. Never returns the master password. */
export async function openFlintTradeVault(masterPassword: string): Promise<VaultOpenResult> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/setup/vault`, {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ master_password: masterPassword }),
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
      "server",
      response.status,
    );
  }

  if (!isRecord(payload) || !isRecord(payload.data) || payload.data.opened !== true) {
    throw new AccountSetupError(
      "FlintTrade backend returned an unexpected vault response.",
      "server",
      response.status,
    );
  }

  return {
    opened: true,
    alreadyPresent: payload.data.already_present === true,
  };
}

/** Read whether an operator exists, the vault is open, and Setup has finished. */
export async function fetchSetupServerState(): Promise<SetupServerState> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/status`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
  } catch {
    throw new AccountSetupError(
      "Cannot reach server. Is the FlintTrade backend running?",
      "network",
    );
  }

  let payload: unknown;
  try {
    payload = await parseJsonBody(response);
  } catch {
    // A truncated or closed body means the server answered and the read
    // failed. That is not a network failure.
    throw new AccountSetupError(
      httpMessage(response),
      "server",
      response.status,
    );
  }
  if (
    !response.ok
    || !isRecord(payload)
    || !isRecord(payload.data)
    || typeof payload.data.is_setup !== "boolean"
  ) {
    throw new AccountSetupError(
      extractMessage(payload) ?? httpMessage(response),
      "server",
      response.status,
    );
  }

  const presecured = payload.data.vault_presecured;
  return {
    isSetup: payload.data.is_setup === true,
    vaultOpen: payload.data.vault_open === true,
    vaultPresecured: typeof presecured === "boolean" ? presecured : null,
    setupFinished: payload.data.setup_finished === true,
    migrationBlocked: payload.data.migration_blocked === "two_operators" ? "two_operators" : null,
  };
}

/**
 * Re-mint the setup session after a reload. Password proof stands in for
 * the account-create JWT that lived only in this browser tab.
 */
export async function resumeFlintTradeSetup(password: string): Promise<SetupResumeResult> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/setup/resume`, {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ password }),
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
      "server",
      response.status,
    );
  }

  if (
    !isRecord(payload)
    || !isRecord(payload.data)
    || typeof payload.data.token !== "string"
    || !payload.data.token
    || typeof payload.data.username !== "string"
    || !payload.data.username
  ) {
    throw new AccountSetupError(
      "FlintTrade backend returned an unexpected setup response.",
      "server",
      response.status,
    );
  }

  return { token: payload.data.token, username: payload.data.username };
}

/** Record that the operator has finished first-run setup. */
export async function completeFlintTradeSetup(): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/setup/complete`, {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({}),
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
      "server",
      response.status,
    );
  }
}

export interface TotpEnrolmentMaterial {
  totpUri: string;
  backupCodes: string[];
}

/**
 * Issue a fresh authenticator QR and backup codes for an existing account.
 *
 * Password-confirmed. Used when the operator chose "Set up later" and later
 * enrols from Settings → Security. The new secret is not enrolled until
 * {@link enableFlintTradeTotp} accepts a live code.
 */
export async function regenerateFlintTradeTotp(password: string): Promise<TotpEnrolmentMaterial> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/setup/regenerate-2fa`, {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ password }),
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
      "server",
      response.status,
    );
  }

  if (!isRecord(payload) || !isRecord(payload.data)) {
    throw new AccountSetupError(
      "FlintTrade backend returned an unexpected authenticator response.",
      "server",
      response.status,
    );
  }

  const totpUri = typeof payload.data.totp_uri === "string" ? payload.data.totp_uri : "";
  const backupCodes = Array.isArray(payload.data.backup_codes)
    ? payload.data.backup_codes.filter((code): code is string => typeof code === "string")
    : [];
  if (!totpUri) {
    throw new AccountSetupError(
      "FlintTrade backend did not return an authenticator QR.",
      "server",
      response.status,
    );
  }

  return { totpUri, backupCodes };
}

/** Confirm optional authenticator enrolment with a live TOTP code. */
export async function enableFlintTradeTotp(totpCode: string): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${getBase()}/v1/auth/totp/enable`, {
      method: "POST",
      headers: buildHeaders(true),
      body: JSON.stringify({ totp_code: totpCode }),
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
      "server",
      response.status,
    );
  }
}
