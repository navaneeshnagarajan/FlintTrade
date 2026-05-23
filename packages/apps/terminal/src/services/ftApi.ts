/**
 * FlintTrade Python backend REST API client — barrel re-export.
 * All logic lives in domain-specific modules. Import from here to avoid
 * breaking any existing imports.
 */

export * from "./ftApi.helpers";
export * from "./ftApi.screener";
export * from "./ftApi.backtest";
export * from "./ftApi.ai";
export * from "./ftApi.automation";
export * from "./ftApi.trading";
export * from "./ftApi.analysis";
export * from "./ftApi.data";
export * from "./ftApi.admin";
export * from "./ftApi.ditto";
export * from "./ftApi.invest";
export * from "./ftApi.workspace";
