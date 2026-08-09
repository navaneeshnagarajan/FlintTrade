import type { Page, TestInfo, ConsoleMessage } from '@playwright/test'

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS'

export interface FixtureRegistry {
  register(method: HttpMethod, path: string, handler: (req?: any) => any | Promise<any>): void
  getCallCount(method: HttpMethod, path: string): number
}

interface RegisteredHandler {
  method: HttpMethod
  path: string
  handler: (req?: any) => any | Promise<any>
  callCount: number
}

export function createSyntheticFixtureRegistry(page: Page, testInfo: TestInfo): FixtureRegistry {
  const handlers = new Map<string, RegisteredHandler>()
  const keyFor = (method: HttpMethod, path: string) => `${method} ${path}`

  // Set up the single catch-all route that enforces exact match only (fail-closed, no catch-all success)
  page.route('**/*', async (route, request) => {
    const method = request.method() as HttpMethod
    const url = new URL(request.url())
    const path = url.pathname
    const key = keyFor(method, path)
    const registered = handlers.get(key)

    if (!registered) {
      // Fail immediately with evidence - unknown/unhandled request
      throw new Error(
        `[fail-closed] unhandled request: ${method} ${path} (no exact handler registered; method or path mismatch or unexpected)`
      )
    }

    // Check for overmatch is done at register time; here we assume single
    registered.callCount += 1
    try {
      const result = await registered.handler(request)
      const body = typeof result === 'string' ? result : JSON.stringify(result ?? {})
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body,
      })
    } catch (err) {
      // Propagate handler errors as test failure with evidence
      throw new Error(`[fail-closed] handler error for ${key}: ${err instanceof Error ? err.message : String(err)}`)
    }
  })

  const registry: FixtureRegistry = {
    register(method: HttpMethod, path: string, handler: (req?: any) => any | Promise<any>) {
      const key = keyFor(method, path)
      if (handlers.has(key)) {
        // Overmatched / duplicate registration fails at register time with evidence
        throw new Error(`[fail-closed] overmatched registration: ${key} already registered (duplicate handler)`)
      }
      handlers.set(key, { method, path, handler, callCount: 0 })
    },
    getCallCount(method: HttpMethod, path: string): number {
      const key = keyFor(method, path)
      return handlers.get(key)?.callCount ?? 0
    },
  }

  // Ensure cleanup on test end (though per-test context is fresh, explicit for isolation)
  testInfo.on('end', async () => {
    // Routes are auto-cleaned by Playwright per context, but we clear map for state isolation proof
    handlers.clear()
  })

  return registry
}

export interface ErrorCaptureOptions {
  allowConsole?: string[] // exact substring matches for benign messages only
}

export interface ErrorCapture {
  capture: {
    pageErrors: Error[]
    unhandledRejections: Error[]
    consoleErrors: string[]
  }
  assertClean: () => Promise<void>
}

/**
 * setupErrorCapture - captures pageerror, unhandledrejection, console errors.
 * assertClean fails the test if any unexpected (non-allowlisted) errors present.
 * Only explicit benign allowlist entries permit specific console messages.
 * No shared mutable state - fresh per call.
 */
export function setupErrorCapture(page: Page, options: ErrorCaptureOptions = {}): ErrorCapture {
  const capture = {
    pageErrors: [] as Error[],
    unhandledRejections: [] as Error[],
    consoleErrors: [] as string[],
  }

  const allowConsole = options.allowConsole ?? []

  const isBenign = (msg: string): boolean => {
    return allowConsole.some((allowed) => msg.includes(allowed))
  }

  page.on('pageerror', (err) => {
    capture.pageErrors.push(err)
  })

  page.on('crash', () => {
    capture.pageErrors.push(new Error('page crashed'))
  })

  // For unhandled rejections in page context
  page.on('console', (msg: ConsoleMessage) => {
    const text = msg.text()
    if (msg.type() === 'error' && !isBenign(text)) {
      capture.consoleErrors.push(text)
    } else if (msg.type() === 'warning' && !isBenign(text)) {
      // Treat non-allowlisted warnings as errors for strictness (fail-closed)
      capture.consoleErrors.push(`[warning] ${text}`)
    }
  })

  // Listen for unhandledrejection via evaluate or page context
  // Playwright does not have direct 'unhandledrejection' event on Page, so we inject a global catcher
  page.addInitScript(() => {
    window.addEventListener('unhandledrejection', (event) => {
      // Store in a global for later collection (since route/console is main path)
      ;(window as any).__unhandledRejections = (window as any).__unhandledRejections || []
      ;(window as any).__unhandledRejections.push(event.reason?.message || String(event.reason))
    })
  })

  const assertClean = async () => {
    // Collect any unhandled from page
    const unhandledFromPage = await page.evaluate(() => {
      const list = (window as any).__unhandledRejections || []
      ;(window as any).__unhandledRejections = []
      return list
    }).catch(() => [])

    capture.unhandledRejections.push(...unhandledFromPage.map((m: string) => new Error(m)))

    const errors: string[] = []
    if (capture.pageErrors.length > 0) {
      errors.push(`pageerror(s): ${capture.pageErrors.map((e) => e.message).join(', ')}`)
    }
    if (capture.unhandledRejections.length > 0) {
      errors.push(`unhandled rejection(s): ${capture.unhandledRejections.map((e) => e.message).join(', ')}`)
    }
    if (capture.consoleErrors.length > 0) {
      errors.push(`console error(s): ${capture.consoleErrors.join(' | ')}`)
    }

    if (errors.length > 0) {
      throw new Error(`[fail-closed] ${errors.join(' ; ')}`)
    }
  }

  return { capture, assertClean }
}
