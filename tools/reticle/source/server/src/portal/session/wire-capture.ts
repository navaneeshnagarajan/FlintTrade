import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto';
import { EventType, CaptureSequenceSchema, CaptureStream, WireReceiptKind, CaptureProjection, WireReceiptSchema, type WireReceipt, type CaptureScope, type ReticleEvent } from '@reticlehq/core';
import { withoutUrlRaw } from '@reticlehq/engine/window/event-filters.js';
import type { CaptureRetention } from './capture-retention.js';
import type { ExportPage } from './capture-export.js';

/** A server receipt of accepted wire telemetry, NEVER an application observation. */
type PrivateReceipt = Pick<WireReceipt, 'kind' | 'receipt' | 'receivedAt'> & {event: ReticleEvent};
interface Cursor { incarnation: string; offset: number; total: number; until: number; expires: number; count: number; bytes: number; through?: number; }

/** Opt-in, bounded and fail-closed. No journal fallback and no evidence-facing accessors. */
export class WireCapture {
  #key = randomBytes(32);
  readonly #incarnation = randomBytes(16).toString('hex');
  readonly #records: PrivateReceipt[] = [];
  #bytes = 2;
  #lost = 0;
  #invalid = false;
  constructor(readonly retention: Readonly<CaptureRetention>) {}
  scope(sessionId: string): CaptureScope | undefined {
    if (this.#invalid || this.#lost) throw new Error('capture scope lifecycle changed or lost receipts');
    const first = this.#records[0]?.event;
    if (first?.documentId === undefined) return undefined;
    return {sessionId, incarnation: this.#incarnation, documentId: first.documentId,
      ...(first.editEpoch === undefined ? {} : {editEpoch: first.editEpoch})};
  }
  invalidate(): void { this.#invalid = true; }
  invalidateCursors(): void { this.#key = randomBytes(32); }
  hasThrough(seq: number): boolean {
    CaptureSequenceSchema.parse(seq);
    if (this.#invalid || this.#lost) throw new Error('wire capture lifecycle changed or lost receipts');
    if (this.#records.length <= seq) return false;
    if (this.#records.slice(0,seq+1).some((record,i)=>record.event.seq!==i)) throw new Error('wire receipt sequence discontinuity');
    return true;
  }
  receive(event: ReticleEvent, now: number): void {
    const record: PrivateReceipt = { kind: event.type === EventType.HUD_USED ? WireReceiptKind.INSTRUMENTER : WireReceiptKind.APPLICATION, receipt: this.#records.length, receivedAt: now, event };
    const serialised = JSON.stringify(record);
    const bytes = Buffer.byteLength(serialised) + (this.#records.length ? 1 : 0);
    const first = this.#records[0];
    if (first && (first.event.documentId !== event.documentId || first.event.editEpoch !== event.editEpoch || first.event.sessionId !== event.sessionId)) this.#invalid = true;
    if (this.#lost || this.#invalid || this.#records.length >= this.retention.maxEvents ||
        this.#bytes + bytes > this.retention.maxBytes || (first && now - first.receivedAt > this.retention.maxAgeMs)) {
      this.#lost = Math.min(Number.MAX_SAFE_INTEGER, this.#lost + 1);
      return;
    }
    // A copy, before normal Session processing can restamp or attribute it.
    this.#records.push(JSON.parse(serialised) as PrivateReceipt);
    this.#bytes += bytes;
  }
  #signature(body: string): Buffer { return createHmac('sha256', this.#key).update(body).digest(); }
  #encode(cursor: Cursor): string {
    const body = Buffer.from(JSON.stringify(cursor)).toString('base64url');
    return body + '.' + this.#signature(body).toString('base64url');
  }
  #decode(text: string): Cursor {
    if (text.length > 2048 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(text)) throw new Error('invalid wire cursor');
    const [body, signature] = text.split('.');
    if (!body || !signature) throw new Error('invalid wire cursor');
    const received = Buffer.from(signature, 'base64url'), expected = this.#signature(body);
    if (received.length !== expected.length || !timingSafeEqual(received, expected)) throw new Error('wire cursor identity/signature mismatch');
    return JSON.parse(Buffer.from(body, 'base64url').toString()) as Cursor;
  }
  page(now: number, open: boolean, count: number, request: ExportPage) {
    const through = request.through_seq;
    if (through !== undefined && !this.hasThrough(through)) throw new Error('wire receipt sequence not received');
    const bytes = request.max_bytes ?? 262144;
    if (!Number.isSafeInteger(count) || count < 1 || count > 2000 || !Number.isSafeInteger(bytes) || bytes < 256 || bytes > 1048576) throw new Error('invalid wire page budget');
    if (!open || this.#invalid) throw new Error('wire capture lifecycle ended/changed');
    if (this.#lost) throw new Error('wire capture lost records: ' + String(this.#lost));
    const first = this.#records[0];
    if (first && now - first.receivedAt > this.retention.maxAgeMs) throw new Error('wire capture exceeded age budget');
    const cursor: Cursor = request.cursor === undefined ? {incarnation:this.#incarnation, offset:0, total:through === undefined ? this.#records.length : through+1, until:now, expires:now+120000, count, bytes, ...(through === undefined ? {} : {through})} : this.#decode(request.cursor);
    if (cursor.incarnation !== this.#incarnation || cursor.total > this.#records.length || cursor.expires < now || cursor.count !== count || cursor.bytes !== bytes || cursor.through !== through) throw new Error('wire cursor expired/budget changed');
    const records: PrivateReceipt[] = [];let used = 2;
    for (let i=cursor.offset;i<cursor.total && records.length<count;i++) {
      const raw = this.#records[i];if (!raw) throw new Error('wire prefix missing');
      // Raw receipt custody stays private; budget precisely the established agent projection.
      const record = {...raw, event: withoutUrlRaw(raw.event) as ReticleEvent};
      WireReceiptSchema.parse(record); // Validate; return the exact projected JSON, not a parsed rewrite.
      const size = Buffer.byteLength(JSON.stringify(record)) + (records.length ? 1 : 0);
      if (used + size > bytes) { if (!records.length) throw new Error('wire record exceeds page budget'); break; }
      records.push(record);used+=size;
    }
    const offset = cursor.offset + records.length;
    return {records, capture:{id:cursor.incarnation,source:CaptureStream.WIRE,projection:CaptureProjection.AGENT_SAFE,since:0 as const,until:cursor.until,offset:cursor.offset,total:cursor.total,count:records.length,complete:offset===cursor.total,event_bytes:used,dropped:this.#lost,retention:this.retention,...(through === undefined ? {} : {through_seq:through}),...(offset<cursor.total?{next_cursor:this.#encode({...cursor,offset})}:{})}};
  }
}
