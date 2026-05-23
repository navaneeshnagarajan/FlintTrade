export function interpolateColour(start: string, end: string, amount: number) {
  return amount <= 0 ? start : amount >= 1 ? end : `color-mix(in srgb, ${end} ${amount * 100}%, ${start})`
}
