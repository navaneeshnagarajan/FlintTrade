import {z} from '../node_modules/zod/index.js';
import {CaptureEventSchema,CapturePageSchema,CaptureExportRequestSchema,WireReceiptSchema,CaptureScopeSchema,CaptureSequenceSchema} from '../node_modules/@reticlehq/core/dist/index.js';
const uint=z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const loss=z.object({held:uint,dropped:uint,note:z.string()}).passthrough();
const health=z.object({throttled:z.boolean().optional(),versionSkew:z.string().optional()}).passthrough();
const nativeShape={buffer:loss.optional(),observationLost:z.boolean().optional(),inconclusive:z.string().optional(),session:health.optional()};
export const NativeVerdictSchema=z.object({verified:z.enum(['yes','no','unknown']),pass:z.boolean(),...nativeShape,capture_scope:CaptureScopeSchema.optional()}).passthrough();
const cost=z.object({events:uint,bytes:uint,droppedOldest:uint.optional()}).passthrough();
const request=z.object({action:z.literal('events'),since:z.literal(0),max_events:z.literal(2000),sessionId:z.string().optional(),export_page:CaptureExportRequestSchema}).passthrough();
const appEvent=CaptureEventSchema.omit({sessionId:true}).passthrough().refine(e=>!Object.hasOwn(e.data,'urlRaw'),'grader URL is private');
const response=z.object({capture:CapturePageSchema,events:z.array(appEvent),cost,summary:z.object({total:uint}).passthrough(),...nativeShape}).passthrough();
export const LivePagesSchema=z.array(z.object({request,response}).passthrough()).min(1).max(100000);
export const WirePagesSchema=z.array(z.object({request,response:response.extend({records:z.array(WireReceiptSchema)})}).passthrough()).min(1).max(100000);
export const CaptureEnvelopeSchema=z.object({
 pages:LivePagesSchema,wirePages:WirePagesSchema,verdict:NativeVerdictSchema,
 wire:z.array(CaptureEventSchema).min(1).max(100000),
 frames:z.array(z.object({socket:uint,index:uint,atMs:uint,payload:z.string()}).passthrough()).min(1).max(200000),
 capture:z.object({schema:z.literal('r88.capture.v1'),startedBeforeNavigation:z.boolean(),originalSince:z.literal(0),startedAtMs:uint,observedAtMs:uint,connectedSockets:uint,closedSockets:uint,socketErrors:uint,hellos:uint,sessionId:z.string().min(1),documentId:z.string().min(1),serverIncarnation:z.string().regex(/^[a-f0-9]{32}$/)}).passthrough(),
 otherSockets:z.array(z.string()).optional(),exportFailure:z.string().optional(),
}).passthrough();
const digest=z.string().regex(/^[a-f0-9]{64}$/);
export const SealSchema=z.object({schema:z.literal('r88.causal-seal.v1'),original:CaptureEnvelopeSchema,predicate:z.record(z.unknown()),originalSha256:digest,predicateSha256:digest,throughSeq:CaptureSequenceSchema,sealedAtMs:uint}).passthrough();
export const SealedCaptureSchema=z.object({seal:SealSchema,startedAtMs:uint,completedAtMs:uint,pages:LivePagesSchema,wirePages:WirePagesSchema,request:z.object({predicate:z.record(z.unknown()),since:z.literal(0),timeout_ms:z.literal(2000),sessionId:z.string(),capture_scope:CaptureScopeSchema}).strict(),freshVerdict:NativeVerdictSchema}).passthrough();
/** Boundary validation is not a projection: return the untouched native object. */
export function validateCaptureEnvelope<T>(value:T):T {CaptureEnvelopeSchema.parse(value);return value;}
