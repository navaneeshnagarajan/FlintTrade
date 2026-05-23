export type AuthFlowType = "oauth_redirect" | "totp_form" | "api_key_direct" | "otp_sms";
export type AccountStatus = "disconnected" | "authenticating" | "connected" | "error" | "token_expired";

export interface BrokerInfo {
  name: string;
  display_name: string;
  auth_flow: AuthFlowType;
  exchanges: string[];
  max_symbols_per_ws: number;
  supports_streaming: boolean;
  oauth_url_template: string | null;
  is_sandbox: boolean;
}

export interface BrokerAccount {
  account_id: string;
  broker: string;
  label: string;
  status: AccountStatus;
  connected_at: string | null;
  error_message: string | null;
  is_primary: boolean;
}

export interface OAuthStartResponse {
  redirect_url: string;
  state: string;
}

export interface TOTPAuthFields {
  client_id: boolean;
  password: boolean;
  totp: boolean;
  pin: boolean;
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
