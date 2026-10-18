import { describe, expect, it } from "vitest";
import { resolveAccountQueryAvailability } from "../accountQueryState";

const fresh = {
  accountReadsEnabled: true,
  hasData: true,
  isOnline: true,
  isError: false,
  isLoading: false,
  isStale: false,
  fetchStatus: "idle" as const,
};

describe("account query presentation availability", () => {
  it.each([
    { name: "fresh idle evidence", input: {}, expected: "ready" },
    { name: "fresh evidence during refetch", input: { fetchStatus: "fetching" }, expected: "ready" },
    { name: "offline idle evidence", input: { isOnline: false }, expected: "stale" },
    { name: "disabled evidence", input: { accountReadsEnabled: false }, expected: "stale" },
    { name: "paused evidence", input: { fetchStatus: "paused" }, expected: "stale" },
    { name: "failed refresh evidence", input: { isError: true }, expected: "stale" },
    { name: "aged or invalidated idle evidence", input: { isStale: true }, expected: "stale" },
    { name: "stale evidence during refetch", input: { isStale: true, fetchStatus: "fetching" }, expected: "stale" },
    { name: "initial active fetch", input: { hasData: false, isLoading: true, fetchStatus: "fetching" }, expected: "loading" },
    { name: "absent idle evidence", input: { hasData: false }, expected: "unavailable" },
    { name: "absent disabled evidence", input: { hasData: false, accountReadsEnabled: false }, expected: "unavailable" },
    { name: "absent paused evidence", input: { hasData: false, fetchStatus: "paused" }, expected: "unavailable" },
    { name: "absent error evidence", input: { hasData: false, isError: true }, expected: "unavailable" },
    { name: "offline initial in-flight fetch", input: { hasData: false, isLoading: true, fetchStatus: "fetching", isOnline: false }, expected: "unavailable" },
  ] as const)("classifies $name as $expected", ({ input, expected }) => {
    expect(resolveAccountQueryAvailability({ ...fresh, ...input })).toBe(expected);
  });
});
