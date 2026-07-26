/**
 * linux-containment-probe.test.ts — TEMPORARY DIAGNOSTIC.
 *
 * The containment sweep finds escaped descendants by matching a
 * FLINTTRADE_PROCESS_ANCHOR environment marker in `ps` output. That works on
 * macOS and does not on the Linux CI runner, and two attempts to fix it by
 * reasoning from macOS both regressed. This probe measures the runner
 * directly instead of guessing: it always passes and only reports.
 *
 * Delete once the containment fix lands.
 */

import { spawn, spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";

describe("linux containment probe", () => {
  it.runIf(process.platform === "linux")("reports how the runner exposes the anchor marker", async () => {
    const token = "probe-token-0123456789";
    const marker = `FLINTTRADE_PROCESS_ANCHOR=${token}`;

    // A detached child holding the marker, exactly like an escaped descendant.
    const child = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], {
      detached: true,
      env: { ...process.env, FLINTTRADE_PROCESS_ANCHOR: token },
      stdio: "ignore",
    });
    child.unref();
    const pid = child.pid;
    await new Promise((resolve) => setTimeout(resolve, 300));

    const report: string[] = [`child pid=${pid}`];

    // 1. Exactly what the script runs today.
    for (const flags of [["axeww"], ["-Eww", "-ax"]]) {
      const out = spawnSync("/bin/ps", [...flags, "-o", "pid=", "-o", "ppid=", "-o", "pgid=", "-o", "command="], { encoding: "utf8" });
      report.push(`ps ${flags.join(" ")} -o …command= : status=${out.status} markerFound=${(out.stdout ?? "").includes(marker)} bytes=${(out.stdout ?? "").length}`);
    }
    // 2. Same flags with no -o override, to isolate whether -o is the problem.
    for (const flags of [["axeww"], ["-Eww", "-ax"]]) {
      const out = spawnSync("/bin/ps", flags, { encoding: "utf8" });
      report.push(`ps ${flags.join(" ")} (default format)    : status=${out.status} markerFound=${(out.stdout ?? "").includes(marker)}`);
    }
    // 3. The /proc path the sweep now also uses.
    const environRead = spawnSync("/bin/sh", ["-c", `tr '\\0' '\\n' < /proc/${pid}/environ | grep -c -x -F -- '${marker}'`], { encoding: "utf8" });
    report.push(`/proc/<pid>/environ readable+exact-match count: ${(environRead.stdout ?? "").trim()} (status=${environRead.status})`);
    // 4. Are the helper binaries where the script looks for them?
    for (const helper of ["/usr/bin/tr", "/bin/tr", "/bin/grep", "/usr/bin/grep", "/bin/ps", "/usr/bin/ps"]) {
      const out = spawnSync("/bin/sh", ["-c", `[ -x '${helper}' ] && echo yes || echo no`], { encoding: "utf8" });
      report.push(`executable ${helper}: ${(out.stdout ?? "").trim()}`);
    }
    // 5. cgroup delegation, which the two reverted attempts depended on.
    const cg = spawnSync("/bin/sh", ["-c", "sed -n 's/^0:://p' /proc/self/cgroup 2>/dev/null; echo '---'; [ -w /sys/fs/cgroup ] && echo 'root writable' || echo 'root not writable'"], { encoding: "utf8" });
    report.push(`cgroup: ${(cg.stdout ?? "").trim().replace(/\n/g, " | ")}`);

    try { process.kill(pid!, "SIGKILL"); } catch { /* already gone */ }

    console.log(`\n===== CONTAINMENT PROBE =====\n${report.join("\n")}\n=============================\n`);
    expect(report.length).toBeGreaterThan(0);
  });
});
