import * as React from "react"

import { cn } from "../lib/utils"

export function Form({
  className,
  ...props
}: React.ComponentProps<"form">) {
  return <form className={cn("grid gap-4", className)} {...props} />
}
