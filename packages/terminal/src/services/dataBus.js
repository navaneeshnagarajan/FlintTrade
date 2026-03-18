class DataBus {
  constructor() {
    this.subscriptions = new Map()
    this.cache = new Map()
  }

  subscribe(topic, callback) {
    if (!this.subscriptions.has(topic)) {
      this.subscriptions.set(topic, new Set())
    }
    this.subscriptions.get(topic).add(callback)
    // Immediately deliver cached value if available
    const cached = this.cache.get(topic)
    if (cached) callback(cached.data)
    return () => this.unsubscribe(topic, callback)
  }

  unsubscribe(topic, callback) {
    this.subscriptions.get(topic)?.delete(callback)
  }

  publish(topic, data) {
    this.cache.set(topic, { data, timestamp: Date.now() })
    this.subscriptions.get(topic)?.forEach(cb => {
      try { cb(data) } catch (e) { console.error(`DataBus error [${topic}]:`, e) }
    })
  }

  getLastValue(topic) {
    return this.cache.get(topic)?.data ?? null
  }

  getLastTimestamp(topic) {
    return this.cache.get(topic)?.timestamp ?? null
  }

  isStale(topic, maxAgeMs = 10000) {
    const ts = this.getLastTimestamp(topic)
    if (!ts) return true
    return Date.now() - ts > maxAgeMs
  }

  clear() {
    this.subscriptions.clear()
    this.cache.clear()
  }
}

// Singleton — all widgets share one DataBus
export const dataBus = new DataBus()
export { DataBus }
