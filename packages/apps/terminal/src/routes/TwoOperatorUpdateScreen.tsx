import { useNavigate } from "react-router";

import { Button } from "@/components/ui/button";
import {
  dispatchTwoOperatorGuide,
  twoOperatorGuideState,
} from "@/lib/twoOperatorGuide";

export const TWO_OPERATOR_SCREEN_TITLE = "FlintTrade couldn't finish updating";
export const TWO_OPERATOR_SCREEN_BODY =
  "This machine has two operator accounts, and FlintTrade supports one. Your data hasn't been changed. See Troubleshooting → Two operator accounts to choose which one to keep.";

/**
 * Paused-update screen. Retry re-checks status. Troubleshooting opens the
 * user-guide anchor. There is no delete control here.
 */
export default function TwoOperatorUpdateScreen({ onRetry }: { onRetry: () => void }) {
  const navigate = useNavigate();

  function openTroubleshooting(): void {
    dispatchTwoOperatorGuide();
    navigate("/learn", { state: twoOperatorGuideState() });
  }

  return (
    <main
      aria-labelledby="two-operator-title"
      className="flex min-h-screen items-center justify-center bg-surface-base px-4 py-10 text-text-primary"
    >
      <div className="w-full max-w-lg space-y-4 rounded-xl border border-border-default/70 bg-surface-card/70 p-6 shadow-2xl shadow-black/20 backdrop-blur-xl">
        <h1 id="two-operator-title" className="text-lg font-semibold text-text-primary">
          {TWO_OPERATOR_SCREEN_TITLE}
        </h1>
        <p className="text-sm text-text-secondary leading-relaxed">{TWO_OPERATOR_SCREEN_BODY}</p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button type="button" variant="outline" onClick={openTroubleshooting}>
            Open troubleshooting
          </Button>
          <Button type="button" onClick={onRetry}>
            Retry
          </Button>
        </div>
      </div>
    </main>
  );
}
