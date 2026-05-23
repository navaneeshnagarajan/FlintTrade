import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import { NOTES_KEY } from "./utils";

export function NotesTab() {
  const today = new Date().toISOString().slice(0, 10);
  const key = `${NOTES_KEY}_${today}`;
  const [notes, setNotes] = useState(() => {
    try {
      return localStorage.getItem(key) ?? "";
    } catch {
      return "";
    }
  });

  const save = (val: string) => {
    setNotes(val);
    try {
      localStorage.setItem(key, val);
    } catch {
      // noop
    }
  };

  const wordCount = notes.trim() ? notes.trim().split(/\s+/).length : 0;

  return (
    <div className="flex flex-col gap-2 p-3 h-full">
      <div className="flex items-center justify-between">
        <span className="text-xs text-text-muted">Daily notes — {today}</span>
        <span className="text-xs text-text-muted">
          {wordCount} words · auto-saved
        </span>
      </div>
      <Textarea
        className="flex-1 text-sm leading-relaxed"
        placeholder={
          "Write your trading notes for today...\n\n- Market observations\n- Strategy notes\n- Lessons learned\n- Plan for tomorrow"
        }
        value={notes}
        onChange={(e) => save(e.target.value)}
      />
      {notes && (
        <Button
          variant="ghost"
          size="sm"
          className="self-end text-xs text-text-muted hover:text-loss h-6"
          onClick={() => save("")}
        >
          Clear
        </Button>
      )}
    </div>
  );
}
