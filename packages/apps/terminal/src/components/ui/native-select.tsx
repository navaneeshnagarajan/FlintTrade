/**
 * native-select.tsx — the platform <select>, styled like the other inputs.
 *
 * Use it where the native control is the better choice: long option lists,
 * phone pickers, and forms whose options come from data. It keeps the
 * browser's own keyboard handling and accessible name.
 */

import * as React from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export interface NativeSelectProps extends React.ComponentProps<"select"> {
  /** `sm` is the 32 px toolbar height, `default` the 36 px form height. */
  controlSize?: "sm" | "default";
  /** Classes for the wrapper that positions the chevron. */
  wrapperClassName?: string;
}

function NativeSelect({
  className,
  wrapperClassName,
  controlSize = "default",
  children,
  ...props
}: NativeSelectProps) {
  return (
    <span
      data-slot="native-select-wrapper"
      className={cn("relative inline-flex min-w-0 max-w-full items-center", wrapperClassName)}
    >
      <select
        data-slot="native-select"
        className={cn(
          "w-full min-w-0 appearance-none truncate rounded-md border border-input bg-transparent pl-2.5 pr-8 text-text-primary shadow-xs outline-none transition-[color,box-shadow]",
          "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50",
          "disabled:cursor-not-allowed disabled:opacity-50 dark:bg-input/30",
          "aria-invalid:border-destructive",
          controlSize === "sm" ? "h-8 text-xs" : "h-9 text-sm",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-2.5 size-3.5 shrink-0 text-text-muted"
      />
    </span>
  );
}

export { NativeSelect };
