interface RateLimiterConfig {
  tokensPerSecond: number;
  bucketSize: number;
}

export class RateLimiter {
  private tokensPerSecond: number;
  private bucketSize: number;
  private tokens: number;
  private lastRefill: number;

  constructor({ tokensPerSecond, bucketSize }: RateLimiterConfig) {
    this.tokensPerSecond = tokensPerSecond;
    this.bucketSize = bucketSize;
    this.tokens = bucketSize;
    this.lastRefill = Date.now();
  }

  tryConsume(count = 1): boolean {
    this.refill();
    if (this.tokens >= count) {
      this.tokens -= count;
      return true;
    }
    return false;
  }

  private refill(): void {
    const now = Date.now();
    const elapsed = (now - this.lastRefill) / 1000;
    this.tokens = Math.min(this.bucketSize, this.tokens + elapsed * this.tokensPerSecond);
    this.lastRefill = now;
  }
}

export const orderLimiter = new RateLimiter({ tokensPerSecond: 10, bucketSize: 10 });
export const smartOrderLimiter = new RateLimiter({ tokensPerSecond: 2, bucketSize: 2 });
export const generalLimiter = new RateLimiter({ tokensPerSecond: 50, bucketSize: 50 });
