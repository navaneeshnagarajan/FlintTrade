import { describe, expect, it } from "vitest";

import {
  EXPLORE_ONE_CLICK_TITLE,
  EXPLORE_SCALPER_ORDER_HELPER,
  scalperOneClickTitle,
  scalperOrderBlockCopy,
  scalperOrdersArmed,
} from "./exploreGate";

const UNAVAILABLE_ORDERS =
  "Orders are blocked because the session mode couldn't be confirmed. Sign in again or reload.";
const UNAVAILABLE_ONE_CLICK =
  "One-click is unavailable because the session mode couldn't be confirmed. Sign in again or reload.";

describe("scalper mode copy", () => {
  it("blocks Example with Example copy and arms Practice and Live", () => {
    expect(scalperOrdersArmed("explore")).toBe(false);
    expect(scalperOrdersArmed("practice")).toBe(true);
    expect(scalperOrdersArmed("live")).toBe(true);
    expect(scalperOrderBlockCopy("explore")).toBe(EXPLORE_SCALPER_ORDER_HELPER);
    expect(scalperOneClickTitle("explore")).toBe(EXPLORE_ONE_CLICK_TITLE);
  });

  it("tells an unconfirmed session to sign in again or reload, and never says Example or Sample", () => {
    expect(scalperOrdersArmed("unavailable")).toBe(false);
    expect(scalperOrderBlockCopy("unavailable")).toBe(UNAVAILABLE_ORDERS);
    expect(scalperOneClickTitle("unavailable")).toBe(UNAVAILABLE_ONE_CLICK);
    expect(scalperOrderBlockCopy("unavailable")).not.toMatch(/Example|Sample/);
    expect(scalperOneClickTitle("unavailable")).not.toMatch(/Example|Sample/);
  });

  it("has no block copy while orders are armed", () => {
    expect(scalperOrderBlockCopy("practice")).toBeNull();
    expect(scalperOrderBlockCopy("live")).toBeNull();
  });
});
