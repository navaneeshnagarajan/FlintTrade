import { fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const routeMocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  persistSetupChoices: vi.fn(() => "/trade"),
  llmChoice: {
    provider: "ollama",
    model: "qwen3:8b",
    host: "",
  },
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => routeMocks.navigate,
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    h2: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/motion", () => ({
  motionConfig: {
    prefersReducedMotion: () => true,
    duration: { fast: 0.1, normal: 0.2, slow: 0.3 },
    ease: { enter: [0, 0, 1, 1], exit: [0, 0, 1, 1] },
  },
}));

vi.mock("@/routes/setup/ModeSelection", () => ({
  ModeSelection: ({ onSelect }: { onSelect: (mode: "advanced") => void }) => (
    <button type="button" onClick={() => onSelect("advanced")}>Advanced</button>
  ),
}));

vi.mock("@/routes/setup/StepIndicator", () => ({
  StepIndicator: () => null,
}));

vi.mock("@/routes/setup/ConnectionStep", () => ({
  ConnectionStep: ({ onComplete }: { onComplete: (values: Record<string, string>) => void }) => (
    <button
      type="button"
      onClick={() => onComplete({
        host: "http://127.0.0.1:5100",
        port: "5100",
        apiKey: "direct-connect",
        wsPort: "8765",
      })}
    >
      Complete connection
    </button>
  ),
}));

vi.mock("@/routes/setup/PersonaStep", () => ({
  NameInput: () => null,
  PersonaPicker: ({ onSelect }: { onSelect: (value: "trader") => void }) => (
    <button type="button" onClick={() => onSelect("trader")}>Pick persona</button>
  ),
  ExperiencePicker: ({ onSelect }: { onSelect: (value: "intermediate") => void }) => (
    <button type="button" onClick={() => onSelect("intermediate")}>Pick experience</button>
  ),
  InterestPicker: ({ onToggle }: { onToggle: (value: string) => void }) => (
    <button type="button" onClick={() => onToggle("automation")}>Pick interest</button>
  ),
}));

vi.mock("@/routes/setup/TradingStep", () => ({
  TradingStep: ({ onComplete }: { onComplete: (values: Record<string, string | number>) => void }) => (
    <button
      type="button"
      onClick={() => onComplete({ defaultExchange: "NFO", defaultProduct: "MIS", defaultQty: 1 })}
    >
      Complete trading
    </button>
  ),
}));

vi.mock("@/routes/setup/RiskStep", () => ({
  RiskStep: ({ onComplete }: { onComplete: (values: Record<string, number>) => void }) => (
    <button
      type="button"
      onClick={() => onComplete({
        maxPositionLots: 1,
        mtmStoploss: 1_000,
        mtmTarget: 2_000,
        maxOrdersPerMinute: 10,
      })}
    >
      Complete risk
    </button>
  ),
}));

vi.mock("@/routes/setup/LlmStep", () => ({
  LlmStep: ({
    defaultValues,
    onComplete,
  }: {
    defaultValues?: { provider?: string; model?: string };
    onComplete: (values: { provider: string; model: string; host: string }) => void;
  }) => (
    <div>
      <span data-testid="saved-llm-provider">{defaultValues?.provider ?? "none"}</span>
      <span data-testid="saved-llm-model">{defaultValues?.model ?? "none"}</span>
      <button
        type="button"
        onClick={() => onComplete(routeMocks.llmChoice)}
      >
        Complete AI
      </button>
    </div>
  ),
}));

vi.mock("@/routes/setup/ReviewStep", () => ({
  LayoutPreview: () => null,
  DoneScreen: ({ onGo }: { onGo: () => void }) => (
    <button type="button" onClick={onGo}>Finish setup</button>
  ),
}));

vi.mock("@/routes/setup/applySetupChoices", () => ({
  persistSetupChoices: routeMocks.persistSetupChoices,
}));

import SetupRoute from "../../SetupRoute";

function reachAiStep() {
  fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick persona" }));
  fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
  fireEvent.click(screen.getByRole("button", { name: "Complete connection" }));
  fireEvent.click(screen.getByRole("button", { name: "Pick experience" }));
  fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
  fireEvent.click(screen.getByRole("button", { name: "Pick interest" }));
  fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
  fireEvent.click(screen.getByRole("button", { name: "Complete trading" }));
  fireEvent.click(screen.getByRole("button", { name: "Complete risk" }));
}

describe("SetupRoute LLM hand-off", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    routeMocks.persistSetupChoices.mockReturnValue("/trade");
    routeMocks.llmChoice = {
      provider: "ollama",
      model: "qwen3:8b",
      host: "",
    };
  });

  it("keeps the saved LLM choice and finishes in AI Settings for managed setup", () => {
    render(<SetupRoute />);
    reachAiStep();

    expect(screen.getByTestId("saved-llm-model")).toHaveTextContent("none");
    fireEvent.click(screen.getByRole("button", { name: "Complete AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByTestId("saved-llm-model")).toHaveTextContent("qwen3:8b");

    fireEvent.click(screen.getByRole("button", { name: "Complete AI" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fireEvent.click(screen.getByRole("button", { name: "Finish setup" }));

    expect(routeMocks.persistSetupChoices).toHaveBeenCalledTimes(1);
    expect(routeMocks.persistSetupChoices).toHaveBeenCalledWith(expect.objectContaining({
      llm: {
        provider: "ollama",
        model: "qwen3:8b",
        host: "",
      },
    }));
    expect(routeMocks.navigate).toHaveBeenCalledWith("/settings#llm");
  });

  it("finishes in authenticated AI Settings for cloud credentials too", () => {
    routeMocks.llmChoice = { provider: "grok", model: "grok-3-mini", host: "" };
    render(<SetupRoute />);
    reachAiStep();

    fireEvent.click(screen.getByRole("button", { name: "Complete AI" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue/i }));
    fireEvent.click(screen.getByRole("button", { name: "Finish setup" }));

    expect(routeMocks.persistSetupChoices).toHaveBeenCalledWith(expect.objectContaining({
      llm: { provider: "grok", model: "grok-3-mini", host: "" },
    }));
    expect(routeMocks.navigate).toHaveBeenCalledWith("/settings#llm");
  });

  it("preserves Claude Code OAuth when navigating back to the AI step", () => {
    routeMocks.llmChoice = {
      provider: "claude-code-oauth",
      model: "claude-3-5-haiku-20241022",
      host: "",
    };
    render(<SetupRoute />);
    reachAiStep();

    fireEvent.click(screen.getByRole("button", { name: "Complete AI" }));
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByTestId("saved-llm-provider")).toHaveTextContent("claude-code-oauth");
    expect(screen.getByTestId("saved-llm-model")).toHaveTextContent("claude-3-5-haiku-20241022");
  });
});
