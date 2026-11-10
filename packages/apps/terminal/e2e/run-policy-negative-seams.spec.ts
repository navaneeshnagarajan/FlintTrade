import { createServer, type Server } from "node:http";
import { test, expect } from "@playwright/test";
import { exactAcknowledgementCorruption, installDecodedReadHold } from "./run-policy-negative-seams";

const path = "/v1/model-runs/synthetic/configuration";
const original = '{"scope":{"run_id":"synthetic"},"unmodified":"नमस्ते"}\n';
for (const control of ["wrong-method", "wrong-path", "wrong-query", "wrong-status", "missing-scope", "invalid-json", "unused", "overuse", "invalid-registration"]) {
  test(`exact ACK corruption refusal ${control}`, () => {
    const fault = exactAcknowledgementCorruption(path + "/confirm");
    const args: [string, string, number, string] = ["POST", path + "/confirm", 200, original];
    if (control === "wrong-method") args[0] = "GET";
    if (control === "wrong-path") args[1] = path;
    if (control === "wrong-query") args[1] += "?extra=true";
    if (control === "wrong-status") args[2] = 503;
    if (control === "missing-scope") args[3] = "{}";
    if (control === "invalid-json") args[3] = "{";
    if (control === "invalid-registration") { expect(() => exactAcknowledgementCorruption("/api/v1/orders/place")).toThrow(); return; }
    if (control === "unused") { expect(() => fault.assertUsed()).toThrow(); return; }
    if (control === "overuse") {
      expect(fault.apply(...args)).not.toBe(original);
      fault.assertUsed();
    }
    expect(() => fault.apply(...args)).toThrow();
  });
}

test.describe("native decoded scheduling qualification", () => {
  let server: Server;
  let origin: string;
  test.beforeEach(async () => {
    server = createServer((request, response) => {
      if (request.url === "/") { response.setHeader("Content-Type", "text/html"); response.end("<!doctype html><title>Native scheduling control</title>"); return; }
      response.setHeader("Content-Type", "application/json");
      if (request.headers["x-hold-body"]) { response.write('{"scope":'); return; }
      if (request.headers["x-refuse"]) response.statusCode = 503;
      response.end(original);
    });
    // The default Playwright server already owns 5173. This control only needs
    // its own loopback origin, so it takes a free port.
    await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
    const address = server.address();
    if (address === null || typeof address === "string") throw new Error("Missing scheduling control address");
    origin = `http://127.0.0.1:${address.port}`;
  });
  test.afterEach(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); });
  test("unchanged native decoded body held after complete HTTP then delivered once", async ({page}) => {
    await page.goto(origin);
    const hold = await installDecodedReadHold(page, path);
    let finished = false;
    page.on("requestfinished", request => { if (new URL(request.url()).pathname === path) finished = true; });
    const pending = page.evaluate(async target => JSON.stringify(await (await fetch(target)).json()), path);
    try {
      await expect.poll(() => finished).toBe(true);
      await expect.poll(async () => (await hold.snapshot()).entered).toBe(1);
      expect((await hold.snapshot()).delivered).toBe(0);
      await hold.release();
      expect(await pending).toBe(JSON.stringify(JSON.parse(original)));
      expect(await hold.snapshot()).toMatchObject({originalText:original, entered:1,delivered:1,sameReference:true,failures:[]});
    } finally { await hold.restore(); await pending; }
  });
  test("wrong URL stays native and duplicate installation refuses", async ({page}) => {
    await page.goto(origin);
    const hold = await installDecodedReadHold(page, path);
    try {
      await expect(installDecodedReadHold(page,path)).rejects.toThrow("already installed");
      expect(await page.evaluate(async () => JSON.stringify(await (await fetch("/different")).json()))).toBe(JSON.stringify(JSON.parse(original)));
      expect((await hold.snapshot()).entered).toBe(0);
    } finally { await hold.restore(); }
  });
  test("second matching decode refuses and latches overuse", async ({page}) => {
    await page.goto(origin);
    const hold = await installDecodedReadHold(page,path);
    const first = page.evaluate(async target => (await fetch(target)).json(),path);
    try {
      await expect.poll(async () => (await hold.snapshot()).entered).toBe(1);
      await expect(page.evaluate(async target => (await fetch(target)).json(),path)).rejects.toThrow("scope/count refused");
      expect((await hold.snapshot()).failures).toEqual(["Decoded scheduling scope/count refused"]);
    } finally { await hold.restore(); await first; }
  });
  test("native cancelled body never counts as decoded delivery", async ({page}) => {
    await page.goto(origin);
    const hold = await installDecodedReadHold(page,path);
    try {
      const result = await page.evaluate(async target => {
        const abort = new AbortController();
        const response = await fetch(target,{headers:{"x-hold-body":"yes"},signal:abort.signal});
        const pending = response.json();abort.abort();
        try { await pending; return "unexpected-success"; } catch(error) { return error instanceof Error ? error.name : "unknown"; }
      },path);
      expect(result).toBe("AbortError");
      expect(await hold.snapshot()).toEqual({path,entered:0,delivered:0,failures:[]});
    } finally { await hold.restore(); }
  });
  test("non-success body is not admitted by the decoded seam", async ({page}) => {
    await page.goto(origin);
    const hold = await installDecodedReadHold(page,path);
    try {
      await expect(page.evaluate(async target=>(await fetch(target,{headers:{"x-refuse":"yes"}})).json(),path)).rejects.toThrow("scope/count refused");
      expect(await hold.snapshot()).toEqual({path,entered:0,delivered:0,failures:["Decoded scheduling scope/count refused"]});
    } finally { await hold.restore(); }
  });
});
