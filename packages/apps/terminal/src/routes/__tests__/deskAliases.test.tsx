import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, Navigate, RouterProvider, useLocation } from "react-router";
import { DESK_ROUTE_ALIASES, PUBLIC_ENTRY_REDIRECTS, deskAliasTarget } from "../deskAliases";

function Landed() {
  const location = useLocation();
  return <div data-testid="landed">{`${location.pathname}${location.hash}`}</div>;
}

function renderAlias(path: string) {
  const router = createMemoryRouter(
    [
      ...DESK_ROUTE_ALIASES.map((alias) => ({
        path: alias.path,
        element: <Navigate to={alias.to} replace />,
      })),
      { path: "/trade", element: <Landed /> },
      { path: "/invest", element: <Landed /> },
      { path: "/settings", element: <Landed /> },
      { path: "/automate", element: <Landed /> },
      { path: "/learn", element: <Landed /> },
      { path: "*", element: <div>Page not found</div> },
    ],
    { initialEntries: [path] },
  );
  render(<RouterProvider router={router} />);
}

describe("public entry redirects", () => {
  it("sends /login to the sign-in screen", async () => {
    const router = createMemoryRouter(
      [
        ...PUBLIC_ENTRY_REDIRECTS.map((alias) => ({
          path: alias.path,
          element: <Navigate to={alias.to} replace />,
        })),
        { path: "/welcome", element: <Landed /> },
        { path: "*", element: <div>Page not found</div> },
      ],
      { initialEntries: ["/login"] },
    );
    render(<RouterProvider router={router} />);
    expect(await screen.findByTestId("landed")).toHaveTextContent("/welcome");
    expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
  });
});

describe("desk route aliases", () => {
  it("maps each retired path onto the screen that owns it", () => {
    expect(deskAliasTarget("/positions")).toBe("/trade#positions");
    expect(deskAliasTarget("/holdings")).toBe("/invest#holdings");
    expect(deskAliasTarget("/monitoring")).toBe("/settings#monitoring");
    expect(deskAliasTarget("/schedules")).toBe("/automate#schedules");
    expect(deskAliasTarget("/glossary")).toBe("/learn#glossary");
    expect(deskAliasTarget("/trade")).toBeNull();
  });

  it.each(DESK_ROUTE_ALIASES.map((alias) => [alias.path, alias.to] as const))(
    "/%s resolves to %s instead of a missing page",
    async (path, target) => {
      renderAlias(`/${path}`);
      expect(await screen.findByTestId("landed")).toHaveTextContent(target);
      expect(screen.queryByText("Page not found")).not.toBeInTheDocument();
    },
  );
});
