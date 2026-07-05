import type { Page } from "@playwright/test";

export async function seedExploreDemoSession(page: Page): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem("flinttrade:demo-session", "active");
    localStorage.setItem(
      "flinttrade:mode",
      JSON.stringify({ state: { mode: "explore" }, version: 2 }),
    );
    sessionStorage.setItem("flinttrade:dailyWelcomeDismissed", "true");
    localStorage.setItem("flinttrade:tourComplete", "true");
  });
}
