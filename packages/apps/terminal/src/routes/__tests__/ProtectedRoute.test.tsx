import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUseAuthGuard = vi.fn();

vi.mock("@/hooks/useAuthGuard", () => ({
  useAuthGuard: () => mockUseAuthGuard(),
}));

import ProtectedRoute from "../ProtectedRoute";

describe("ProtectedRoute", () => {
  beforeEach(() => {
    mockUseAuthGuard.mockReset();
  });

  it("does not mount account-owning descendants while unauthenticated", () => {
    const accountRead = vi.fn();
    function AccountOwningLayout() {
      accountRead();
      return <div>Private layout</div>;
    }
    mockUseAuthGuard.mockReturnValue({ isAuthenticated: false, isLoading: false });

    render(
      <ProtectedRoute>
        <AccountOwningLayout />
      </ProtectedRoute>,
    );

    expect(accountRead).not.toHaveBeenCalled();
    expect(screen.queryByText("Private layout")).not.toBeInTheDocument();
  });

  it("mounts descendants only after authentication is established", () => {
    mockUseAuthGuard.mockReturnValue({ isAuthenticated: true, isLoading: false });

    render(<ProtectedRoute><div>Private layout</div></ProtectedRoute>);

    expect(screen.getByText("Private layout")).toBeInTheDocument();
  });
});
