import * as React from "react"

import { cn } from "../lib/utils"

export function FieldError({
  className,
  ...props
}: React.ComponentProps<"p">) {
  return (
    <p
      className={cn("text-xs text-loss", className)}
      role="alert"
      {...props}
    />
  )
}
