import type { ComponentProps } from "react";
import { cn } from "@/lib/utils";

type CheckboxProps = Omit<ComponentProps<"input">, "type">;

/** Two-state project primitive retaining native labels, forms and fieldset disabling. */
function Checkbox({ className, ...props }: CheckboxProps) {
  return (
    <input
      {...props}
      type="checkbox"
      data-slot="checkbox"
      className={cn(
        "size-4 shrink-0 rounded-sm accent-accent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        "focus-visible:ring-offset-2 focus-visible:ring-offset-surface-base",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
    />
  );
}

export { Checkbox };
