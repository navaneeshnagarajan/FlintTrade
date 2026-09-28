import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** Matches the admission note length the place gate will accept. */
export const ADMISSION_NOTE_MAX = 4000;

export function admissionRationale(note: string): string {
  return note.trim().slice(0, ADMISSION_NOTE_MAX);
}

/**
 * Optional free-text note sent with a place. An empty note is a normal case:
 * the gate judges it, and this field does not block the button.
 */
export function AdmissionNoteField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <Textarea
      id={id}
      value={value}
      maxLength={ADMISSION_NOTE_MAX}
      rows={2}
      aria-label="Admission note"
      placeholder="Optional note for this order"
      onChange={(event) => onChange(event.target.value.slice(0, ADMISSION_NOTE_MAX))}
    />
  );
}

/**
 * Order Pad note. Collapsed until the operator asks for it. Empty is allowed
 * and does not add a step before Place.
 */
export function OrderPadReasonField({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(value.trim().length > 0);
  if (!open) {
    return (
      <Button
        type="button"
        variant="link"
        className="h-auto justify-start px-0 text-xs font-normal"
        onClick={() => setOpen(true)}
      >
        Add a reason (optional)
      </Button>
    );
  }
  return (
    <Input
      id={id}
      value={value}
      maxLength={ADMISSION_NOTE_MAX}
      aria-label="Admission note"
      placeholder="Optional note for this order"
      onChange={(event) => onChange(event.target.value.slice(0, ADMISSION_NOTE_MAX))}
    />
  );
}
