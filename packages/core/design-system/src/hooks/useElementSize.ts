import { useEffect, useRef, useState } from "react"

export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [size, setSize] = useState({ height: 0, width: 0 })

  useEffect(() => {
    if (!ref.current) {
      return
    }
    const observer = new ResizeObserver(([entry]) => {
      setSize({
        height: entry.contentRect.height,
        width: entry.contentRect.width,
      })
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])

  return [ref, size] as const
}
