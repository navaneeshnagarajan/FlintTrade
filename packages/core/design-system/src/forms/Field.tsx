import * as React from "react"

import { cn } from "../lib/utils"

export function Field({
  className,
  ...props
}: React.ComponentProps<"label">) {
  return (
    <label
      className={cn("grid gap-1.5 text-sm font-medium text-text-primary", className)}
      {...props}
    />
  )
}
