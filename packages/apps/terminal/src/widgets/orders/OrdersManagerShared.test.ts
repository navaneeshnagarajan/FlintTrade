import { describe, expect, it } from "vitest";
import type { BrokerAccount } from "@/types/broker";
import {
  brokerOrderTargetOptions,
  brokerOrderTargetExists,
  DEFAULT_BROKER_TARGET,
  isBrokerOrderTargetableAccount,
} from "./OrdersManagerShared";

const account = (overrides: Partial<BrokerAccount> = {}): BrokerAccount => ({
  account_id: "A1",
  broker: "dhan",
  label: "Dhan",
  status: "connected",
  connected_at: null,
  error_message: null,
  is_primary: false,
  source: "native",
  ...overrides,
});

describe("broker order target selection", () => {
  it("only treats connected accounts as selectable live order targets", () => {
    expect(isBrokerOrderTargetableAccount(account({ status: "connected" }))).toBe(true);
    expect(isBrokerOrderTargetableAccount(account({ status: "connected", read_only: true }))).toBe(false);
    expect(isBrokerOrderTargetableAccount(account({ status: "token_expired" }))).toBe(false);
    expect(isBrokerOrderTargetableAccount(account({ status: "disconnected" }))).toBe(false);
  });

  it("keeps OpenAlgo available but rejects stale native targets", () => {
    expect(brokerOrderTargetExists(DEFAULT_BROKER_TARGET, [])).toBe(true);
    expect(
      brokerOrderTargetExists(
        { broker: "dhan", account_id: "A1" },
        [account({ status: "connected" })],
      ),
    ).toBe(true);
    expect(
      brokerOrderTargetExists(
        { broker: "dhan", account_id: "A1" },
        [account({ status: "token_expired" })],
      ),
    ).toBe(false);
  });

  it("can restrict a management surface to supported native brokers", () => {
    const options = brokerOrderTargetOptions(
      [
        account({ account_id: "D1", broker: "dhan", source: "native" }),
        account({ account_id: "U1", broker: "upstox", source: "native" }),
        account({ account_id: "G1", broker: "groww", source: "native" }),
        account({ account_id: "D2", broker: "dhan", source: "gateway" }),
      ],
      {
        includeOpenAlgo: false,
        nativeOnly: true,
        supportedBrokers: ["dhan", "upstox"],
      },
    );

    expect(options.map((option) => option.target)).toStrictEqual([
      { broker: "dhan", account_id: "D1" },
      { broker: "upstox", account_id: "U1" },
    ]);
  });
});
