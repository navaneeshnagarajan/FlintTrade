import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { CaptureSequenceSchema, CaptureStream, CaptureProjection, type CaptureExportRequest, type ReticleEvent } from '@reticlehq/core';
import { withoutUrlRaw } from '@reticlehq/engine/window/event-filters.js';
import type { CaptureRetention } from './capture-retention.js';

export type ExportPage = CaptureExportRequest;
interface Cursor {
  id: string; offset: number; total: number; until: number; expires: number;
  document: string | undefined; count: number; bytes: number;
  through?: number;
}
interface CaptureView {
  events: ReticleEvent[]; now: number; dropped: number; document: string | undefined;
  open: boolean; retention: Readonly<CaptureRetention>;
}
const PAGE_BYTES = 262144;
const MAX_PAGE_BYTES = 1048576;
const CURSOR_LIFETIME_MS = 120000;

/** No extra event journal or snapshot store. A signed immutable prefix is valid only while
 * the live buffer remains lossless and its session/document lifetime has not changed.
 * Appending does not change the prefix; any eviction refuses continuation, not a partial success.
 */
export class CaptureExport {
  #key = randomBytes(32);
  invalidate(): void { this.#key = randomBytes(32); }
  #sign(body: string): Buffer { return createHmac('sha256', this.#key).update(body).digest(); }
  #encode(cursor: Cursor): string {
    const body = Buffer.from(JSON.stringify(cursor)).toString('base64url');
    return `${body}.${this.#sign(body).toString('base64url')}`;
  }
  #decode(value: string): Cursor {
    if (value.length > 2048 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(value)) throw new Error('invalid capture cursor');
    const [body, signature] = value.split('.');
    if (!body || !signature) throw new Error('invalid capture cursor');
    const sig = Buffer.from(signature, 'base64url');
    const expected = this.#sign(body);
    if (sig.length !== expected.length || !timingSafeEqual(sig, expected)) throw new Error('capture cursor belongs to another session or was altered');
    return JSON.parse(Buffer.from(body, 'base64url').toString()) as Cursor;
  }
  page(view: CaptureView, count: number, request: ExportPage) {
    const through = request.through_seq;
    if (through !== undefined) CaptureSequenceSchema.parse(through);
    if (through !== undefined) {
      if (view.events.some(event => !Number.isSafeInteger(event.seq))) throw new Error('unsequenced application evidence in sealed capture');
      view = {...view, events:view.events.filter(event => event.seq !== undefined && event.seq <= through)};
    }
    const bytes = request.max_bytes ?? PAGE_BYTES;
    if (!Number.isSafeInteger(count) || count < 1 || count > 2000 || !Number.isSafeInteger(bytes) || bytes < 256 || bytes > MAX_PAGE_BYTES) throw new Error('invalid capture page budget');
    if (!view.open) throw new Error('capture session is not live');
    if (view.dropped !== 0) throw new Error('live capture lost events; journal recovery is not live retention');
    const first = view.events[0];
    if (first && first.t < view.now - view.retention.maxAgeMs) throw new Error('live capture exceeded age budget');
    const cursor: Cursor = request.cursor === undefined ? {
      id: randomBytes(16).toString('hex'), offset: 0, total: view.events.length,
      until: view.now, expires: view.now + CURSOR_LIFETIME_MS, document: view.document, count, bytes,
      ...(through === undefined ? {} : {through}),
    } : this.#decode(request.cursor);
    if (cursor.expires < view.now || cursor.document !== view.document || cursor.total > view.events.length || cursor.count !== count || cursor.bytes !== bytes || cursor.through !== through) throw new Error('capture cursor expired or window changed');
    const events: unknown[] = [];
    let used = 2;
    for (let i = cursor.offset; i < cursor.total && events.length < count; i++) {
      const source = view.events[i];
      if (source === undefined) throw new Error('capture prefix missing');
      const {sessionId: _sessionId, ...rest} = source;
      const event = withoutUrlRaw(rest);
      const size = Buffer.byteLength(JSON.stringify(event)) + (events.length ? 1 : 0);
      if (used + size > bytes) {
        if (!events.length) throw new Error('capture event exceeds page byte budget; no event was truncated');
        break;
      }
      used += size; events.push(event);
    }
    const offset = cursor.offset + events.length;
    return {events, capture: {
      id: cursor.id, source: CaptureStream.LIVE, projection: CaptureProjection.AGENT_SAFE, since: 0, until: cursor.until,
      offset: cursor.offset, total: cursor.total, count: events.length,
      complete: offset === cursor.total, event_bytes: used, dropped: view.dropped,
      retention: view.retention,
      ...(through === undefined ? {} : {through_seq:through}),
      ...(offset < cursor.total ? {next_cursor: this.#encode({...cursor, offset})} : {}),
    }};
  }
}
