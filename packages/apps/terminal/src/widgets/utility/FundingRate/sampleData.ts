/** Fixed examples for explaining periodic perpetual funding; no provider source. */
export interface ExampleFundingRate {
  readonly symbol: string;
  /** Signed fraction of position notional per funding period. */
  readonly rate: number;
  readonly history: readonly number[];
}

export const EXAMPLE_FUNDING_RATES: readonly ExampleFundingRate[] = [
  { symbol: "BTCUSD", rate: 0.0001, history: [0.00004, 0.00006, 0.00003, 0.00008, 0.00007, 0.00009, 0.0001] },
  { symbol: "ETHUSD", rate: -0.0002, history: [-0.00005, -0.00008, -0.0001, -0.00007, -0.00014, -0.00018, -0.0002] },
  { symbol: "SOLUSD", rate: 0.0003, history: [0.0001, 0.00012, 0.00018, 0.00016, 0.00022, 0.00026, 0.0003] },
  { symbol: "XRPUSD", rate: 0, history: [0.00002, -0.00001, 0, 0.00001, -0.00002, 0.00001, 0] },
];
