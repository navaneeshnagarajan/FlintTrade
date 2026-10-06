/** About component/browser coverage only: all backend responses are synthetic. */
import { test, expect } from "./fixture-registry";

const inventory = {
  app_version: "0.0.1", runtimes: [{ name: "Python", version: "3.12.9" }],
  packages: [{ name: "flask", installed: "3.1.2", configured: "3.1.1" }],
  brokers: [
    { name: "dhanhq", installed: "2.2.0", configured: "2.2.0", source_commit: null, installed_commit: null },
    { name: "upstox-python-sdk", installed: "2.29.0", configured: "2.30.0", source_commit: null, installed_commit: null },
    { name: "growwapi", installed: null, configured: "1.5.0", source_commit: null, installed_commit: null },
    { name: "kotakneoapi", installed: "3.0.8", configured: "3.0.8", release_version: "3.0.7", source_commit: "a".repeat(40), installed_commit: "b".repeat(40) },
  ],
};

test("About separates observed versions and pins without runtime mutations", async ({ page, syntheticApi }, testInfo) => {
  syntheticApi.register({ name: "version inventory", method: "GET", path: "/ft-api/api/v1/versions", expectedCalls: 1, handler: () => ({ json: inventory }) });
  syntheticApi.register({ name: "pure Ollama versions", method: "GET", path: "/ft-api/api/v1/versions/ollama", expectedCalls: 1, handler: () => ({ json: { configured: "v0.35.0", reported: "0.32.0", status: "reported" } }) });
  await page.goto("/e2e/about-versions.fixture.html");
  await expect(page.getByRole("table", { name: "Backend runtimes" })).toContainText("3.12.9");
  await expect(page.getByRole("table", { name: "Frontend libraries" }).getByRole("row", { name: /^React / })).toContainText("^19.3.0");
  await expect(page.getByRole("table", { name: "Broker SDKs" })).toContainText("Not installed / unavailable");
  await expect(page.getByText(/kotakneoapi release compatibility baseline/)).toContainText("3.0.7");
  await expect(page.getByText("a".repeat(40), { exact: true })).toBeVisible();
  await expect(page.getByText("b".repeat(40), { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Ollama", exact: true })).toContainText("v0.35.0");
  await expect(page.getByRole("table", { name: "Ollama", exact: true })).toContainText("0.32.0");
  await expect(page.getByText(/Not running in a desktop shell/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("about-versions.png"), fullPage: true });
});

test("Demo About shows build metadata without querying local runtimes", async ({ page }) => {
  await page.goto("/e2e/about-versions.fixture.html?mode=demo");
  await expect(page.getByText(/Backend and Ollama versions are unavailable in Demo/)).toBeVisible();
  await expect(page.getByRole("table", { name: "Frontend libraries" })).toBeVisible();
});

test("Unavailable observations stay unavailable", async ({ page, syntheticApi }) => {
  syntheticApi.register({ name: "malformed older backend", method: "GET", path: "/ft-api/api/v1/versions", expectedCalls: 1, handler: () => ({ json: { status: "unsupported" } }) });
  syntheticApi.register({ name: "unavailable Ollama", method: "GET", path: "/ft-api/api/v1/versions/ollama", expectedCalls: 1, handler: () => ({ json: { configured: "v0.35.0", reported: null, status: "unavailable" } }) });
  await page.goto("/e2e/about-versions.fixture.html");
  await expect(page.getByText(/Backend version information is unavailable/)).toBeVisible();
  await expect(page.getByRole("row", { name: "Reported running server Unavailable" })).toBeVisible();
  await expect(page.getByText("Not responding", { exact: true })).toHaveCount(0);
});
