import { describe, it, expect, vi } from 'vitest'
import { DataBus } from '../dataBus'

describe('DataBus', () => {
  it('broadcasts data to all subscribers of a topic', () => {
    const bus = new DataBus()
    const cb1 = vi.fn()
    const cb2 = vi.fn()
    bus.subscribe('positions', cb1)
    bus.subscribe('positions', cb2)
    bus.publish('positions', [{ symbol: 'NIFTY' }])
    expect(cb1).toHaveBeenCalledWith([{ symbol: 'NIFTY' }])
    expect(cb2).toHaveBeenCalledWith([{ symbol: 'NIFTY' }])
  })

  it('does not broadcast to unsubscribed callbacks', () => {
    const bus = new DataBus()
    const cb = vi.fn()
    bus.subscribe('positions', cb)
    bus.unsubscribe('positions', cb)
    bus.publish('positions', [])
    expect(cb).not.toHaveBeenCalled()
  })

  it('caches last value per topic', () => {
    const bus = new DataBus()
    bus.publish('quotes:NIFTY', { ltp: 23581 })
    expect(bus.getLastValue('quotes:NIFTY')).toEqual({ ltp: 23581 })
  })

  it('returns null for topics with no data', () => {
    const bus = new DataBus()
    expect(bus.getLastValue('nonexistent')).toBeNull()
  })
})
