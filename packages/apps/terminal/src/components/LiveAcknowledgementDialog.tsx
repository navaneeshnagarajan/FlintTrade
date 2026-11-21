import { useEffect, useState } from "react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import {
  LIVE_ACK_CANCEL,
  LIVE_ACK_CHECKBOX,
  LIVE_ACK_CONFIRM,
  LIVE_ACK_TITLE,
  recordLiveAcknowledgement,
} from "@/lib/liveAcknowledgement";

interface LiveAcknowledgementDialogProps {
  /** Text to acknowledge; the dialog is closed when empty. */
  text: string;
  onCancel: () => void;
  onAccept: () => void;
}

/** "Turn on Live": one tick, then the usual PIN step. */
export function LiveAcknowledgementDialog({ text, onCancel, onAccept }: LiveAcknowledgementDialogProps) {
  const [ticked, setTicked] = useState(false);
  useEffect(() => {
    if (!text) setTicked(false);
  }, [text]);
  return (
    <AlertDialog open={text !== ""} onOpenChange={(open) => { if (!open) onCancel(); }}>
      <AlertDialogContent data-testid="live-acknowledgement">
        <AlertDialogHeader>
          <AlertDialogTitle>{LIVE_ACK_TITLE}</AlertDialogTitle>
          <AlertDialogDescription>{text}</AlertDialogDescription>
        </AlertDialogHeader>
        <label className="flex items-center gap-2 text-sm text-text-primary">
          <Checkbox
            checked={ticked}
            onChange={(event) => setTicked(event.target.checked)}
            data-testid="live-acknowledgement-checkbox"
          />
          {LIVE_ACK_CHECKBOX}
        </label>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={onCancel}>{LIVE_ACK_CANCEL}</AlertDialogCancel>
          <AlertDialogAction
            disabled={!ticked}
            onClick={(event) => {
              event.preventDefault();
              if (!ticked) return;
              recordLiveAcknowledgement(text);
              setTicked(false);
              onAccept();
            }}
            className="bg-profit hover:bg-profit/90 text-white"
          >
            {LIVE_ACK_CONFIRM}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
