export type AuthFlowType =
  | "oauth_redirect"
  | "totp_form"
  | "api_key_direct"
  | "otp_sms"
  | "otp_multistep";
export type AccountStatus = "disconnected" | "authenticating" | "connected" | "error" | "token_expired";

export interface AuthMethodField {
  name: string;
  label: string;
  secret: boolean;
  required: boolean;
  help: string;
}

export interface AuthMethod {
  id: string;
  label: string;
  kind: "direct" | "oauth" | string;
  description: string;
  fields: AuthMethodField[];
}

export interface BrokerInfo {
  name: string;
  display_name: string;
  auth_flow: AuthFlowType;
  exchanges: string[];
  max_symbols_per_ws: number;
  supports_streaming: boolean;
  oauth_url_template: string | null;
  is_sandbox: boolean;
  aux_params?: string[];
  native?: boolean;
  connectable?: boolean;
  auth_methods?: AuthMethod[];
  sdk_pin?: string | null;
}

export interface BrokerAccount {
  account_id: string;
  broker: string;
  label: string;
  status: AccountStatus;
  connected_at: string | null;
  error_message: string | null;
  is_primary: boolean;
  source?: "gateway" | "native";
  expires_at?: number | null;
  needs_relogin?: boolean;
  login_retryable?: boolean;
}

export interface TOTPAuthFields {
  client_id?: boolean;
  password?: boolean;
  totp?: boolean;
  pin?: boolean;
  api_key?: boolean;
  api_secret?: boolean;
}

export type AuthFlowState =
  | { step: "idle" }
  | { step: "selecting_broker" }
  | { step: "entering_credentials"; broker: BrokerInfo; fields: TOTPAuthFields }
  | { step: "awaiting_redirect"; broker: BrokerInfo; redirectUrl: string }
  | { step: "awaiting_otp"; broker: BrokerInfo }
  | { step: "authenticating"; broker: BrokerInfo }
  | { step: "success"; account: BrokerAccount }
  | { step: "error"; message: string };
