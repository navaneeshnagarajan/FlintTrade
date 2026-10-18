import type { RouteObject } from "react-router";
import { createMemoryRouter, Outlet, RouterProvider, useLocation, useNavigationType } from "react-router";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";

// Capture the real Application route declarations at the browser-history seam;
// run their actual elements/redirects with public memory history. No duplicate
// redirect implementation or production export/test seam is introduced.
const captured = vi.hoisted(() => ({ routes: [] as RouteObject[], dispose: () => {} }));
vi.mock("react-router", async importOriginal => {
  const actual = await importOriginal<typeof import("react-router")>();
  return { ...actual, createBrowserRouter: (routes: RouteObject[]) => {
    captured.routes = routes;
    const router = actual.createMemoryRouter(routes, { initialEntries: ["/welcome"] });
    captured.dispose = () => router.dispose();
    return router;
  } };
});
vi.mock("@/routes/RootLayout", () => ({ default: () => <Outlet /> }));
vi.mock("@/routes/AppLayout", () => ({ default: () => <><RouteProbe /><Outlet /></> }));
vi.mock("@/routes/WelcomeRoute", () => ({ default: () => <h1>Welcome entry</h1> }));
import "@/Application";

function RouteProbe() {
  const location = useLocation();
  const action = useNavigationType();
  return <output aria-label="Application route">{JSON.stringify({
    path: location.pathname, search: location.search, hash: location.hash, state: location.state, action,
  })}</output>;
}
let activeRouter: ReturnType<typeof createMemoryRouter> | undefined;
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  useAuthStore.setState({ status: "logged-in", token: "synthetic-route-session", username: "synthetic" });
  useModeStore.setState({ mode: "practice" });
});
afterEach(() => { cleanup(); activeRouter?.dispose(); });
afterAll(() => captured.dispose());

const aliases = [
  { from: "/home", to: "/terminal" }, { from: "/trade", to: "/terminal" },
  { from: "/invest", to: "/portfolio" }, { from: "/lab", to: "/testing" },
  { from: "/automate", to: "/automation" }, { from: "/ditto", to: "/brokers" },
  { from: "/ai", to: "/automation", widgetId: "ai-centre" },
  { from: "/admin", to: "/system", widgetId: "system-console" },
  { from: "/admin/observability", to: "/system", widgetId: "observability" },
];
describe("Application compatibility navigation owner", () => {
  it.each(aliases)("replaces $from with $to preserving URL context and the intended state", async ({ from, to, widgetId }) => {
    const state = { source: "synthetic-history", selected: "A&B" };
    const search = "?symbol=A%26B&exchange=NSE&source=palette";
    const hash = "#details";
    activeRouter = createMemoryRouter(captured.routes, { initialEntries: ["/welcome", { pathname: from, search, hash, state }], initialIndex: 1 });
    render(<RouterProvider router={activeRouter} />);
    const expectedState = widgetId ? { openWidget: { widgetId } } : state;
    await waitFor(() => expect(screen.getByRole("status", { name: "Application route" })).toHaveTextContent(
      JSON.stringify({ path: to, search, hash, state: expectedState, action: "REPLACE" }),
    ));
    // Back must reach the entry before the alias, not return to the alias.
    await act(async () => { await activeRouter!.navigate(-1); });
    expect(await screen.findByRole("heading", { name: "Welcome entry" })).toBeInTheDocument();
    expect(activeRouter.state.location.pathname).toBe("/welcome");
    expect(useModeStore.getState().mode).toBe("practice");
    expect(useAuthStore.getState().token).toBe("synthetic-route-session");
  });

  it("does not mount the protected app for a logged-out alias visit", async () => {
    useAuthStore.setState({ status: "logged-out", token: null });
    activeRouter = createMemoryRouter(captured.routes, { initialEntries: ["/trade?symbol=RELIANCE#orders"] });
    render(<RouterProvider router={activeRouter} />);
    expect(screen.queryByRole("status", { name: "Application route" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Welcome entry" })).toBeInTheDocument();
    expect(activeRouter.state.location.pathname).toBe("/welcome");
  });
});
