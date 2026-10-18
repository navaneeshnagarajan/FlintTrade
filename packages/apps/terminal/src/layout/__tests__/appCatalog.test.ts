import { expect, it } from 'vitest';
import { existsSync, writeFileSync } from 'node:fs';
import { APPS, APP_WIDGETS, appForPath } from '../appCatalog';
import { APP_PRESETS } from '../appLayouts';
import { widgetCatalog } from '../widgetFactory';
import { HOME_WIDGET_COMPONENTS } from '@/routes/home/homeWidgetRegistry';
it('retains every active widget and Home implementation in a purpose-specific app', () => {
  expect(new Set(APPS.map(app => app.id)).size).toBe(9);
  expect(new Set(APP_WIDGETS.map(widget => widget.id)).size).toBe(APP_WIDGETS.length);
  expect(APP_WIDGETS.find(widget => widget.id === 'observability')?.apps).toContain('system');
  expect(APP_WIDGETS.find(widget => widget.id === 'skill-drafts')?.apps).toContain('automation');
  for (const widget of widgetCatalog) expect(APP_WIDGETS.find(entry => entry.id === widget.id)?.apps.length, widget.id).toBeGreaterThan(0);
  for (const id of Object.keys(HOME_WIDGET_COMPONENTS)) expect(APP_WIDGETS.find(entry => entry.id === `overview:${id}`)?.apps.length, id).toBeGreaterThan(0);
  for (const route of ['/trade', '/home', '/invest', '/lab', '/automate', '/ai', '/learn', '/settings', '/ditto', '/admin']) expect(appForPath(route), route).toBeTruthy();
  // Optional artifact only; all correspondence assertions above always run.
  if (existsSync('/run/test/artifacts')) writeFileSync('/run/test/artifacts/r3-catalogue.json', JSON.stringify({ apps: APPS, widgets: APP_WIDGETS, presets: APP_PRESETS }, null, 2));
});
