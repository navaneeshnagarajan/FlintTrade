// Dev-only. Imported automatically by @reticlehq/vite-plugin, so you do not need to import it.
// Self-guards on import.meta.env.DEV, so it is a no-op in a production build.
import { registerCapabilities } from '@reticlehq/react';

if (import.meta.env.DEV) {
  // ── Start with ONE flow. ─────────────────────────────────────────────────────────────────────
  // You do not need to describe the whole app to get value, and trying to is the slow path. Register
  // the store your most important flow reads, and list the testids that flow touches. Add more later,
  // when a flow you actually replay needs them.
  //
  // Registering a store is the highest-value line in this file: it lets the agent check what the app
  // BELIEVES, not just what it rendered — the class of bug a screenshot cannot see. Pass the STORE,
  // not `() => store.getState()`: the store form wires `subscribe` too, so every mutation emits a
  // state diff; the getter form is read-only and silently produces empty diffs.
  // import your store, then: registerStore('app', useStore) // pass the store itself, not () => store.getState()
  // import your store, then: registerStore('app', jotaiStore(getDefaultStore(), { cart, user }))

  registerCapabilities({
    testids: ['active-indicator', 'auto-hide-strip', 'sidebar-settings-section', 'execution-mode', 'status-bar', 'status-bar-card-count', 'status-bar-layout-name', 'ticker-strip', 'ticker-marquee', 'topbar-more-row', 'topbar-more-root', 'topbar-more-sheet', 'market-session-status', 'fo-session-status', 'fullscreen-btn', 'avatar-btn', 'search-btn', 'topbar-v2', 'logo-link', 'topbar-more-btn', 'tools-btn', 'topbar-desk-tools-btn', 'workspace-switcher', 'notification-bell', 'account-switcher', 'logo-icon', 'location-probe', 'dialog', 'dialog-content', 'location', 'feed-freshness-chip', 'badge', 'native-connect-blockers', 'native-broker-sdk-status', 'native-broker-static-ip', 'rate-limits-panel', 'add-widget-card', 'inner', 'card', 'labelled-card', 'child-1', 'child-2', 'bento-grid-root', 'grid', 'container-child', 'spotlight-tour', 'spotlight-tour-card', 'tour-next', 'label', 'particles', 'inner-content', 'hero', 'content', 'child-a', 'child-b', 'action-btn', 'route-body-fill', 'trade-desk', 'widget-content', 'live-content'],
    signals: [], // names you pass to reticle.signal()
    stores: [], // the keys you registered above
  });
}
