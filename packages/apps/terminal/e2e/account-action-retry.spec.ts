import { expect, test } from "./fixture-registry";
import { seedExploreDemoSession } from "./helpers";

test.use({ benignConsoleErrors: [{
  text: "Failed to load resource: the server responded with a status of 503 (Service Unavailable)",
  url: "http://localhost:5173/ft-api/api/v1/native/accounts",
}] });

test("broker connection retry retains its action identity after an ambiguous response", async ({ page, syntheticApi }) => {
  const warnings: string[] = [];
  page.on("console", (message) => { if (message.type() === "warning") warnings.push(message.text()); });
  await seedExploreDemoSession(page);
  for (const [name, data] of Object.entries({
    openalgo: { host: "", ws_port: 8765, api_key_configured: false },
    llm: { provider: "", host: "", model: "", api_key_configured: false },
  })) {
    syntheticApi.register({
      name: `settings hydration ${name}`, method: "GET", path: `/ft-api/v1/config/${name}`,
      expectedCalls: 2,
      handler: () => ({ json: { status: "success", data } }),
    });
  }
  syntheticApi.register({
    name: "synthetic native catalogue", method: "GET", path: "/ft-api/api/v1/native/brokers",
    handler: () => ({ json: { status: "success", data: { brokers: [{
      adapter_id: "dhan", display_name: "Dhan", connectable: true, requires_static_ip: false,
      native_connect_blockers: [], sdk_attestation: { status: "ok" },
      auth_methods: [{ id: "access_token", label: "Access token", kind: "direct", description: "Fixture only",
        fields: [
          { name: "client_id", label: "Dhan client ID", secret: false, required: true, help: "" },
          { name: "access_token", label: "Access token", secret: true, required: true, help: "" },
        ] }],
    }] } } }),
  });
  syntheticApi.register({
    name: "empty MCP catalogue", method: "GET", path: "/ft-api/api/v1/broker/mcp",
    handler: () => ({ json: { status: "success", data: { brokers: [] } } }),
  });
  const keys: string[] = [];
  syntheticApi.register({
    name: "ambiguous then recovered connection", method: "POST", path: "/ft-api/api/v1/native/accounts",
    expectedCalls: 2,
    handler: (request) => {
      const key = request.headers()["idempotency-key"];
      expect(key).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
      keys.push(key);
      return keys.length === 1
        ? { status: 503, json: { status: "error", message: "Synthetic response lost; retry the same action." } }
        : { json: { status: "success", data: { connected: true, login: "ok" } } };
    },
  });
  for (const path of ["/ft-api/v1/accounts", "/ft-api/api/v1/native/accounts"]) {
    syntheticApi.register({
      name: `post-action refresh ${path}`, method: "GET", path,
      handler: () => ({ json: { status: "success", data: { accounts: [] } } }),
    });
  }
  await page.goto("/settings#brokers");
  await expect(page).toHaveURL("http://localhost:5173/settings#brokers");
  await expect(page).toHaveTitle(/FlintTrade/i);
  await page.getByRole("combobox", { name: /^Broker$/i }).click();
  await page.getByRole("option", { name: "Dhan", exact: true }).click();
  await page.getByRole("combobox", { name: /login method/i }).click();
  await page.getByRole("option", { name: "Access token", exact: true }).click();
  await page.getByLabel(/account id/i).fill("FIXTURE-ACCOUNT");
  await page.getByLabel("Dhan client ID", { exact: true }).fill("FIXTURE-ACCOUNT");
  await page.getByLabel("Access token", { exact: true }).fill("SYNTHETIC-NOT-A-CREDENTIAL");
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Synthetic response lost; retry the same action.")).toBeVisible();
  await page.getByRole("button", { name: "Connect", exact: true }).click();
  await expect(page.getByText("Dhan account FIXTURE-ACCOUNT connected.", { exact: true })).toBeVisible();
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  await expect.poll(() => syntheticApi.callCount("GET", "/ft-api/api/v1/native/accounts")).toBe(1);
  await expect(page.locator("vite-error-overlay")).toHaveCount(0);
  expect(warnings).toEqual([]);
  const screenshot = process.env["FLINTTRADE_E2E_SCREENSHOT"];
  if (screenshot) await page.screenshot({ path: screenshot });
});
