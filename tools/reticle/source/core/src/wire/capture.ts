import { z } from 'zod';
import { ReticleEventSchema } from './messages.js';
import { URL_RAW } from './net.js';

/** Independent agent-facing capture streams; wire telemetry is never application evidence. */
export const CaptureStream = { LIVE: 'live', WIRE: 'wire' } as const;
export const WireReceiptKind = { APPLICATION: 'application', INSTRUMENTER: 'instrumenter' } as const;
export const CaptureProjection = { AGENT_SAFE: 'withoutUrlRaw' } as const;
export const CaptureSequenceSchema = z.number().int().min(0).max(99999);
const uint = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
export const CaptureScopeSchema = z.object({
  sessionId: z.string().min(1), incarnation: z.string().regex(/^[a-f0-9]{32}$/),
  documentId: ReticleEventSchema.shape.documentId.unwrap(), editEpoch: uint.optional(),
}).strict();
export type CaptureScope = z.infer<typeof CaptureScopeSchema>;
export const CaptureExportRequestSchema = z.object({
  through_seq: CaptureSequenceSchema.optional(), stream: z.literal(CaptureStream.WIRE).optional(),
  cursor: z.string().max(2048).optional(), max_bytes: z.number().int().min(256).max(1048576).optional(),
}).strict();
export type CaptureExportRequest = z.infer<typeof CaptureExportRequestSchema>;
export const CaptureRetentionSchema = z.object({
  maxEvents: z.number().int().min(1).max(100000), maxAgeMs: z.number().int().min(1).max(600000),
  maxBytes: z.number().int().min(1).max(67108864),
}).strict();
/** Validate without defaulting data or discarding unknown native fields. */
export const CaptureEventSchema = ReticleEventSchema.extend({
  t: uint, seq: CaptureSequenceSchema, data: z.record(z.unknown()),
}).passthrough();
export const AgentCaptureEventSchema = CaptureEventSchema.refine(
  event => !Object.hasOwn(event.data, URL_RAW), 'grader-only URL must stay private',
);
export const WireReceiptSchema = z.object({
  kind: z.nativeEnum(WireReceiptKind), receipt: uint, receivedAt: uint,
  event: AgentCaptureEventSchema,
}).passthrough();
export type WireReceipt = z.infer<typeof WireReceiptSchema>;
export const CapturePageSchema = z.object({
  id: z.string().regex(/^[a-f0-9]{32}$/), source: z.nativeEnum(CaptureStream), since: z.literal(0),
  until: uint, offset: uint, total: uint.max(100000), count: uint.max(2000), complete: z.boolean(),
  event_bytes: uint, dropped: uint, next_cursor: z.string().max(2048).optional(),
  through_seq: CaptureSequenceSchema.optional(), retention: CaptureRetentionSchema,
  scope: CaptureScopeSchema.optional(), projection: z.literal(CaptureProjection.AGENT_SAFE).optional(),
}).passthrough();
