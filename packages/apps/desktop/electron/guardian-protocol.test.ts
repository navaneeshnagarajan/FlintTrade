import { describe, expect, it } from "vitest";

import { GuardianProtocol, parseGuardianLine } from "./guardian-protocol";

const TOKEN = "a".repeat(64);

describe("guardian protocol", () => {
  it("parses only exact, complete guardian lines", () => {
    const protocol = new GuardianProtocol();
    const events = protocol.feed(Buffer.from([
      "ordinary startup log",
      "FLINTTRADE_BACKEND_PID pid=4321",
      "FLINTTRADE_BACKEND_READY port=5100",
      "FLINTTRADE_BACKEND_BLOCKED reason=instance-lease",
      `FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=${TOKEN} reason=force-exit`,
      `FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${TOKEN}`,
      "FLINTTRADE_NOTIFY\tOrder filled\tRELIANCE BUY 10 @ 2900",
      "",
    ].join("\n"), "utf8"));

    expect(events).toEqual([
      { type: "application-pid", pid: 4321 },
      { type: "ready", port: 5100 },
      { type: "blocked", reason: "instance-lease" },
      { type: "pending-exit-ack", reason: "force-exit", token: TOKEN },
      { type: "cleanup-complete", token: TOKEN },
      { type: "notification", body: "RELIANCE BUY 10 @ 2900", title: "Order filled" },
    ]);
  });

  it("waits for a newline and preserves fragmented UTF-8", () => {
    const protocol = new GuardianProtocol();
    const encoded = Buffer.from("FLINTTRADE_NOTIFY\tExécution\tOrdre exécuté\n", "utf8");
    const split = encoded.indexOf(Buffer.from("é", "utf8")) + 1;

    expect(protocol.feed(encoded.subarray(0, split))).toEqual([]);
    expect(protocol.feed(encoded.subarray(split, encoded.length - 1))).toEqual([]);
    expect(protocol.feed(encoded.subarray(encoded.length - 1))).toEqual([
      { type: "notification", body: "Ordre exécuté", title: "Exécution" },
    ]);
    expect(protocol.rawTail).toContain("Exécution");
    expect(protocol.rawTail).not.toContain("�");
  });

  it("accepts a single CR before the newline without relaxing field syntax", () => {
    const protocol = new GuardianProtocol();
    expect(protocol.feed(Buffer.from("FLINTTRADE_BACKEND_READY port=5100\r\n"))).toEqual([
      { type: "ready", port: 5100 },
    ]);
    expect(protocol.feed(Buffer.from("FLINTTRADE_BACKEND_READY port=5100\rjunk\n"))).toEqual([]);
  });

  it.each([
    " FLINTTRADE_BACKEND_PID pid=1",
    "prefix FLINTTRADE_BACKEND_PID pid=1",
    "FLINTTRADE_BACKEND_PID pid=0",
    "FLINTTRADE_BACKEND_PID pid=01",
    "FLINTTRADE_BACKEND_PID pid=4294967296",
    "FLINTTRADE_BACKEND_PID pid=1 trailing",
    "FLINTTRADE_BACKEND_READY port=0",
    "FLINTTRADE_BACKEND_READY port=01",
    "FLINTTRADE_BACKEND_READY port=65536",
    "FLINTTRADE_BACKEND_READY port=5100 trailing",
    "FLINTTRADE_BACKEND_BLOCKED reason=",
    "FLINTTRADE_BACKEND_BLOCKED reason=Instance-Lease",
    "FLINTTRADE_BACKEND_BLOCKED reason=instance-lease trailing",
    `FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=${TOKEN} reason=unknown`,
    `FLINTTRADE_BACKEND_PENDING_EXIT_ACK token=${TOKEN} reason=force-exit trailing`,
    `FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${"a".repeat(63)}`,
    `FLINTTRADE_BACKEND_CLEANUP_COMPLETE token=${TOKEN} trailing`,
    "FLINTTRADE_NOTIFY\t\tbody",
    "FLINTTRADE_NOTIFY\ttitle",
    "FLINTTRADE_NOTIFY\ttitle\tbody\textra",
    "FLINTTRADE_NOTIFY title body",
  ])("rejects malformed or prefixed line %j", (line) => {
    expect(parseGuardianLine(line)).toBeNull();
  });

  it("retains an exact bounded UTF-8 raw tail", () => {
    const protocol = new GuardianProtocol({ maxRawTailBytes: 17 });
    protocol.feed(Buffer.from(`discard-${"π".repeat(20)}-tail\n`, "utf8"));

    expect(Buffer.byteLength(protocol.rawTail, "utf8")).toBeLessThanOrEqual(17);
    expect(protocol.rawTail).toMatch(/tail\n$/);
    expect(protocol.rawTail).not.toContain("�");
  });

  it("drops an oversized logical line without parsing a retained sentinel suffix", () => {
    const protocol = new GuardianProtocol({ maxLineBytes: 64, maxRawTailBytes: 128 });
    const oversized = `${"x".repeat(80)}FLINTTRADE_BACKEND_READY port=5100\n`;

    expect(protocol.feed(Buffer.from(oversized))).toEqual([]);
    expect(protocol.feed(Buffer.from("FLINTTRADE_BACKEND_READY port=5101\n"))).toEqual([
      { type: "ready", port: 5101 },
    ]);
  });
});
