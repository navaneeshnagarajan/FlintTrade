/**
 * checkbox.tsx — the platform checkbox at one size, in the accent colour.
 *
 * It stays an <input type="checkbox">, so labels, forms and keyboard use
 * work as the browser defines them. The page's colour scheme (terminal.css)
 * gives it the dark or light box.
 */

import * as React from "react";

import { cn } from "@/lib/utils";

function Checkbox({ className, ...props }: Omit<React.ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      data-slot="checkbox"
      className={cn(
        "size-4 shrink-0 cursor-pointer rounded align-middle accent-accent",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}

export { Checkbox };
