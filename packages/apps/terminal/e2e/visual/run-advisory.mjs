import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const terminalDir = path.resolve(import.meta.dirname, "../..");
const updateBaselines = process.env.UPDATE_VISUAL_BASELINES === "1";
const gate = process.env.VISUAL_AXE_GATE === "1";

const args = [
  "exec",
  "playwright",
  "test",
  "--config=playwright.visual.config.ts",
  "--project=chromium",
  "--workers=1",
  "--retries=0",
];
if (updateBaselines) args.push("--update-snapshots");

const env = {
  ...process.env,
  CI: "true",
  VISUAL_AXE_ADVISORY: "1",
  UPDATE_AXE_SNAPSHOT: updateBaselines ? "1" : process.env.UPDATE_AXE_SNAPSHOT,
};

const result = spawnSync("pnpm", args, {
  cwd: terminalDir,
  env,
  stdio: "inherit",
});
const playwrightCode = result.status ?? 1;

const lines = [];
lines.push("## Visual and accessibility (advisory)");
lines.push("");
lines.push(gate
  ? "Gate is **on** (`VISUAL_AXE_GATE=1`). This job fails when Playwright fails."
  : "Gate is **off** (`VISUAL_AXE_GATE=0`). Diffs and new axe violations are reported here and the job stays green. Set that variable to `\"1\"` to make it a gate.");
lines.push("");

const notesPath = path.join(terminalDir, "e2e/visual/coverage-notes.json");
if (fs.existsSync(notesPath)) {
  const notes = JSON.parse(fs.readFileSync(notesPath, "utf8"));
  lines.push(`Sample data: ${notes.sampleData}.`);
  lines.push(`Dashboard: ${notes.dashboard}.`);
  lines.push(`Status menu: ${notes.statusMenu}.`);
  lines.push(`Laya chip labels rendered today: ${notes.layaRendered.join(", ")}.`);
  lines.push(`Not rendered, so not baselined: ${notes.layaNotRendered.join("; ")}.`);
  lines.push("");
}

const knownPath = path.join(terminalDir, "e2e/visual/known-axe-violations.json");
if (fs.existsSync(knownPath)) {
  const known = JSON.parse(fs.readFileSync(knownPath, "utf8"));
  lines.push("### Known axe violations");
  lines.push("");
  const screens = Object.keys(known).sort();
  if (screens.length === 0) {
    lines.push("No axe snapshot is committed yet.");
  } else {
    for (const screen of screens) {
      const violations = known[screen]?.violations ?? [];
      const counts = new Map();
      for (const violation of violations) {
        counts.set(violation.id, (counts.get(violation.id) ?? 0) + violation.targets.length);
      }
      const summary = counts.size === 0
        ? "none"
        : [...counts.entries()].map(([id, count]) => `${id} (${count})`).join(", ");
      lines.push(`- \`${screen}\`: ${summary}`);
    }
  }
  lines.push("");
}

const reportPath = path.join(terminalDir, "test-results/visual-a11y.json");
const failures = [];
if (fs.existsSync(reportPath)) {
  collectFailures(JSON.parse(fs.readFileSync(reportPath, "utf8")), failures);
} else {
  lines.push("Playwright did not write `test-results/visual-a11y.json`.");
  lines.push("");
}

lines.push("### Playwright result");
lines.push("");
lines.push(`Exit code ${playwrightCode}. ${failures.length} failing test(s).`);
lines.push("");
for (const failure of failures.slice(0, 40)) {
  lines.push(`- **${failure}**`);
}
if (failures.length > 40) lines.push(`- … ${failures.length - 40} more`);
lines.push("");

const diffs = [];
walk(path.join(terminalDir, "test-results"), diffs);
const pictures = diffs.filter((file) => file.endsWith(".png"));
lines.push(`Diff and actual images under test-results: ${pictures.length}.`);
lines.push("");

const summary = `${lines.join("\n")}\n`;
const summaryPath = process.env.GITHUB_STEP_SUMMARY;
if (summaryPath) fs.appendFileSync(summaryPath, summary);
process.stdout.write(`\n${summary}`);

// A manual baseline refresh must not commit partial screenshots. Ordinary
// advisory runs stay green until VISUAL_AXE_GATE is flipped.
if (gate || updateBaselines) process.exit(playwrightCode);
process.exit(0);

function collectFailures(node, found) {
  if (!node || typeof node !== "object") return;
  if (Array.isArray(node.specs)) {
    for (const spec of node.specs) {
      const tests = Array.isArray(spec.tests) ? spec.tests : [];
      for (const test of tests) {
        const results = Array.isArray(test.results) ? test.results : [];
        for (const result of results) {
          const failed = result.status === "unexpected"
            || result.status === "failed"
            || result.status === "timedOut"
            || result.status === "interrupted";
          if (failed) {
            const message = result.error?.message ?? result.status;
            const flat = String(message).replace(/\s+/g, " ").slice(0, 500);
            found.push(`${spec.title}: ${flat}`);
          }
        }
      }
    }
  }
  if (Array.isArray(node.suites)) {
    for (const suite of node.suites) collectFailures(suite, found);
  }
}

function walk(dir, found) {
  if (!fs.existsSync(dir)) return;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, found);
    else found.push(full);
  }
}
