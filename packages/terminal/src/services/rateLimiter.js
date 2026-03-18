export class RateLimiter {
  constructor({ tokensPerSecond, bucketSize }) {
    this.tokensPerSecond = tokensPerSecond
    this.bucketSize = bucketSize
    this.tokens = bucketSize
    this.lastRefill = Date.now()
  }

  tryConsume(count = 1) {
    this._refill()
    if (this.tokens >= count) {
      this.tokens -= count
      return true
    }
    return false
  }

  _refill() {
    const now = Date.now()
    const elapsed = (now - this.lastRefill) / 1000
    this.tokens = Math.min(this.bucketSize, this.tokens + elapsed * this.tokensPerSecond)
    this.lastRefill = now
  }
}

// Pre-configured limiters matching OpenAlgo rate limits
export const orderLimiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
export const smartOrderLimiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 })
export const generalLimiter = new RateLimiter({ tokensPerSecond: 50, bucketSize: 50 })
