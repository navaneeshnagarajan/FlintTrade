import { describe, it, expect, vi, beforeEach } from 'vitest'
import { RateLimiter } from '../rateLimiter'

describe('RateLimiter', () => {
  it('allows requests within limit', () => {
    const limiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
    for (let i = 0; i < 10; i++) {
      expect(limiter.tryConsume()).toBe(true)
    }
  })

  it('rejects requests over limit', () => {
    const limiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 })
    expect(limiter.tryConsume()).toBe(true)
    expect(limiter.tryConsume()).toBe(true)
    expect(limiter.tryConsume()).toBe(false)
  })

  it('refills tokens over time', () => {
    vi.useFakeTimers()
    const limiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 })
    // Drain all tokens
    for (let i = 0; i < 10; i++) limiter.tryConsume()
    expect(limiter.tryConsume()).toBe(false)
    // Advance 500ms → should have ~5 tokens
    vi.advanceTimersByTime(500)
    expect(limiter.tryConsume()).toBe(true)
    vi.useRealTimers()
  })
})
