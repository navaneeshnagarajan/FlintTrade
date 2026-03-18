import { useState, useEffect, useCallback } from 'react'
import { dataBus } from '../services/dataBus'

export function useDataBus(topic) {
  const [data, setData] = useState(() => dataBus.getLastValue(topic))
  const [isStale, setIsStale] = useState(() => dataBus.isStale(topic))

  useEffect(() => {
    const unsubscribe = dataBus.subscribe(topic, (newData) => {
      setData(newData)
      setIsStale(false)
    })

    // Check staleness every 5s
    const interval = setInterval(() => {
      setIsStale(dataBus.isStale(topic))
    }, 5000)

    return () => {
      unsubscribe()
      clearInterval(interval)
    }
  }, [topic])

  const refresh = useCallback(() => {
    // Trigger a manual fetch — widgets call this, DataBus handles dedup
    dataBus.publish(`${topic}:refresh`, Date.now())
  }, [topic])

  return { data, isStale, refresh }
}
