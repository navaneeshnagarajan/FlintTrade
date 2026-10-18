// Read-only CDP logpoints. No source transform, query options or store writes.
export async function installDiscoveryProbe(page, cdp) {
  const events = [], locations = [], errors = [];
  const loadedScripts = new Set();
  cdp.on("Debugger.scriptParsed", event => loadedScripts.add(event.url));
  await page.addInitScript(() => {
    const ids = new WeakMap(), flights = new Map();
    let next = 0;
    Object.defineProperty(globalThis, '__r38DiscoveryObservation', { value: {
      record(discovery) {
        if (!ids.has(discovery)) { ids.set(discovery, ++next); flights.set(next, discovery); }
        const previousLimit = Error.stackTraceLimit;
        let stack;
        try { Error.stackTraceLimit = 80; stack = new Error('read-only discovery entry').stack; }
        finally { Error.stackTraceLimit = previousLimit; }
        const record = { id: ids.get(discovery), borrowersBefore: discovery.borrowers.size,
          stopped: discovery.stopped, aborted: discovery.controller.signal.aborted,
          url: location.href, time: performance.now(), stack };
        globalThis.__r38DiscoveryBinding(JSON.stringify(record));
      },
      snapshot: () => [...flights].map(([id, d]) => ({ id, borrowers: d.borrowers.size, stopped: d.stopped, aborted: d.controller.signal.aborted })),
    }, writable: false });
  });
  await cdp.send('Runtime.enable');
  await cdp.send('Runtime.addBinding', { name: '__r38DiscoveryBinding' });
  cdp.on('Runtime.bindingCalled', event => {
    if (event.name === '__r38DiscoveryBinding') events.push(JSON.parse(event.payload));
  });
  const installed = new Set();
  const instruction = await cdp.send('Debugger.setBreakpointByUrl', {
    lineNumber: 0, columnNumber: 0,
    urlRegex: String.raw`^http://127\.0\.0\.1:5173/(?:src/services/nativeAccountDiscovery\.ts(?:\?.*)?|assets/brokerAccountsApi-[^/]+\.js|owner\.js)$`,
  });
  cdp.on('Debugger.paused', async event => {
    try {
      if (!event.hitBreakpoints?.includes(instruction.breakpointId)) throw new Error('Unexpected debugger pause: ' + event.reason);
      const scriptId = event.callFrames[0].location.scriptId;
      if (!installed.has(scriptId)) {
        installed.add(scriptId);
        const { scriptSource: source } = await cdp.send('Debugger.getScriptSource', { scriptId });
        // This exact member belongs to the qualified R34 owner. It is present
        // in both normal emitted JS and Vite's development module.
        const matches = [...source.matchAll(/([\w$]+)\.borrowers\.add\(/g)];
        if (matches.length) {
          if (matches.length !== 1 || !source.includes('Native account discovery is unavailable or malformed.')) throw new Error('Ambiguous discovery owner');
          const match = matches[0];
          const pre = source.slice(0, match.index);
          const lineNumber = pre.split('\n').length - 1;
          const columnNumber = pre.length - pre.lastIndexOf('\n') - 1;
          const condition = `(globalThis.__r38DiscoveryObservation.record(${match[1]}), false)`;
          const breakpoint = await cdp.send('Debugger.setBreakpoint', { location: { scriptId, lineNumber, columnNumber }, condition });
          if (breakpoint.actualLocation.lineNumber !== lineNumber || breakpoint.actualLocation.columnNumber !== columnNumber) throw new Error('Logpoint moved from exact discovery add statement');
          locations.push({ scriptId, lineNumber, columnNumber, actualLocation: breakpoint.actualLocation, condition, ownerSource: source });
          await cdp.send('Debugger.removeBreakpoint', { breakpointId: instruction.breakpointId });
        }
      }
    } catch (error) { errors.push(String(error)); }
    finally { await cdp.send('Debugger.resume').catch(error => errors.push(String(error))); }
  });
  return {
    events, locations, errors,
    async flights() {
      return page.evaluate(() => globalThis.__r38DiscoveryObservation?.snapshot() ?? []);
    },
    async queries() {
      // Import only the already-loaded vendor module, never main/Application
      // or another QueryProvider instance. QueryClient's public heap instances
      // expose the mounted cache without assigning a global application getter.
      const result = await cdp.send('Runtime.evaluate', {
        expression: String.raw`(async () => {
          const path = ${JSON.stringify([...loadedScripts].find(p => /\/assets\/vendor-tanstack-[^/]+\.js$/.test(p)))};
          if (!path) return undefined;
          const module = await import(path);
          const owners = Object.values(module).filter(v => typeof v === 'function' && typeof v.prototype?.getQueryCache === 'function');
          if (owners.length !== 1) throw new Error('Expected exactly one loaded QueryClient class');
          return owners[0].prototype;
        })()`, awaitPromise: true, objectGroup: 'r38-query-read',
      });
      if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
      if (!result.result.objectId) return [];
      try {
        const objects = await cdp.send('Runtime.queryObjects', { prototypeObjectId: result.result.objectId, objectGroup: 'r38-query-read' });
        const snapshots = await cdp.send('Runtime.callFunctionOn', {
          objectId: objects.objects.objectId, returnByValue: true,
          functionDeclaration: `function() {
            return this.flatMap(client => client.getQueryCache().getAll().map(query => ({
              key: query.queryKey, status: query.state.status, fetchStatus: query.state.fetchStatus,
              failures: query.state.fetchFailureCount, observers: query.getObserversCount(), error: String(query.state.error)
            })));
          }`,
        });
        if (snapshots.exceptionDetails) throw new Error(JSON.stringify(snapshots.exceptionDetails));
        return snapshots.result.value;
      } finally { await cdp.send('Runtime.releaseObjectGroup', { objectGroup: 'r38-query-read' }); }
    },
  };
}
