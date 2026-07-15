import { describe, expect, it } from "vitest";

import { buildGetCellContent, getColumns } from "../gridConfig";

describe("Option Chain OI cells", () => {
  it("renders an explicit zero as 0 even when the side maximum is zero", () => {
    const columns = getColumns("LTP");
    const callOiColumn = columns.findIndex((column) => column.id === "c_oi");
    const putOiColumn = columns.findIndex((column) => column.id === "p_oi");
    const getCellContent = buildGetCellContent({
      view: "LTP",
      columns,
      strikes: [{ strike: 25000, call: { oi: 0 }, put: { oi: 0 } }],
      atmStrike: 25000,
      maxCallOI: 0,
      maxPutOI: 0,
      isInBasket: () => false,
    });

    expect(getCellContent([callOiColumn, 0])).toMatchObject({ displayData: "0" });
    expect(getCellContent([putOiColumn, 0])).toMatchObject({ displayData: "0" });
  });

  it("renders explicit zero LTP as 0 and unavailable LTP as a dash", () => {
    const columns = getColumns("LTP");
    const callLtpColumn = columns.findIndex((column) => column.id === "c_ltp");
    const putLtpColumn = columns.findIndex((column) => column.id === "p_ltp");
    const getCellContent = buildGetCellContent({
      view: "LTP",
      columns,
      strikes: [{ strike: 25000, call: { ltp: 0 }, put: {} }],
      atmStrike: 25000,
      maxCallOI: 0,
      maxPutOI: 0,
      isInBasket: () => false,
    });

    expect(getCellContent([callLtpColumn, 0])).toMatchObject({ displayData: "0" });
    expect(getCellContent([putLtpColumn, 0])).toMatchObject({ displayData: "—" });
  });
});
