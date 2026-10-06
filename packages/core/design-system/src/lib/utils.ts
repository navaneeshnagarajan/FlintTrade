import { type ClassValue, clsx } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// text-xxs is a font size (10px). Without this group, tailwind-merge treats
// it as a text colour and drops it beside text-foreground or text-text-primary,
// so a Badge falls back to text-xs (12px).
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["xxs"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
