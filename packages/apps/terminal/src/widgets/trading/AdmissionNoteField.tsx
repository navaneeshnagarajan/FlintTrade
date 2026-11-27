import { useEffect, useRef, useState } from "react";
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
 *
 * With `collapsible`, the field stays behind an "Add a reason (optional)" link
 * until the operator asks for it, so it adds no step before Place.
 */
export function AdmissionNoteField({
  id,
  value,
  onChange,
  collapsible = false,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  collapsible?: boolean;
}) {
  const hasNote = value.trim().length > 0;
  const [opened, setOpened] = useState(!collapsible || hasNote);
  const inputRef = useRef<HTMLInputElement>(null);
  const focusOnOpen = useRef(false);

  // A note that arrives while collapsed (a prefill) must never be sent unseen.
  if (!opened && hasNote) setOpened(true);

  useEffect(() => {
    if (opened && focusOnOpen.current) {
      focusOnOpen.current = false;
      inputRef.current?.focus();
    }
  }, [opened]);

  const handleChange = (next: string) => onChange(next.slice(0, ADMISSION_NOTE_MAX));

  if (!opened) {
    return (
      <Button
        type="button"
        variant="link"
        className="h-auto justify-start px-0 text-xs font-normal"
        onClick={() => {
          // The link unmounts on open; move focus to the field that replaces it.
          focusOnOpen.current = true;
          setOpened(true);
        }}
      >
        Add a reason (optional)
      </Button>
    );
  }

  if (collapsible) {
    return (
      <Input
        ref={inputRef}
        id={id}
        value={value}
        maxLength={ADMISSION_NOTE_MAX}
        aria-label="Add a reason (optional)"
        placeholder="Optional note for this order"
        onChange={(event) => handleChange(event.target.value)}
      />
    );
  }

  return (
    <Textarea
      id={id}
      value={value}
      maxLength={ADMISSION_NOTE_MAX}
      rows={2}
      aria-label="Add a reason (optional)"
      placeholder="Optional note for this order"
      onChange={(event) => handleChange(event.target.value)}
    />
  );
}
