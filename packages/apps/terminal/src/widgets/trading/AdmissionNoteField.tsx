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
