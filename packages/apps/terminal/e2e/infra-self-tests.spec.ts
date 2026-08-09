import { test, expect } from '@playwright/test'

// Wished-for API for the shared fail-closed synthetic fixture registry
// Named, fresh-per-test, exact method+path handlers only.
// Unknown/unhandled/overmatched requests MUST fail test immediately with evidence.
// No catch-all success routes, no shared mutable state.
// Helpers must capture and assert zero pageerror, unhandledrejection, console errors (benign allowlist only).

import {
  createSyntheticFixtureRegistry,
  setupErrorCapture,
} from './fixture-registry'

test.describe('fail-closed synthetic fixture registry self-tests', () => {
  test('expected handler works for exact GET /api/status', async ({ page }) => {
    await page.goto('about:blank')
    const registry = createSyntheticFixtureRegistry(page, test.info())
    let called = false
    registry.register('GET', '/api/status', () => {
      called = true
      return { status: 'ok', version: 'e039' }
    })

    // Trigger via page context fetch (intercepted by page.route, no backend/network needed)
    const body = await page.evaluate(async () => {
      const res = await fetch('http://localhost:5173/api/status')
      if (!res.ok) throw new Error('fetch failed')
      return res.json()
    })
    expect(body.status).toBe('ok')
    expect(called).toBe(true)
    expect(registry.getCallCount('GET', '/api/status')).toBe(1)
  })

  test('method mismatch fails immediately with evidence', async ({ page }) => {
    await page.goto('about:blank')
    const registry = createSyntheticFixtureRegistry(page, test.info())
    registry.register('GET', '/api/status', () => ({ ok: true }))

    // Should fail because POST does not match registered GET - route throw fails test
    await expect(async () => {
      await page.evaluate(async () => {
        await fetch('http://localhost:5173/api/status', { method: 'POST', body: '{}' })
      })
    }).rejects.toThrow(/method mismatch|unhandled request|fail-closed/i)
  })

  test('path mismatch fails immediately with evidence', async ({ page }) => {
    await page.goto('about:blank')
    const registry = createSyntheticFixtureRegistry(page, test.info())
    registry.register('GET', '/api/status', () => ({ ok: true }))

    await expect(async () => {
      await page.evaluate(async () => {
        await fetch('http://localhost:5173/api/other')
      })
    }).rejects.toThrow(/path mismatch|unhandled request|fail-closed/i)
  })

  test('unexpected/unhandled request fails immediately with evidence', async ({ page }) => {
    await page.goto('about:blank')
    const registry = createSyntheticFixtureRegistry(page, test.info())
    // No handlers registered at all

    await expect(async () => {
      await page.evaluate(async () => {
        await fetch('http://localhost:5173/api/unexpected')
      })
    }).rejects.toThrow(/unhandled request|unknown request|fail-closed/i)
  })

  test('overmatched (duplicate registration) fails at register time with evidence', async ({ page }) => {
    await page.goto('about:blank')
    const registry = createSyntheticFixtureRegistry(page, test.info())
    registry.register('GET', '/api/status', () => ({ ok: true }))

    expect(() => {
      registry.register('GET', '/api/status', () => ({ ok: false }))
    }).toThrow(/overmatched|duplicate|already registered/i)
  })

  test('state isolation - two registries do not share state', async ({ page }) => {
    await page.goto('about:blank')
    const registry1 = createSyntheticFixtureRegistry(page, test.info())
    const registry2 = createSyntheticFixtureRegistry(page, test.info())

    registry1.register('GET', '/api/isolated', () => ({ from: 1 }))

    // registry2 should not know about it (callCount 0), and can register its own (fresh state)
    expect(registry2.getCallCount('GET', '/api/isolated')).toBe(0)
    expect(() => registry2.register('GET', '/api/isolated', () => ({ from: 2 }))).not.toThrow()
  })

  test('pageerror / unhandledrejection / console error fails the test (unless explicitly allowlisted benign)', async ({ page }) => {
    await page.goto('about:blank')
    const { assertClean } = setupErrorCapture(page, {
      allowConsole: ['[benign]'],
    })

    // Simulate a pageerror
    await page.evaluate(() => {
      throw new Error('simulated pageerror for RED test')
    })

    // The assert should fail
    await expect(async () => {
      await assertClean()
    }).rejects.toThrow(/pageerror|unhandled rejection|console error/i)
  })

  test('benign allowlist permits only explicit benign console messages', async ({ page }) => {
    await page.goto('about:blank')
    const { assertClean } = setupErrorCapture(page, {
      allowConsole: ['[allowed-benign-warning]'],
    })

    await page.evaluate(() => {
      console.warn('[allowed-benign-warning] this is ok')
      console.error('real error not allowed')
    })

    await expect(async () => {
      await assertClean()
    }).rejects.toThrow(/console error/i)
  })
})
