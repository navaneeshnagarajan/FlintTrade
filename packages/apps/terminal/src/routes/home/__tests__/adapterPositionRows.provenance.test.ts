import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import provenance from "./fixtures/adapterPositionRows.provenance.json";

it("binds the unchanged position rows to explicitly synthetic mapper inputs", () => {
  const fixtures = resolve(process.cwd(), "src/routes/home/__tests__/fixtures");
  const root = resolve(process.cwd(), "../../..");
  const digest = (path: string) => createHash("sha256").update(readFileSync(path)).digest("hex");
  expect(provenance.synthetic).toBe(true);
  expect(provenance.fixture).toBe("adapterPositionRows.json");
  expect(digest(resolve(fixtures, provenance.fixture))).toBe(provenance.sha256);
  expect(provenance.source_test).toBe("packages/integrations/gateway/tests/brokers/test_home_position_card_rows.py");
  expect(digest(resolve(root, provenance.source_test))).toBe(provenance.source_test_sha256);
  expect(provenance.source_inputs).toEqual([
    "_DHAN_WITHOUT_PNL", "_DHAN_WITH_PNL", "_DHAN_NO_COST", "_NEO_OPEN_LEG", "_NEO_NO_COST",
  ]);
  expect(provenance.origin).toContain("hardcoded synthetic test inputs");
  expect(provenance.origin).toContain("not captured provider or account data");
});
