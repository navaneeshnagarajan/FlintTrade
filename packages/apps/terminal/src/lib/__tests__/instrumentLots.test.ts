import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, vi } from "vitest";

import fixture from "@flinttrade/instrument-lots";
import {
  contractsFromRows,
  indexLotLine,
  instrumentLotRows,
  loadInstrumentLotRows,
  lotSizeForContract,
  lotSizeFromMaster,
  scalperLotLabel,
  setInstrumentLotRows,
  type ScripRow,
} from "../instrumentLots";

const revision = JSON.parse(
  readFileSync(
    resolve(
      dirname(fileURLToPath(import.meta.url)),
      "../../../../../core/core/tests/data/instrument_lot_revision_window.json",
    ),
    "utf8",
  ),
) as {
  rows: Parameters<typeof contractsFromRows>[0];
  clash_row: Parameters<typeof contractsFromRows>[0][number];
};

const AS_OF = "2026-09-01";
const SYNTHETIC_IDS = ["13", "14", "25", "51", "9013", "9014", "9025", "9051"];

describe("lotSizeFromMaster", () => {
  it("reads the revision window from the test fixture", () => {
    const rows = revision.rows;
    expect(lotSizeForContract("13", rows, AS_OF)).toBe(75);
    expect(lotSizeForContract("9013", rows, AS_OF)).toBe(75);
    expect(lotSizeForContract("14", rows, AS_OF)).toBe(65);
    expect(lotSizeForContract("9014", rows, AS_OF)).toBe(65);
    expect(lotSizeFromMaster("NIFTY", rows, AS_OF)).toBe(75);
    expect(lotSizeFromMaster("BANKNIFTY", rows, AS_OF)).toBe(30);
    expect(lotSizeFromMaster("SENSEX", rows, AS_OF)).toBe(20);
    expect(scalperLotLabel("NIFTY", rows, AS_OF)).toBe("75 · Oct expiry, 65 · Nov expiry");
    expect(scalperLotLabel("BANKNIFTY", rows, AS_OF)).toBe("30 · Sep expiry");
    expect(scalperLotLabel("SENSEX", rows, AS_OF)).toBe("20 · Sep expiry");
  });

  it("drops a contract once its expiry is before the frozen date", () => {
    const rows = revision.rows;
    expect(lotSizeForContract("13", rows, "2026-10-28")).toBeNull();
    expect(lotSizeForContract("14", rows, "2026-10-28")).toBe(65);
    expect(scalperLotLabel("NIFTY", rows, "2026-10-28")).toBe("65 · Nov expiry");
    expect(lotSizeFromMaster("BANKNIFTY", rows, "2026-09-25")).toBeNull();
    expect(scalperLotLabel("SENSEX", rows, "2026-09-25")).toBeNull();
  });

  it("does not invent a lot size for a symbol the master does not list", () => {
    expect(lotSizeFromMaster("FINNIFTY")).toBeNull();
    expect(scalperLotLabel("FINNIFTY")).toBeNull();
  });

  it("rejects one contract that disagrees across the masters and keeps two expiries", () => {
    const rows = revision.rows.filter(
      (row) => row.SEM_CUSTOM_SYMBOL === "NIFTY" || row.pSymbolName === "NIFTY",
    );
    expect(lotSizeForContract("13", rows, AS_OF)).toBe(75);
    expect(lotSizeForContract("14", rows, AS_OF)).toBe(65);
    expect(scalperLotLabel("NIFTY", rows, AS_OF)).toBe("75 · Oct expiry, 65 · Nov expiry");
    expect(() => contractsFromRows([...rows, revision.clash_row])).toThrow(
      /disagrees on the lot size for NIFTY 2026-10-27/,
    );
  });

  it("ships source and fetched_at and no synthetic security ids", () => {
    const shipped = fixture as {
      source?: unknown;
      fetched_at?: unknown;
      rows?: { SEM_SMST_SECURITY_ID?: string; pSymbol?: string }[];
    };
    expect(Array.isArray(shipped.source)).toBe(true);
    expect((shipped.source as string[]).length).toBeGreaterThan(0);
    expect((shipped.source as string[]).every((url) => url.startsWith("https://"))).toBe(true);
    expect(typeof shipped.fetched_at).toBe("string");
    expect(shipped.fetched_at).not.toBe("");
    const ids = (shipped.rows ?? []).flatMap((row) => [row.SEM_SMST_SECURITY_ID, row.pSymbol]).filter(Boolean);
    expect(ids.some((id) => SYNTHETIC_IDS.includes(id as string))).toBe(false);
  });

  it("follows a cache revision for the caption and the quantity check, not the excerpt", async () => {
    const asOf = "2026-09-29";
    const cacheRows: ScripRow[] = [
      {
        SEM_SMST_SECURITY_ID: "CACHE-NIFTY",
        SEM_CUSTOM_SYMBOL: "NIFTY",
        SEM_INSTRUMENT_NAME: "FUTIDX",
        SEM_TRADING_SYMBOL: "NIFTY-Oct2026-FUT",
        SEM_EXPIRY_DATE: "2099-12-31",
        SEM_LOT_UNITS: "50",
      },
    ];
    const shipped = fixture as { rows: ScripRow[] };
    expect(lotSizeFromMaster("NIFTY", shipped.rows, asOf)).toBe(65);
    expect(scalperLotLabel("NIFTY", shipped.rows, asOf)).toBe("65 · Sep expiry");

    setInstrumentLotRows([]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        rows: cacheRows,
        line: "NIFTY 50 · BANKNIFTY — · SENSEX — (Dec expiry)",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await loadInstrumentLotRows();

    expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/api/v1/instrument-lots");
    const rows = instrumentLotRows();
    const label = scalperLotLabel("NIFTY", rows, asOf);
    const lot = lotSizeForContract("CACHE-NIFTY", rows, asOf);
    expect(label).toBe("50 · Dec expiry");
    expect(lot).toBe(50);
    expect(indexLotLine(rows, asOf)).toBe("NIFTY 50 · BANKNIFTY — · SENSEX — (Dec expiry)");
    expect(lot).not.toBeNull();
    expect(50 % (lot as number)).toBe(0);
    expect(65 % (lot as number)).not.toBe(0);
    expect(lotSizeFromMaster("NIFTY", shipped.rows, asOf)).toBe(65);
    vi.unstubAllGlobals();
  });
});
