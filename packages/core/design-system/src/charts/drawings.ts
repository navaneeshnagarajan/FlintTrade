export type FlintChartDrawingKind =
  | "hline"
  | "vline"
  | "trendline"
  | "ray"
  | "extended_line"
  | "parallel_channel"
  | "fib"
  | "fib_extension"
  | "long_position"
  | "short_position"
  | "rect"
  | "circle"
  | "brush"
  | "elliott_impulse"
  | "elliott_correction"
  | "measure"
  | "text"
  | "callout"
  | "price_label"

export type FlintChartDrawingLineStyle = "solid" | "dotted" | "dashed"
export type FlintChartDrawingLineWidth = 1 | 2 | 3 | 4

export interface FlintChartDrawingStyle {
  color: string
  lineWidth: FlintChartDrawingLineWidth
  lineStyle: FlintChartDrawingLineStyle
}

export type FlintChartDrawingStyleInput = Partial<FlintChartDrawingStyle>

export interface FlintChartDrawingState {
  hidden?: boolean
  locked?: boolean
}

export interface FlintChartDrawingPoint<TTime = unknown> {
  time: TTime
  price: number
}

export interface FlintChartHLineDrawing extends FlintChartDrawingState {
  kind: "hline"
  id: string
  price: number
  style?: FlintChartDrawingStyle
}

export interface FlintChartVLineDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "vline"
  id: string
  time: TTime
  style?: FlintChartDrawingStyle
}

export interface FlintChartTwoPointDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "trendline" | "ray" | "extended_line" | "fib" | "rect" | "circle" | "measure"
  id: string
  p1: FlintChartDrawingPoint<TTime>
  p2: FlintChartDrawingPoint<TTime>
  style?: FlintChartDrawingStyle
}

export interface FlintChartParallelChannelDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "parallel_channel"
  id: string
  p1: FlintChartDrawingPoint<TTime>
  p2: FlintChartDrawingPoint<TTime>
  p3: FlintChartDrawingPoint<TTime>
  style?: FlintChartDrawingStyle
}

export interface FlintChartFibExtensionDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "fib_extension"
  id: string
  p1: FlintChartDrawingPoint<TTime>
  p2: FlintChartDrawingPoint<TTime>
  p3: FlintChartDrawingPoint<TTime>
  style?: FlintChartDrawingStyle
}

export interface FlintChartPositionRiskDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "long_position" | "short_position"
  id: string
  p1: FlintChartDrawingPoint<TTime>
  p2: FlintChartDrawingPoint<TTime>
  p3: FlintChartDrawingPoint<TTime>
  style?: FlintChartDrawingStyle
}

export interface FlintChartElliottWaveDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "elliott_impulse" | "elliott_correction"
  id: string
  points: FlintChartDrawingPoint<TTime>[]
  style?: FlintChartDrawingStyle
}

export interface FlintChartBrushDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "brush"
  id: string
  points: FlintChartDrawingPoint<TTime>[]
  style?: FlintChartDrawingStyle
}

export interface FlintChartTextDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "text"
  id: string
  point: FlintChartDrawingPoint<TTime>
  label: string
  style?: FlintChartDrawingStyle
}

export interface FlintChartCalloutDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "callout"
  id: string
  point: FlintChartDrawingPoint<TTime>
  label: string
  style?: FlintChartDrawingStyle
}

export interface FlintChartPriceLabelDrawing<TTime = unknown> extends FlintChartDrawingState {
  kind: "price_label"
  id: string
  point: FlintChartDrawingPoint<TTime>
  style?: FlintChartDrawingStyle
}

export type FlintChartDrawing<TTime = unknown> =
  | FlintChartHLineDrawing
  | FlintChartVLineDrawing<TTime>
  | FlintChartTwoPointDrawing<TTime>
  | FlintChartParallelChannelDrawing<TTime>
  | FlintChartFibExtensionDrawing<TTime>
  | FlintChartPositionRiskDrawing<TTime>
  | FlintChartElliottWaveDrawing<TTime>
  | FlintChartBrushDrawing<TTime>
  | FlintChartTextDrawing<TTime>
  | FlintChartCalloutDrawing<TTime>
  | FlintChartPriceLabelDrawing<TTime>

export interface FlintChartLineDataPoint<TTime = unknown> {
  time: TTime
  value: number
}

export interface FlintChartPriceLineSpec {
  price: number
  color: string
  lineWidth: 1 | 2 | 3 | 4
  lineStyle: 0 | 1 | 2 | 3 | 4
  axisLabelVisible: boolean
  title: string
}

export interface FlintChartMarkerSpec<TTime = unknown> {
  time: TTime
  position: "aboveBar" | "belowBar" | "inBar" | "atPriceTop" | "atPriceBottom" | "atPriceMiddle"
  color: string
  shape: "circle" | "square" | "arrowUp" | "arrowDown"
  size: number
  text?: string
  price?: number
}

export interface FlintChartDrawingLineSeriesRenderSpec<TTime = unknown> {
  key: string
  drawingId: string
  options: FlintChartLineDrawingSeriesOptions
  data: FlintChartLineDataPoint<TTime>[]
}

export interface FlintChartDrawingPriceLineRenderSpec {
  key: string
  drawingId: string
  priceLine: FlintChartPriceLineSpec
}

export interface FlintChartDrawingRenderPlan<TTime = unknown> {
  lineSeries: FlintChartDrawingLineSeriesRenderSpec<TTime>[]
  priceLines: FlintChartDrawingPriceLineRenderSpec[]
  markers: FlintChartMarkerSpec<TTime>[]
}

export interface FlintChartDrawingRenderPlanPartDiff<TSpec> {
  added: TSpec[]
  updated: TSpec[]
  unchanged: TSpec[]
  removed: TSpec[]
}

export interface FlintChartDrawingRenderPlanDiff<TTime = unknown> {
  lineSeries: FlintChartDrawingRenderPlanPartDiff<FlintChartDrawingLineSeriesRenderSpec<TTime>>
  priceLines: FlintChartDrawingRenderPlanPartDiff<FlintChartDrawingPriceLineRenderSpec>
  markersChanged: boolean
  markers: FlintChartMarkerSpec<TTime>[]
}

export interface FlintChartLineDrawingSeriesOptions {
  color: string
  lineWidth: 1 | 2 | 3 | 4
  lineStyle: 0 | 1 | 2 | 3 | 4
  priceScaleId: string
  lastValueVisible: boolean
  priceLineVisible: boolean
}

export interface FlintChartDrawingEnvelope<TTime = unknown> {
  version: 1
  drawings: FlintChartDrawing<TTime>[]
}

export interface FlintChartDrawingSummary {
  id: string
  index: number
  kind: FlintChartDrawingKind
  label: string
  detail: string
  hidden: boolean
  locked: boolean
}

export interface FlintChartDrawingHitPoint<TTime = unknown> {
  time?: TTime
  price: number
}

export interface FlintChartDrawingHitOptions {
  priceTolerance?: number
  timeTolerance?: number
}

export interface FlintChartDrawingMoveDelta {
  priceDelta?: number
  timeDelta?: number
}

export type FlintChartDrawingHandleId = "p1" | "p2" | "p3"

export interface FlintChartDrawingHandleHit<TTime = unknown> {
  drawingId: string
  handle: FlintChartDrawingHandleId
  kind:
    | FlintChartTwoPointDrawing<TTime>["kind"]
    | FlintChartParallelChannelDrawing<TTime>["kind"]
    | FlintChartFibExtensionDrawing<TTime>["kind"]
    | FlintChartPositionRiskDrawing<TTime>["kind"]
  time: TTime
  price: number
}

export interface FlintChartDrawingStorageScope {
  symbol: string
  exchange: string
  workspaceId?: string
  prefix?: string
}

export type FlintChartDrawingDraftStatus =
  | "idle"
  | "pending"
  | "awaiting-text"
  | "created"
  | "unsupported"

export interface FlintChartDrawingDraftInput<TTime = unknown> {
  tool: string | null | undefined
  point: FlintChartDrawingPoint<TTime>
  pendingPoint?: FlintChartDrawingPoint<TTime> | null
  pendingPoints?: readonly FlintChartDrawingPoint<TTime>[]
  label?: string | null
  createId?: () => string
}

export interface FlintChartDrawingDraftResult<TTime = unknown> {
  status: FlintChartDrawingDraftStatus
  drawing: FlintChartDrawing<TTime> | null
  pendingPoint: FlintChartDrawingPoint<TTime> | null
  pendingPoints?: FlintChartDrawingPoint<TTime>[]
  awaitingText: FlintChartDrawingPoint<TTime> | null
}

export interface FlintChartVisibleLogicalRange {
  from: number
  to: number
}

export interface FlintChartViewState {
  symbol: string
  exchange: string
  interval: string
  visibleLogicalRange?: FlintChartVisibleLogicalRange
  updatedAt: number
}

export const FLINT_CHART_DRAWINGS_VERSION = 1
export const FLINT_CHART_DRAWINGS_STORAGE_PREFIX = "flinttrade:drawings"
export const FLINT_CHART_VIEW_STATE_STORAGE_KEY = "flinttrade:chart:view-state:v1"
export const FLINT_CHART_FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const
export const FLINT_CHART_FIB_EXTENSION_LEVELS = [0, 0.618, 1, 1.272, 1.618, 2.618] as const
export const FLINT_CHART_ELLIOTT_WAVE_LABELS = {
  elliott_impulse: ["0", "1", "2", "3", "4", "5"],
  elliott_correction: ["0", "A", "B", "C"],
} as const

export const FLINT_CHART_DRAWING_STYLE_COLORS = [
  { label: "blue", value: "#3b82f6" },
  { label: "teal", value: "#14b8a6" },
  { label: "green", value: "#22c55e" },
  { label: "amber", value: "#eab308" },
  { label: "orange", value: "#f97316" },
  { label: "red", value: "#ef4444" },
  { label: "violet", value: "#8b5cf6" },
  { label: "slate", value: "#64748b" },
] as const

export const FLINT_CHART_DRAWING_LINE_STYLES: readonly FlintChartDrawingLineStyle[] = [
  "solid",
  "dotted",
  "dashed",
]

export const FLINT_CHART_DRAWING_LINE_WIDTHS: readonly FlintChartDrawingLineWidth[] = [1, 2, 3, 4]

export const FLINT_CHART_FIB_COLORS: Record<(typeof FLINT_CHART_FIB_LEVELS)[number], string> = {
  0: "#ef4444",
  0.236: "#f97316",
  0.382: "#eab308",
  0.5: "#22c55e",
  0.618: "#3b82f6",
  0.786: "#a855f7",
  1: "#ef4444",
}

export const FLINT_CHART_FIB_EXTENSION_COLORS: Record<(typeof FLINT_CHART_FIB_EXTENSION_LEVELS)[number], string> = {
  0: "#38bdf8",
  0.618: "#22c55e",
  1: "#eab308",
  1.272: "#f97316",
  1.618: "#ef4444",
  2.618: "#a855f7",
}

const LINE_SOLID = 0
const LINE_DOTTED = 1
const LINE_DASHED = 2
const EXTENDED_LINE_EXTENSION_MULTIPLIER = 25
const CIRCLE_DRAWING_ARC_SAMPLES = 17
const TWO_POINT_DRAWING_KINDS = new Set<FlintChartTwoPointDrawing["kind"]>([
  "trendline",
  "ray",
  "extended_line",
  "fib",
  "rect",
  "circle",
  "measure",
])

const DEFAULT_DRAWING_STYLES: Record<FlintChartDrawingKind, FlintChartDrawingStyle> = {
  hline: { color: "#eab308", lineWidth: 1, lineStyle: "dashed" },
  vline: { color: "#64748b", lineWidth: 1, lineStyle: "dotted" },
  trendline: { color: "#3b82f6", lineWidth: 1, lineStyle: "solid" },
  ray: { color: "#f97316", lineWidth: 1, lineStyle: "solid" },
  extended_line: { color: "#60a5fa", lineWidth: 1, lineStyle: "solid" },
  parallel_channel: { color: "#38bdf8", lineWidth: 1, lineStyle: "solid" },
  fib: { color: "#38bdf8", lineWidth: 1, lineStyle: "dashed" },
  fib_extension: { color: "#22c55e", lineWidth: 1, lineStyle: "dashed" },
  long_position: { color: "#22c55e", lineWidth: 1, lineStyle: "dashed" },
  short_position: { color: "#ef4444", lineWidth: 1, lineStyle: "dashed" },
  rect: { color: "#8b5cf6", lineWidth: 1, lineStyle: "dotted" },
  circle: { color: "#06b6d4", lineWidth: 1, lineStyle: "solid" },
  brush: { color: "#f97316", lineWidth: 2, lineStyle: "solid" },
  elliott_impulse: { color: "#facc15", lineWidth: 1, lineStyle: "solid" },
  elliott_correction: { color: "#a855f7", lineWidth: 1, lineStyle: "solid" },
  measure: { color: "#22c55e", lineWidth: 1, lineStyle: "dotted" },
  text: { color: "#facc15", lineWidth: 1, lineStyle: "solid" },
  callout: { color: "#f97316", lineWidth: 1, lineStyle: "solid" },
  price_label: { color: "#38bdf8", lineWidth: 1, lineStyle: "solid" },
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function isTwoPointDrawingKind(value: string): value is FlintChartTwoPointDrawing["kind"] {
  return TWO_POINT_DRAWING_KINDS.has(value as FlintChartTwoPointDrawing["kind"])
}

function isTwoPointDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartTwoPointDrawing<TTime> {
  return isTwoPointDrawingKind(drawing.kind)
}

function isParallelChannelDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartParallelChannelDrawing<TTime> {
  return drawing.kind === "parallel_channel"
}

function isFibExtensionDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartFibExtensionDrawing<TTime> {
  return drawing.kind === "fib_extension"
}

function isPositionRiskDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartPositionRiskDrawing<TTime> {
  return drawing.kind === "long_position" || drawing.kind === "short_position"
}

function isElliottWaveKind(value: string): value is FlintChartElliottWaveDrawing["kind"] {
  return value === "elliott_impulse" || value === "elliott_correction"
}

function isElliottWaveDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartElliottWaveDrawing<TTime> {
  return isElliottWaveKind(drawing.kind)
}

function isBrushDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is FlintChartBrushDrawing<TTime> {
  return drawing.kind === "brush"
}

function isThreePointDrawing<TTime>(
  drawing: FlintChartDrawing<TTime>,
): drawing is
  | FlintChartParallelChannelDrawing<TTime>
  | FlintChartFibExtensionDrawing<TTime>
  | FlintChartPositionRiskDrawing<TTime> {
  return isParallelChannelDrawing(drawing) || isFibExtensionDrawing(drawing) || isPositionRiskDrawing(drawing)
}

export function getFlintChartElliottWaveLabels(kind: FlintChartElliottWaveDrawing["kind"]): readonly string[] {
  return FLINT_CHART_ELLIOTT_WAVE_LABELS[kind]
}

export function getFlintChartElliottWavePointCount(kind: FlintChartElliottWaveDrawing["kind"]): number {
  return getFlintChartElliottWaveLabels(kind).length
}

export function createFlintChartDrawingId(): string {
  const cryptoLike = globalThis.crypto as { randomUUID?: () => string } | undefined
  const uuid = cryptoLike?.randomUUID?.()
  return uuid ?? Math.random().toString(36).slice(2, 10)
}

function createDrawingDraftResult<TTime = unknown>(
  status: FlintChartDrawingDraftStatus,
  partial: Partial<Omit<FlintChartDrawingDraftResult<TTime>, "status">> = {},
): FlintChartDrawingDraftResult<TTime> {
  const result: FlintChartDrawingDraftResult<TTime> = {
    status,
    drawing: partial.drawing ?? null,
    pendingPoint: partial.pendingPoint ?? null,
    awaitingText: partial.awaitingText ?? null,
  }
  if (partial.pendingPoints) result.pendingPoints = [...partial.pendingPoints]
  return result
}

export function advanceFlintChartDrawingDraft<TTime = unknown>({
  tool,
  point,
  pendingPoint = null,
  pendingPoints,
  label,
  createId = createFlintChartDrawingId,
}: FlintChartDrawingDraftInput<TTime>): FlintChartDrawingDraftResult<TTime> {
  if (!tool || tool === "cursor" || tool === "eraser") {
    return createDrawingDraftResult("idle")
  }

  if (tool === "hline") {
    return createDrawingDraftResult("created", {
      drawing: { kind: "hline", id: createId(), price: point.price },
    })
  }

  if (tool === "vline") {
    return createDrawingDraftResult("created", {
      drawing: { kind: "vline", id: createId(), time: point.time },
    })
  }

  if (tool === "text") {
    const cleanLabel = label?.trim()
    if (cleanLabel) {
      return createDrawingDraftResult("created", {
        drawing: { kind: "text", id: createId(), point, label: cleanLabel },
      })
    }
    return createDrawingDraftResult("awaiting-text", { awaitingText: point })
  }

  if (tool === "callout") {
    const cleanLabel = label?.trim()
    if (cleanLabel) {
      return createDrawingDraftResult("created", {
        drawing: { kind: "callout", id: createId(), point, label: cleanLabel },
      })
    }
    return createDrawingDraftResult("awaiting-text", { awaitingText: point })
  }

  if (tool === "price_label") {
    return createDrawingDraftResult("created", {
      drawing: { kind: "price_label", id: createId(), point },
    })
  }

  if (isElliottWaveKind(tool)) {
    const points = pendingPoints?.length
      ? [...pendingPoints]
      : pendingPoint
        ? [pendingPoint]
        : []
    const pointCount = getFlintChartElliottWavePointCount(tool)

    if (points.length < pointCount - 1) {
      const nextPoints = [...points, point]
      return createDrawingDraftResult("pending", {
        pendingPoint: point,
        pendingPoints: nextPoints,
      })
    }

    return createDrawingDraftResult("created", {
      drawing: {
        kind: tool,
        id: createId(),
        points: [...points, point],
      },
      pendingPoints: [],
    })
  }

  if (
    tool === "parallel_channel" ||
    tool === "fib_extension" ||
    tool === "long_position" ||
    tool === "short_position"
  ) {
    const points = pendingPoints?.length
      ? [...pendingPoints]
      : pendingPoint
        ? [pendingPoint]
        : []

    if (points.length === 0) {
      return createDrawingDraftResult("pending", {
        pendingPoint: point,
        pendingPoints: [point],
      })
    }

    if (points.length === 1) {
      return createDrawingDraftResult("pending", {
        pendingPoint: point,
        pendingPoints: [points[0], point],
      })
    }

    return createDrawingDraftResult("created", {
      drawing: {
        kind: tool,
        id: createId(),
        p1: points[0],
        p2: points[1],
        p3: point,
      },
      pendingPoints: [],
    })
  }

  if (isTwoPointDrawingKind(tool)) {
    if (!pendingPoint) {
      return createDrawingDraftResult("pending", { pendingPoint: point })
    }
    return createDrawingDraftResult("created", {
      drawing: { kind: tool, id: createId(), p1: pendingPoint, p2: point },
    })
  }

  return createDrawingDraftResult("unsupported")
}

function formatDrawingPrice(value: number): string {
  return Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatSignedDrawingPrice(value: number): string {
  return `${value >= 0 ? "+" : ""}${Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function getMeasureBarDelta(from: unknown, to: unknown): number | null {
  const delta = getFlintChartTimeDelta(from, to)
  return delta !== null && Number.isFinite(delta) ? delta : null
}

export function getFlintChartMeasureLabel<TTime = unknown>(
  drawing: FlintChartTwoPointDrawing<TTime>,
): string {
  const priceDelta = drawing.p2.price - drawing.p1.price
  const percentDelta = drawing.p1.price === 0 ? null : (priceDelta / drawing.p1.price) * 100
  const barDelta = getMeasureBarDelta(drawing.p1.time, drawing.p2.time)
  const percentText = percentDelta === null ? "n/a" : `${percentDelta >= 0 ? "+" : ""}${percentDelta.toFixed(2)}%`
  const barText = barDelta === null ? "n/a bars" : `${Math.abs(barDelta)} bar${Math.abs(barDelta) === 1 ? "" : "s"}`

  return `${formatSignedDrawingPrice(priceDelta)} (${percentText}) / ${barText}`
}

function normaliseDrawingColor(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined
  const color = value.trim()
  return /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : undefined
}

function normaliseDrawingLineWidth(value: unknown): FlintChartDrawingLineWidth | undefined {
  return value === 1 || value === 2 || value === 3 || value === 4 ? value : undefined
}

function normaliseDrawingLineStyle(value: unknown): FlintChartDrawingLineStyle | undefined {
  return value === "solid" || value === "dotted" || value === "dashed" ? value : undefined
}

function normaliseDrawingStylePatch(value: unknown): FlintChartDrawingStyleInput | null {
  if (!isRecord(value)) return null
  const style: FlintChartDrawingStyleInput = {}
  const color = normaliseDrawingColor(value.color)
  const lineWidth = normaliseDrawingLineWidth(value.lineWidth)
  const lineStyle = normaliseDrawingLineStyle(value.lineStyle)

  if (color) style.color = color
  if (lineWidth) style.lineWidth = lineWidth
  if (lineStyle) style.lineStyle = lineStyle

  return Object.keys(style).length > 0 ? style : null
}

function normaliseDrawingStyle(
  value: unknown,
  kind: FlintChartDrawingKind,
): FlintChartDrawingStyle | undefined {
  const patch = normaliseDrawingStylePatch(value)
  return patch ? { ...DEFAULT_DRAWING_STYLES[kind], ...patch } : undefined
}

function normaliseDrawingState(value: Record<string, unknown>): FlintChartDrawingState {
  return {
    ...(value.hidden === true ? { hidden: true } : {}),
    ...(value.locked === true ? { locked: true } : {}),
  }
}

function normaliseVisibleLogicalRange(value: unknown): FlintChartVisibleLogicalRange | undefined {
  if (!isRecord(value) || !isFiniteNumber(value.from) || !isFiniteNumber(value.to)) {
    return undefined
  }
  if (value.to <= value.from) return undefined
  return { from: value.from, to: value.to }
}

function hasTime(value: unknown): boolean {
  return value !== null && value !== undefined
}

function timeToNumber(value: unknown): number | null {
  if (isFiniteNumber(value)) return value
  if (typeof value === "string") {
    const numeric = Number(value)
    if (Number.isFinite(numeric)) return numeric
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  if (
    isRecord(value) &&
    isFiniteNumber(value.year) &&
    isFiniteNumber(value.month) &&
    isFiniteNumber(value.day)
  ) {
    return Date.UTC(value.year, value.month - 1, value.day) / 86_400_000
  }
  return null
}

function timeDistance(a: unknown, b: unknown): number | null {
  if (a === b) return 0
  const aNumber = timeToNumber(a)
  const bNumber = timeToNumber(b)
  return aNumber !== null && bNumber !== null ? Math.abs(aNumber - bNumber) : null
}

function isTimeInsideRange(value: unknown, a: unknown, b: unknown, tolerance: number): boolean {
  const valueNumber = timeToNumber(value)
  const aNumber = timeToNumber(a)
  const bNumber = timeToNumber(b)
  if (valueNumber === null || aNumber === null || bNumber === null) return false
  return valueNumber >= Math.min(aNumber, bNumber) - tolerance &&
    valueNumber <= Math.max(aNumber, bNumber) + tolerance
}

function interpolatePriceAtTime<TTime>(
  p1: FlintChartDrawingPoint<TTime>,
  p2: FlintChartDrawingPoint<TTime>,
  time: TTime | undefined,
): number | null {
  if (!hasTime(time)) return null
  const x1 = timeToNumber(p1.time)
  const x2 = timeToNumber(p2.time)
  const x = timeToNumber(time)
  if (x1 === null || x2 === null || x === null || x1 === x2) return null
  const progress = (x - x1) / (x2 - x1)
  return p1.price + (p2.price - p1.price) * progress
}

function shiftTime<TTime>(time: TTime, timeDelta: number): TTime | null {
  if (!isFiniteNumber(timeDelta) || timeDelta === 0) return time
  if (typeof time === "number") return (time + timeDelta) as TTime
  if (typeof time === "string") {
    const numeric = Number(time)
    if (Number.isFinite(numeric)) return String(numeric + timeDelta) as TTime
    const parsed = Date.parse(time)
    if (!Number.isFinite(parsed)) return null
    const shifted = new Date(parsed + timeDelta).toISOString()
    return (/^\d{4}-\d{2}-\d{2}$/.test(time) ? shifted.slice(0, 10) : shifted) as TTime
  }
  if (
    isRecord(time) &&
    isFiniteNumber(time.year) &&
    isFiniteNumber(time.month) &&
    isFiniteNumber(time.day)
  ) {
    const shifted = new Date(Date.UTC(time.year, time.month - 1, time.day) + timeDelta * 86_400_000)
    return {
      year: shifted.getUTCFullYear(),
      month: shifted.getUTCMonth() + 1,
      day: shifted.getUTCDate(),
    } as TTime
  }
  return null
}

function isDrawingPoint<TTime>(value: unknown): value is FlintChartDrawingPoint<TTime> {
  return isRecord(value) && hasTime(value.time) && isFiniteNumber(value.price)
}

function normaliseDrawing<TTime>(value: unknown): FlintChartDrawing<TTime> | null {
  if (!isRecord(value) || !isNonEmptyString(value.id) || !isNonEmptyString(value.kind)) {
    return null
  }

  if (value.kind === "hline") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isFiniteNumber(value.price)
      ? { kind: "hline", id: value.id, price: value.price, ...normaliseDrawingState(value), ...(style ? { style } : {}) }
      : null
  }

  if (value.kind === "vline") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return hasTime(value.time)
      ? { kind: "vline", id: value.id, time: value.time as TTime, ...normaliseDrawingState(value), ...(style ? { style } : {}) }
      : null
  }

  if (isTwoPointDrawingKind(value.kind)) {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.p1) && isDrawingPoint<TTime>(value.p2)
      ? {
          kind: value.kind,
          id: value.id,
          p1: value.p1,
          p2: value.p2,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "parallel_channel") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.p1) &&
      isDrawingPoint<TTime>(value.p2) &&
      isDrawingPoint<TTime>(value.p3)
      ? {
          kind: "parallel_channel",
          id: value.id,
          p1: value.p1,
          p2: value.p2,
          p3: value.p3,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "fib_extension") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.p1) &&
      isDrawingPoint<TTime>(value.p2) &&
      isDrawingPoint<TTime>(value.p3)
      ? {
          kind: "fib_extension",
          id: value.id,
          p1: value.p1,
          p2: value.p2,
          p3: value.p3,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "long_position" || value.kind === "short_position") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.p1) &&
      isDrawingPoint<TTime>(value.p2) &&
      isDrawingPoint<TTime>(value.p3)
      ? {
          kind: value.kind,
          id: value.id,
          p1: value.p1,
          p2: value.p2,
          p3: value.p3,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (isElliottWaveKind(value.kind)) {
    const style = normaliseDrawingStyle(value.style, value.kind)
    const points = Array.isArray(value.points)
      ? value.points.filter((point): point is FlintChartDrawingPoint<TTime> => isDrawingPoint<TTime>(point))
      : []
    return points.length === getFlintChartElliottWavePointCount(value.kind)
      ? {
          kind: value.kind,
          id: value.id,
          points,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "brush") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    const points = Array.isArray(value.points)
      ? value.points.filter((point): point is FlintChartDrawingPoint<TTime> => isDrawingPoint<TTime>(point))
      : []
    return points.length >= 2
      ? {
          kind: "brush",
          id: value.id,
          points,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "text") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.point) && typeof value.label === "string"
      ? {
          kind: "text",
          id: value.id,
          point: value.point,
          label: value.label,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "callout") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.point) && typeof value.label === "string"
      ? {
          kind: "callout",
          id: value.id,
          point: value.point,
          label: value.label,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  if (value.kind === "price_label") {
    const style = normaliseDrawingStyle(value.style, value.kind)
    return isDrawingPoint<TTime>(value.point)
      ? {
          kind: "price_label",
          id: value.id,
          point: value.point,
          ...normaliseDrawingState(value),
          ...(style ? { style } : {}),
        }
      : null
  }

  return null
}

function parseJson(value: string | null): unknown {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

export function createFlintChartDrawingsStorageKey({
  symbol,
  exchange,
  workspaceId = "default",
  prefix = FLINT_CHART_DRAWINGS_STORAGE_PREFIX,
}: FlintChartDrawingStorageScope): string {
  const safeSymbol = encodeURIComponent(symbol.trim().toUpperCase())
  const safeExchange = encodeURIComponent(exchange.trim().toUpperCase())
  const safeWorkspace = encodeURIComponent(workspaceId.trim() || "default")
  if (safeWorkspace === "default") return `${prefix}:${safeSymbol}:${safeExchange}`
  return `${prefix}:${safeWorkspace}:${safeSymbol}:${safeExchange}`
}

export function parseFlintChartDrawings<TTime = unknown>(
  value: string | null | unknown,
): FlintChartDrawing<TTime>[] {
  const parsed = typeof value === "string" || value === null ? parseJson(value) : value
  const maybeDrawings =
    Array.isArray(parsed)
      ? parsed
      : isRecord(parsed) && Array.isArray(parsed.drawings)
        ? parsed.drawings
        : []

  return maybeDrawings
    .map((drawing) => normaliseDrawing<TTime>(drawing))
    .filter((drawing): drawing is FlintChartDrawing<TTime> => drawing !== null)
}

export function encodeFlintChartDrawings<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
): string {
  const envelope: FlintChartDrawingEnvelope<TTime> = {
    version: FLINT_CHART_DRAWINGS_VERSION,
    drawings: drawings.map((drawing) => ({ ...drawing })) as FlintChartDrawing<TTime>[],
  }
  return JSON.stringify(envelope)
}

export function getFlintChartDrawingLineStyleCode(
  lineStyle: FlintChartDrawingLineStyle,
): 0 | 1 | 2 {
  if (lineStyle === "dotted") return LINE_DOTTED
  if (lineStyle === "dashed") return LINE_DASHED
  return LINE_SOLID
}

export function createFlintChartDefaultDrawingStyle(
  kind: FlintChartDrawingKind,
): FlintChartDrawingStyle {
  return { ...DEFAULT_DRAWING_STYLES[kind] }
}

export function getFlintChartDrawingStyle<TTime = unknown>(
  drawing: FlintChartDrawing<TTime>,
): FlintChartDrawingStyle {
  return drawing.style ?? createFlintChartDefaultDrawingStyle(drawing.kind)
}

export function getFlintChartDrawingLabel<TTime = unknown>(
  drawing: FlintChartDrawing<TTime>,
): string {
  switch (drawing.kind) {
    case "hline":
      return `Horizontal Line ${formatDrawingPrice(drawing.price)}`
    case "vline":
      return "Vertical Line"
    case "trendline":
      return "Trend Line"
    case "ray":
      return "Ray"
    case "extended_line":
      return "Extended Line"
    case "parallel_channel":
      return "Parallel Channel"
    case "fib":
      return "Fib Retracement"
    case "fib_extension":
      return "Fib Extension"
    case "long_position":
      return "Long Position"
    case "short_position":
      return "Short Position"
    case "rect":
      return "Rectangle"
    case "circle":
      return "Circle"
    case "brush":
      return "Brush"
    case "elliott_impulse":
      return "Elliott Impulse"
    case "elliott_correction":
      return "Elliott Correction"
    case "measure":
      return "Measure"
    case "text":
      return drawing.label.trim() ? `Text: ${drawing.label.trim()}` : "Text"
    case "callout":
      return drawing.label.trim() ? `Callout: ${drawing.label.trim()}` : "Callout"
    case "price_label":
      return `Price Label ${formatDrawingPrice(drawing.point.price)}`
  }
}

export function getFlintChartDrawingDetail<TTime = unknown>(
  drawing: FlintChartDrawing<TTime>,
): string {
  if (drawing.kind === "hline") return `Price ${formatDrawingPrice(drawing.price)}`
  if (drawing.kind === "vline") return `Time ${String(drawing.time)}`
  if (drawing.kind === "text") return `Price ${formatDrawingPrice(drawing.point.price)}`
  if (drawing.kind === "callout") return `Price ${formatDrawingPrice(drawing.point.price)}`
  if (drawing.kind === "price_label") return `Price ${formatDrawingPrice(drawing.point.price)}`
  if (drawing.kind === "measure") return getFlintChartMeasureLabel(drawing)
  if (drawing.kind === "parallel_channel") {
    return `${formatDrawingPrice(drawing.p1.price)} -> ${formatDrawingPrice(drawing.p2.price)} / ${formatDrawingPrice(drawing.p3.price)}`
  }
  if (drawing.kind === "fib_extension") {
    return `${formatDrawingPrice(drawing.p1.price)} -> ${formatDrawingPrice(drawing.p2.price)} from ${formatDrawingPrice(drawing.p3.price)}`
  }
  if (drawing.kind === "long_position" || drawing.kind === "short_position") {
    const reward = drawing.kind === "long_position"
      ? drawing.p2.price - drawing.p1.price
      : drawing.p1.price - drawing.p2.price
    const risk = drawing.kind === "long_position"
      ? drawing.p1.price - drawing.p3.price
      : drawing.p3.price - drawing.p1.price
    const ratio = risk > 0 ? reward / risk : null
    const ratioText = ratio !== null && Number.isFinite(ratio) ? ratio.toFixed(2) : "n/a"
    return `Target ${formatDrawingPrice(drawing.p2.price)} / Stop ${formatDrawingPrice(drawing.p3.price)} / R:R ${ratioText}`
  }
  if (isElliottWaveDrawing(drawing)) {
    const first = drawing.points[0]
    const last = drawing.points.at(-1)
    if (!first || !last) return `${drawing.points.length} waves`
    return `${formatDrawingPrice(first.price)} -> ${formatDrawingPrice(last.price)} / ${drawing.points.length} waves`
  }
  if (isBrushDrawing(drawing)) {
    return `${drawing.points.length} points`
  }

  return `${formatDrawingPrice(drawing.p1.price)} -> ${formatDrawingPrice(drawing.p2.price)}`
}

export function createFlintChartDrawingSummaries<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
): FlintChartDrawingSummary[] {
  return drawings.map((drawing, index) => ({
    id: drawing.id,
    index,
    kind: drawing.kind,
    label: getFlintChartDrawingLabel(drawing),
    detail: getFlintChartDrawingDetail(drawing),
    hidden: drawing.hidden === true,
    locked: drawing.locked === true,
  }))
}

export function getFlintChartSelectedDrawing<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  selectedDrawingId: string | null | undefined,
): FlintChartDrawing<TTime> | null {
  if (!selectedDrawingId) return null
  return drawings.find((drawing) => drawing.id === selectedDrawingId) ?? null
}

export function removeFlintChartDrawingById<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
): FlintChartDrawing<TTime>[] {
  const target = drawingId ? drawings.find((drawing) => drawing.id === drawingId) : undefined
  if (!target || target.locked === true) {
    return drawings as FlintChartDrawing<TTime>[]
  }
  return drawings.filter((drawing) => drawing.id !== drawingId)
}

export function getFlintChartVisibleDrawings<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
): FlintChartDrawing<TTime>[] {
  return drawings.filter((drawing) => drawing.hidden !== true)
}

function updateDrawingState<TTime = unknown>(
  drawing: FlintChartDrawing<TTime>,
  state: FlintChartDrawingState,
): FlintChartDrawing<TTime> {
  const next = { ...drawing } as FlintChartDrawing<TTime>
  if (state.hidden === true) {
    next.hidden = true
  } else if (state.hidden === false) {
    delete next.hidden
  }
  if (state.locked === true) {
    next.locked = true
  } else if (state.locked === false) {
    delete next.locked
  }
  return next
}

export function updateFlintChartDrawingsHidden<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  hidden: boolean,
): FlintChartDrawing<TTime>[] {
  if (drawings.every((drawing) => (drawing.hidden === true) === hidden)) {
    return drawings as FlintChartDrawing<TTime>[]
  }
  return drawings.map((drawing) => updateDrawingState(drawing, { hidden }))
}

export function updateFlintChartDrawingsLocked<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  locked: boolean,
): FlintChartDrawing<TTime>[] {
  if (drawings.every((drawing) => (drawing.locked === true) === locked)) {
    return drawings as FlintChartDrawing<TTime>[]
  }
  return drawings.map((drawing) => updateDrawingState(drawing, { locked }))
}

export function updateFlintChartDrawingStateById<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  state: FlintChartDrawingState,
): FlintChartDrawing<TTime>[] {
  const target = drawingId ? drawings.find((drawing) => drawing.id === drawingId) : undefined
  if (!target || (state.hidden === undefined && state.locked === undefined)) {
    return drawings as FlintChartDrawing<TTime>[]
  }
  const nextTarget = updateDrawingState(target, state)
  if (
    (target.hidden === true) === (nextTarget.hidden === true) &&
    (target.locked === true) === (nextTarget.locked === true)
  ) {
    return drawings as FlintChartDrawing<TTime>[]
  }
  return drawings.map((drawing) =>
    drawing.id === drawingId ? nextTarget : drawing,
  )
}

export function removeFlintChartUnlockedDrawings<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
): FlintChartDrawing<TTime>[] {
  const next = drawings.filter((drawing) => drawing.locked === true)
  return next.length === drawings.length ? drawings as FlintChartDrawing<TTime>[] : next
}

export function updateFlintChartDrawingStyle<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  styleInput: FlintChartDrawingStyleInput,
): FlintChartDrawing<TTime>[] {
  const target = drawingId ? drawings.find((drawing) => drawing.id === drawingId) : undefined
  if (!target || target.locked === true) {
    return drawings as FlintChartDrawing<TTime>[]
  }

  return drawings.map((drawing) => {
    if (drawing.id !== drawingId) return drawing
    const nextStyle = {
      ...getFlintChartDrawingStyle(drawing),
      ...normaliseDrawingStylePatch(styleInput),
    }
    return { ...drawing, style: nextStyle } as FlintChartDrawing<TTime>
  })
}

export function getFlintChartTimeDelta(from: unknown, to: unknown): number | null {
  const fromNumber = timeToNumber(from)
  const toNumber = timeToNumber(to)
  return fromNumber !== null && toNumber !== null ? toNumber - fromNumber : null
}

export function moveFlintChartDrawingByDelta<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  delta: FlintChartDrawingMoveDelta,
): FlintChartDrawing<TTime>[] {
  const target = drawingId ? drawings.find((drawing) => drawing.id === drawingId) : undefined
  const priceDelta = isFiniteNumber(delta.priceDelta) ? delta.priceDelta : 0
  const timeDelta = isFiniteNumber(delta.timeDelta) ? delta.timeDelta : 0
  if (!target || target.locked === true || (priceDelta === 0 && timeDelta === 0)) {
    return drawings as FlintChartDrawing<TTime>[]
  }

  if (target.kind === "hline" && priceDelta === 0) {
    return drawings as FlintChartDrawing<TTime>[]
  }

  return drawings.map((drawing) => {
    if (drawing.id !== drawingId) return drawing

    if (drawing.kind === "hline") {
      return { ...drawing, price: drawing.price + priceDelta }
    }

    if (drawing.kind === "vline") {
      if (timeDelta === 0) return drawing
      const time = shiftTime(drawing.time, timeDelta)
      return time === null ? drawing : { ...drawing, time }
    }

    if (drawing.kind === "text" || drawing.kind === "callout" || drawing.kind === "price_label") {
      const time = timeDelta === 0 ? drawing.point.time : shiftTime(drawing.point.time, timeDelta)
      if (time === null && priceDelta === 0) return drawing
      return {
        ...drawing,
        point: {
          ...drawing.point,
          ...(time !== null ? { time } : {}),
          price: drawing.point.price + priceDelta,
        },
      }
    }

    if (isElliottWaveDrawing(drawing) || isBrushDrawing(drawing)) {
      const shiftedPoints = drawing.points.map((point) => {
        const time = timeDelta === 0 ? point.time : shiftTime(point.time, timeDelta)
        return {
          ...point,
          ...(time !== null ? { time } : {}),
          price: point.price + priceDelta,
        }
      })
      return {
        ...drawing,
        points: shiftedPoints,
      }
    }

    if (isThreePointDrawing(drawing)) {
      const p1Time = timeDelta === 0 ? drawing.p1.time : shiftTime(drawing.p1.time, timeDelta)
      const p2Time = timeDelta === 0 ? drawing.p2.time : shiftTime(drawing.p2.time, timeDelta)
      const p3Time = timeDelta === 0 ? drawing.p3.time : shiftTime(drawing.p3.time, timeDelta)
      if (p1Time === null && p2Time === null && p3Time === null && priceDelta === 0) return drawing

      return {
        ...drawing,
        p1: {
          ...drawing.p1,
          ...(p1Time !== null ? { time: p1Time } : {}),
          price: drawing.p1.price + priceDelta,
        },
        p2: {
          ...drawing.p2,
          ...(p2Time !== null ? { time: p2Time } : {}),
          price: drawing.p2.price + priceDelta,
        },
        p3: {
          ...drawing.p3,
          ...(p3Time !== null ? { time: p3Time } : {}),
          price: drawing.p3.price + priceDelta,
        },
      }
    }

    const p1Time = timeDelta === 0 ? drawing.p1.time : shiftTime(drawing.p1.time, timeDelta)
    const p2Time = timeDelta === 0 ? drawing.p2.time : shiftTime(drawing.p2.time, timeDelta)
    if (p1Time === null && p2Time === null && priceDelta === 0) return drawing

    return {
      ...drawing,
      p1: {
        ...drawing.p1,
        ...(p1Time !== null ? { time: p1Time } : {}),
        price: drawing.p1.price + priceDelta,
      },
      p2: {
        ...drawing.p2,
        ...(p2Time !== null ? { time: p2Time } : {}),
        price: drawing.p2.price + priceDelta,
      },
    }
  })
}

export function moveFlintChartDrawingByPriceDelta<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  priceDelta: number,
): FlintChartDrawing<TTime>[] {
  return moveFlintChartDrawingByDelta(drawings, drawingId, { priceDelta })
}

export function moveFlintChartDrawingHandleByDelta<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  handle: FlintChartDrawingHandleId,
  delta: FlintChartDrawingMoveDelta,
): FlintChartDrawing<TTime>[] {
  const target = drawingId ? drawings.find((drawing) => drawing.id === drawingId) : undefined
  const priceDelta = isFiniteNumber(delta.priceDelta) ? delta.priceDelta : 0
  const timeDelta = isFiniteNumber(delta.timeDelta) ? delta.timeDelta : 0
  if (
    !target ||
    target.locked === true ||
    (!isTwoPointDrawing(target) && !isThreePointDrawing(target)) ||
    (handle !== "p1" && handle !== "p2" && handle !== "p3") ||
    (priceDelta === 0 && timeDelta === 0)
  ) {
    return drawings as FlintChartDrawing<TTime>[]
  }

  return drawings.map((drawing) => {
    if (drawing.id !== drawingId) return drawing
    if (!isTwoPointDrawing(drawing) && !isThreePointDrawing(drawing)) {
      return drawing
    }
    if (handle === "p3" && !isThreePointDrawing(drawing)) {
      return drawing
    }

    const point =
      handle === "p3"
        ? isThreePointDrawing(drawing)
          ? drawing.p3
          : null
        : drawing[handle]
    if (!point) return drawing
    const time = timeDelta === 0 ? point.time : shiftTime(point.time, timeDelta)
    if (time === null && priceDelta === 0) return drawing

    return {
      ...drawing,
      [handle]: {
        ...point,
        ...(time !== null ? { time } : {}),
        price: point.price + priceDelta,
      },
    } as FlintChartDrawing<TTime>
  })
}

function scoreFlintChartDrawingPointHit<TTime>(
  point: FlintChartDrawingPoint<TTime>,
  hit: FlintChartDrawingHitPoint<TTime>,
  priceTolerance: number,
  timeTolerance: number,
): number | null {
  if (!hasTime(hit.time)) return null
  const priceDistance = Math.abs(hit.price - point.price)
  const distance = timeDistance(hit.time, point.time)
  if (distance === null || distance > timeTolerance || priceDistance > priceTolerance) {
    return null
  }
  return priceDistance + distance
}

export function findFlintChartDrawingHandleHit<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  drawingId: string | null | undefined,
  point: FlintChartDrawingHitPoint<TTime>,
  options: FlintChartDrawingHitOptions = {},
): FlintChartDrawingHandleHit<TTime> | null {
  const drawing = drawingId
    ? getFlintChartVisibleDrawings(drawings).find((candidate) => candidate.id === drawingId)
    : undefined
  if (
    !drawing ||
    drawing.locked === true ||
    (!isTwoPointDrawing(drawing) && !isThreePointDrawing(drawing))
  ) {
    return null
  }

  const priceTolerance = Math.max(0, options.priceTolerance ?? 0)
  const timeTolerance = Math.max(0, options.timeTolerance ?? 0)
  const candidates: Array<{
    handle: FlintChartDrawingHandleId
    point: FlintChartDrawingPoint<TTime>
    score: number
  }> = []

  for (const candidate of [
    { handle: "p1" as const, point: drawing.p1 },
    { handle: "p2" as const, point: drawing.p2 },
    ...(isThreePointDrawing(drawing) ? [{ handle: "p3" as const, point: drawing.p3 }] : []),
  ]) {
    const score = scoreFlintChartDrawingPointHit(candidate.point, point, priceTolerance, timeTolerance)
    if (score !== null) {
      candidates.push({ ...candidate, score })
    }
  }

  if (candidates.length === 0) return null
  candidates.sort((a, b) => a.score - b.score)
  const { handle, point: hitPoint } = candidates[0]

  return {
    drawingId: drawing.id,
    handle,
    kind: drawing.kind,
    time: hitPoint.time,
    price: hitPoint.price,
  }
}

function scoreFlintChartBoundedSegmentHit<TTime = unknown>(
  p1: FlintChartDrawingPoint<TTime>,
  p2: FlintChartDrawingPoint<TTime>,
  point: FlintChartDrawingHitPoint<TTime>,
  priceTolerance: number,
  timeTolerance: number,
): number | null {
  const expectedPrice = interpolatePriceAtTime(p1, p2, point.time)
  if (expectedPrice === null) return null
  const x = timeToNumber(point.time)
  const x1 = timeToNumber(p1.time)
  const x2 = timeToNumber(p2.time)
  if (x === null || x1 === null || x2 === null) return null
  if (x < Math.min(x1, x2) - timeTolerance || x > Math.max(x1, x2) + timeTolerance) {
    return null
  }

  const priceDistance = Math.abs(point.price - expectedPrice)
  return priceDistance <= priceTolerance ? priceDistance : null
}

function scoreFlintChartDrawingHit<TTime = unknown>(
  drawing: FlintChartDrawing<TTime>,
  point: FlintChartDrawingHitPoint<TTime>,
  priceTolerance: number,
  timeTolerance: number,
): number | null {
  if (drawing.kind === "hline") {
    const distance = Math.abs(point.price - drawing.price)
    return distance <= priceTolerance ? distance : null
  }

  if (drawing.kind === "vline") {
    if (!hasTime(point.time)) return null
    const distance = timeDistance(point.time, drawing.time)
    return distance !== null && distance <= timeTolerance ? distance : null
  }

  if (drawing.kind === "text" || drawing.kind === "callout" || drawing.kind === "price_label") {
    if (!hasTime(point.time)) return null
    const priceDistance = Math.abs(point.price - drawing.point.price)
    const distance = timeDistance(point.time, drawing.point.time)
    if (distance === null || distance > timeTolerance || priceDistance > priceTolerance) return null
    return priceDistance + distance
  }

  if (drawing.kind === "rect") {
    if (!hasTime(point.time)) return null
    const inTime = isTimeInsideRange(point.time, drawing.p1.time, drawing.p2.time, timeTolerance)
    const minPrice = Math.min(drawing.p1.price, drawing.p2.price) - priceTolerance
    const maxPrice = Math.max(drawing.p1.price, drawing.p2.price) + priceTolerance
    return inTime && point.price >= minPrice && point.price <= maxPrice ? 0 : null
  }

  if (drawing.kind === "circle") {
    if (!hasTime(point.time)) return null
    const x = timeToNumber(point.time)
    const x1 = timeToNumber(drawing.p1.time)
    const x2 = timeToNumber(drawing.p2.time)
    if (x === null || x1 === null || x2 === null || x1 === x2) return null

    const minX = Math.min(x1, x2)
    const maxX = Math.max(x1, x2)
    if (x < minX - timeTolerance || x > maxX + timeTolerance) return null

    const centerX = (x1 + x2) / 2
    const radiusX = Math.abs(x2 - x1) / 2
    const centerPrice = (drawing.p1.price + drawing.p2.price) / 2
    const radiusPrice = Math.abs(drawing.p2.price - drawing.p1.price) / 2
    if (radiusX === 0 || radiusPrice === 0) return null

    const normalised =
      ((x - centerX) / radiusX) ** 2 +
      ((point.price - centerPrice) / radiusPrice) ** 2
    const timeToleranceRatio = timeTolerance / radiusX
    const priceToleranceRatio = priceTolerance / radiusPrice
    const tolerance = Math.max(0.08, timeToleranceRatio, priceToleranceRatio)
    return normalised <= (1 + tolerance) ** 2 ? 0 : null
  }

  if (isElliottWaveDrawing(drawing) || isBrushDrawing(drawing)) {
    return drawing.points.slice(1).reduce<number | null>((best, to, index) => {
      const from = drawing.points[index]
      const score = scoreFlintChartBoundedSegmentHit(from, to, point, priceTolerance, timeTolerance)
      if (score === null) return best
      return best === null ? score : Math.min(best, score)
    }, null)
  }

  if (drawing.kind === "parallel_channel") {
    const p4 = createParallelChannelFourthPoint(drawing)
    const segments = p4
      ? [
          [drawing.p1, drawing.p2],
          [drawing.p3, p4],
          [drawing.p1, drawing.p3],
          [drawing.p2, p4],
        ] as const
      : [
          [drawing.p1, drawing.p2],
          [drawing.p1, drawing.p3],
        ] as const

    return segments.reduce<number | null>((best, [from, to]) => {
      const score = scoreFlintChartBoundedSegmentHit(from, to, point, priceTolerance, timeTolerance)
      if (score === null) return best
      return best === null ? score : Math.min(best, score)
    }, null)
  }

  if (drawing.kind === "fib_extension") {
    const nearestLevelDistance = createFlintChartFibExtensionPriceLines(drawing).reduce((nearest, level) => {
      return Math.min(nearest, Math.abs(point.price - level.price))
    }, Number.POSITIVE_INFINITY)
    return nearestLevelDistance <= priceTolerance ? nearestLevelDistance : null
  }

  if (drawing.kind === "long_position" || drawing.kind === "short_position") {
    const nearestLevelDistance = createFlintChartPositionRiskPriceLines(drawing).reduce((nearest, level) => {
      return Math.min(nearest, Math.abs(point.price - level.price))
    }, Number.POSITIVE_INFINITY)
    return nearestLevelDistance <= priceTolerance ? nearestLevelDistance : null
  }

  if (drawing.kind === "fib") {
    const inTime = hasTime(point.time)
      ? isTimeInsideRange(point.time, drawing.p1.time, drawing.p2.time, timeTolerance)
      : true
    if (!inTime) return null
    const hiPrice = Math.max(drawing.p1.price, drawing.p2.price)
    const loPrice = Math.min(drawing.p1.price, drawing.p2.price)
    const range = hiPrice - loPrice
    const nearestLevelDistance = FLINT_CHART_FIB_LEVELS.reduce((nearest, level) => {
      const levelPrice = hiPrice - range * level
      return Math.min(nearest, Math.abs(point.price - levelPrice))
    }, Number.POSITIVE_INFINITY)
    return nearestLevelDistance <= priceTolerance ? nearestLevelDistance : null
  }

  const expectedPrice = interpolatePriceAtTime(drawing.p1, drawing.p2, point.time)
  if (expectedPrice === null) return null
  const x = timeToNumber(point.time)
  const x1 = timeToNumber(drawing.p1.time)
  const x2 = timeToNumber(drawing.p2.time)
  if (x === null || x1 === null || x2 === null) return null

  const inTimeRange =
    drawing.kind === "extended_line"
      ? true
      : drawing.kind === "ray"
      ? x2 >= x1
        ? x >= x1 - timeTolerance
        : x <= x1 + timeTolerance
      : x >= Math.min(x1, x2) - timeTolerance && x <= Math.max(x1, x2) + timeTolerance
  if (!inTimeRange) return null

  const priceDistance = Math.abs(point.price - expectedPrice)
  return priceDistance <= priceTolerance ? priceDistance : null
}

export function findFlintChartDrawingHit<TTime = unknown>(
  drawings: readonly FlintChartDrawing<TTime>[],
  point: FlintChartDrawingHitPoint<TTime>,
  options: FlintChartDrawingHitOptions = {},
): FlintChartDrawing<TTime> | null {
  const priceTolerance = Math.max(0, options.priceTolerance ?? 0)
  const timeTolerance = Math.max(0, options.timeTolerance ?? 0)
  let bestDrawing: FlintChartDrawing<TTime> | null = null
  let bestScore = Number.POSITIVE_INFINITY

  for (const drawing of getFlintChartVisibleDrawings(drawings)) {
    const score = scoreFlintChartDrawingHit(drawing, point, priceTolerance, timeTolerance)
    if (score !== null && score < bestScore) {
      bestDrawing = drawing
      bestScore = score
    }
  }

  return bestDrawing
}

export function parseFlintChartViewState(value: string | null | unknown): FlintChartViewState | null {
  const parsed = typeof value === "string" || value === null ? parseJson(value) : value
  if (!isRecord(parsed)) return null
  if (!isNonEmptyString(parsed.symbol) || !isNonEmptyString(parsed.exchange) || !isNonEmptyString(parsed.interval)) {
    return null
  }
  const visibleLogicalRange = normaliseVisibleLogicalRange(parsed.visibleLogicalRange)
  return {
    symbol: parsed.symbol,
    exchange: parsed.exchange,
    interval: parsed.interval,
    ...(visibleLogicalRange ? { visibleLogicalRange } : {}),
    updatedAt: isFiniteNumber(parsed.updatedAt) ? parsed.updatedAt : 0,
  }
}

export function encodeFlintChartViewState(state: Omit<FlintChartViewState, "updatedAt">): string {
  return JSON.stringify({ ...state, updatedAt: Date.now() } satisfies FlintChartViewState)
}

export function createFlintChartHLinePriceLine(
  priceOrDrawing: number | FlintChartHLineDrawing,
): FlintChartPriceLineSpec {
  const drawing = typeof priceOrDrawing === "number" ? null : priceOrDrawing
  const price = typeof priceOrDrawing === "number" ? priceOrDrawing : priceOrDrawing.price
  const style = drawing ? getFlintChartDrawingStyle(drawing) : createFlintChartDefaultDrawingStyle("hline")
  return {
    price,
    color: style.color,
    lineWidth: style.lineWidth,
    lineStyle: getFlintChartDrawingLineStyleCode(style.lineStyle),
    axisLabelVisible: true,
    title: "",
  }
}

export function createFlintChartVLineMarker<TTime>(
  timeOrDrawing: TTime | FlintChartVLineDrawing<TTime>,
): FlintChartMarkerSpec<TTime> {
  const drawing =
    isRecord(timeOrDrawing) && timeOrDrawing.kind === "vline"
      ? timeOrDrawing as unknown as FlintChartVLineDrawing<TTime>
      : null
  const time = drawing ? drawing.time : timeOrDrawing as TTime
  const style = drawing ? getFlintChartDrawingStyle(drawing) : createFlintChartDefaultDrawingStyle("vline")
  return {
    time,
    position: "inBar",
    color: style.color,
    shape: "square",
    size: 0.5,
    text: "|",
  }
}

export function createFlintChartLineDrawingSeriesOptions(
  kindOrDrawing:
    | "trendline"
    | "ray"
    | "extended_line"
    | "parallel_channel"
    | "brush"
    | "elliott_impulse"
    | "elliott_correction"
    | FlintChartTwoPointDrawing
    | FlintChartParallelChannelDrawing
    | FlintChartBrushDrawing
    | FlintChartElliottWaveDrawing,
): FlintChartLineDrawingSeriesOptions {
  const kind = typeof kindOrDrawing === "string" ? kindOrDrawing : kindOrDrawing.kind
  const style =
    typeof kindOrDrawing === "string"
      ? createFlintChartDefaultDrawingStyle(kind)
      : getFlintChartDrawingStyle(kindOrDrawing)
  return {
    color: style.color,
    lineWidth: style.lineWidth,
    lineStyle: getFlintChartDrawingLineStyleCode(style.lineStyle),
    priceScaleId: "right",
    lastValueVisible: false,
    priceLineVisible: false,
  }
}

export function createFlintChartLineDrawingData<TTime>(
  drawing: FlintChartTwoPointDrawing<TTime>,
): FlintChartLineDataPoint<TTime>[] {
  if (drawing.kind === "ray") {
    const timeDelta = getFlintChartTimeDelta(drawing.p1.time, drawing.p2.time)
    if (timeDelta !== null && timeDelta !== 0) {
      const priceDelta = drawing.p2.price - drawing.p1.price
      const endTime = shiftTime(drawing.p2.time, timeDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER)
      if (endTime !== null) {
        return [
          { time: drawing.p1.time, value: drawing.p1.price },
          {
            time: endTime,
            value: drawing.p2.price + priceDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER,
          },
        ]
      }
    }
  }

  if (drawing.kind === "extended_line") {
    const timeDelta = getFlintChartTimeDelta(drawing.p1.time, drawing.p2.time)
    if (timeDelta !== null && timeDelta !== 0) {
      const priceDelta = drawing.p2.price - drawing.p1.price
      const startTime = shiftTime(drawing.p1.time, -timeDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER)
      const endTime = shiftTime(drawing.p2.time, timeDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER)
      if (startTime !== null && endTime !== null) {
        return [
          {
            time: startTime,
            value: drawing.p1.price - priceDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER,
          },
          {
            time: endTime,
            value: drawing.p2.price + priceDelta * EXTENDED_LINE_EXTENSION_MULTIPLIER,
          },
        ]
      }
    }
  }

  return [
    { time: drawing.p1.time, value: drawing.p1.price },
    { time: drawing.p2.time, value: drawing.p2.price },
  ]
}

function createParallelChannelFourthPoint<TTime>(
  drawing: FlintChartParallelChannelDrawing<TTime>,
): FlintChartDrawingPoint<TTime> | null {
  const timeDelta = getFlintChartTimeDelta(drawing.p1.time, drawing.p3.time)
  if (timeDelta === null) return null
  const time = shiftTime(drawing.p2.time, timeDelta)
  if (time === null) return null
  return {
    time,
    price: drawing.p2.price + drawing.p3.price - drawing.p1.price,
  }
}

export function createFlintChartParallelChannelDrawingData<TTime>(
  drawing: FlintChartParallelChannelDrawing<TTime>,
): FlintChartLineDataPoint<TTime>[][] {
  const p4 = createParallelChannelFourthPoint(drawing)
  const base: FlintChartLineDataPoint<TTime>[] = [
    { time: drawing.p1.time, value: drawing.p1.price },
    { time: drawing.p2.time, value: drawing.p2.price },
  ]
  const width: FlintChartLineDataPoint<TTime>[] = [
    { time: drawing.p1.time, value: drawing.p1.price },
    { time: drawing.p3.time, value: drawing.p3.price },
  ]

  if (!p4) {
    return [base, width]
  }

  return [
    base,
    [
      { time: drawing.p3.time, value: drawing.p3.price },
      { time: p4.time, value: p4.price },
    ],
    width,
    [
      { time: drawing.p2.time, value: drawing.p2.price },
      { time: p4.time, value: p4.price },
    ],
  ]
}

export function createFlintChartBrushDrawing<TTime>(
  points: readonly FlintChartDrawingPoint<TTime>[],
  createId: () => string = createFlintChartDrawingId,
): FlintChartBrushDrawing<TTime> | null {
  const cleanPoints = points.filter((point) => hasTime(point.time) && Number.isFinite(point.price))
  if (cleanPoints.length < 2) return null
  return {
    kind: "brush",
    id: createId(),
    points: cleanPoints.map((point) => ({ ...point })),
  }
}

export function createFlintChartBrushDrawingData<TTime>(
  drawing: FlintChartBrushDrawing<TTime>,
): FlintChartLineDataPoint<TTime>[] {
  return drawing.points.map((point) => ({
    time: point.time,
    value: point.price,
  }))
}

export function createFlintChartElliottWaveDrawingData<TTime>(
  drawing: FlintChartElliottWaveDrawing<TTime>,
): FlintChartLineDataPoint<TTime>[] {
  return drawing.points.map((point) => ({
    time: point.time,
    value: point.price,
  }))
}

function roundDrawingDataValue(value: number): number {
  return Math.round(value * 100_000_000) / 100_000_000
}

export function createFlintChartCircleDrawingData<TTime>(
  drawing: FlintChartTwoPointDrawing<TTime>,
  samples = CIRCLE_DRAWING_ARC_SAMPLES,
): FlintChartLineDataPoint<TTime>[][] {
  const timeDelta = getFlintChartTimeDelta(drawing.p1.time, drawing.p2.time)
  const sampleCount = Math.max(5, Math.floor(samples))
  const centerTime = timeDelta === null ? null : shiftTime(drawing.p1.time, timeDelta / 2)
  const radiusTimeDelta = timeDelta === null ? null : timeDelta / 2
  const centerPrice = (drawing.p1.price + drawing.p2.price) / 2
  const radiusPrice = Math.abs(drawing.p2.price - drawing.p1.price) / 2

  if (
    timeDelta === null ||
    timeDelta === 0 ||
    centerTime === null ||
    radiusTimeDelta === null ||
    radiusPrice === 0
  ) {
    return [createFlintChartLineDrawingData(drawing)]
  }

  const buildArc = (direction: 1 | -1): FlintChartLineDataPoint<TTime>[] => {
    const points: FlintChartLineDataPoint<TTime>[] = []
    for (let index = 0; index < sampleCount; index += 1) {
      const progress = index / (sampleCount - 1)
      const angle = Math.PI * progress
      const time = shiftTime(centerTime, -radiusTimeDelta * Math.cos(angle))
      if (time === null) continue
      points.push({
        time,
        value: roundDrawingDataValue(centerPrice + direction * Math.sin(angle) * radiusPrice),
      })
    }
    return points
  }

  const upper = buildArc(1)
  const lower = buildArc(-1)
  return upper.length > 1 && lower.length > 1
    ? [upper, lower]
    : [createFlintChartLineDrawingData(drawing)]
}

export function createFlintChartDrawingHandleMarkers<TTime>(
  drawings: readonly FlintChartDrawing<TTime>[],
  selectedDrawingId: string | null | undefined,
): FlintChartMarkerSpec<TTime>[] {
  const drawing = getFlintChartSelectedDrawing(drawings, selectedDrawingId)
  if (
    !drawing ||
    drawing.hidden === true ||
    drawing.locked === true ||
    (!isTwoPointDrawing(drawing) && !isThreePointDrawing(drawing))
  ) {
    return []
  }
  const style = getFlintChartDrawingStyle(drawing)
  const points = [
    { point: drawing.p1, text: "1" },
    { point: drawing.p2, text: "2" },
    ...(isThreePointDrawing(drawing) ? [{ point: drawing.p3, text: "3" }] : []),
  ]
  return points.map(({ point, text }) => ({
    time: point.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "circle",
    size: 1.25,
    price: point.price,
    text,
  }))
}

export function createFlintChartFibPriceLines<TTime>(
  drawing: FlintChartTwoPointDrawing<TTime>,
): FlintChartPriceLineSpec[] {
  const hiPrice = Math.max(drawing.p1.price, drawing.p2.price)
  const loPrice = Math.min(drawing.p1.price, drawing.p2.price)
  const range = hiPrice - loPrice
  const style = drawing.style ? getFlintChartDrawingStyle(drawing) : null

  return FLINT_CHART_FIB_LEVELS.map((level) => ({
    price: hiPrice - range * level,
    color: style?.color ?? FLINT_CHART_FIB_COLORS[level] ?? "#94a3b8",
    lineWidth: style?.lineWidth ?? 1,
    lineStyle: style ? getFlintChartDrawingLineStyleCode(style.lineStyle) : LINE_DASHED,
    axisLabelVisible: true,
    title: `Fib ${(level * 100).toFixed(1)}%`,
  }))
}

export function createFlintChartElliottWaveMarkers<TTime>(
  drawing: FlintChartElliottWaveDrawing<TTime>,
): FlintChartMarkerSpec<TTime>[] {
  const style = getFlintChartDrawingStyle(drawing)
  const labels = getFlintChartElliottWaveLabels(drawing.kind)
  return drawing.points.map((point, index) => ({
    time: point.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "circle",
    size: 1.15,
    price: point.price,
    text: labels[index] ?? String(index),
  }))
}

export function createFlintChartFibExtensionPriceLines<TTime>(
  drawing: FlintChartFibExtensionDrawing<TTime>,
): FlintChartPriceLineSpec[] {
  const range = drawing.p2.price - drawing.p1.price
  const style = drawing.style ? getFlintChartDrawingStyle(drawing) : null

  return FLINT_CHART_FIB_EXTENSION_LEVELS.map((level) => ({
    price: roundDrawingDataValue(drawing.p3.price + range * level),
    color: style?.color ?? FLINT_CHART_FIB_EXTENSION_COLORS[level] ?? "#22c55e",
    lineWidth: style?.lineWidth ?? 1,
    lineStyle: style ? getFlintChartDrawingLineStyleCode(style.lineStyle) : LINE_DASHED,
    axisLabelVisible: true,
    title: `Fib Ext ${(level * 100).toFixed(1)}%`,
  }))
}

export function createFlintChartPositionRiskPriceLines<TTime>(
  drawing: FlintChartPositionRiskDrawing<TTime>,
): FlintChartPriceLineSpec[] {
  const side = drawing.kind === "long_position" ? "Long" : "Short"
  const style = drawing.style ? getFlintChartDrawingStyle(drawing) : null
  const lineWidth = style?.lineWidth ?? 1
  const lineStyle = style ? getFlintChartDrawingLineStyleCode(style.lineStyle) : LINE_DASHED

  return [
    {
      price: drawing.p1.price,
      color: style?.color ?? "#38bdf8",
      lineWidth,
      lineStyle,
      axisLabelVisible: true,
      title: `${side} Entry`,
    },
    {
      price: drawing.p2.price,
      color: style?.color ?? "#22c55e",
      lineWidth,
      lineStyle,
      axisLabelVisible: true,
      title: `${side} Target`,
    },
    {
      price: drawing.p3.price,
      color: style?.color ?? "#ef4444",
      lineWidth,
      lineStyle,
      axisLabelVisible: true,
      title: `${side} Stop`,
    },
  ]
}

export function createFlintChartRectPriceLines<TTime>(
  drawing: FlintChartTwoPointDrawing<TTime>,
): FlintChartPriceLineSpec[] {
  const topPrice = Math.max(drawing.p1.price, drawing.p2.price)
  const botPrice = Math.min(drawing.p1.price, drawing.p2.price)
  const style = getFlintChartDrawingStyle(drawing)
  return [
    {
      price: topPrice,
      color: style.color,
      lineWidth: style.lineWidth,
      lineStyle: getFlintChartDrawingLineStyleCode(style.lineStyle),
      axisLabelVisible: true,
      title: "Rect Top",
    },
    {
      price: botPrice,
      color: style.color,
      lineWidth: style.lineWidth,
      lineStyle: getFlintChartDrawingLineStyleCode(style.lineStyle),
      axisLabelVisible: true,
      title: "Rect Bot",
    },
  ]
}

export function createFlintChartMeasureMarker<TTime>(
  drawing: FlintChartTwoPointDrawing<TTime>,
): FlintChartMarkerSpec<TTime> {
  const style = getFlintChartDrawingStyle(drawing)
  return {
    time: drawing.p2.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "circle",
    size: 1,
    price: drawing.p2.price,
    text: getFlintChartMeasureLabel(drawing),
  }
}

export function createFlintChartTextMarker<TTime>(
  drawing: FlintChartTextDrawing<TTime>,
): FlintChartMarkerSpec<TTime> {
  const style = getFlintChartDrawingStyle(drawing)
  return {
    time: drawing.point.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "circle",
    size: 1,
    price: drawing.point.price,
    text: drawing.label,
  }
}

export function createFlintChartPriceLabelMarker<TTime>(
  drawing: FlintChartPriceLabelDrawing<TTime>,
): FlintChartMarkerSpec<TTime> {
  const style = getFlintChartDrawingStyle(drawing)
  return {
    time: drawing.point.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "square",
    size: 1,
    price: drawing.point.price,
    text: formatDrawingPrice(drawing.point.price),
  }
}

export function createFlintChartCalloutMarker<TTime>(
  drawing: FlintChartCalloutDrawing<TTime>,
): FlintChartMarkerSpec<TTime> {
  const style = getFlintChartDrawingStyle(drawing)
  return {
    time: drawing.point.time,
    position: "atPriceMiddle",
    color: style.color,
    shape: "square",
    size: 1,
    price: drawing.point.price,
    text: drawing.label,
  }
}

export function createFlintChartDrawingRenderPlan<TTime>(
  drawings: readonly FlintChartDrawing<TTime>[],
  selectedDrawingId?: string | null,
): FlintChartDrawingRenderPlan<TTime> {
  const lineSeries: FlintChartDrawingLineSeriesRenderSpec<TTime>[] = []
  const priceLines: FlintChartDrawingPriceLineRenderSpec[] = []
  const markers: FlintChartMarkerSpec<TTime>[] = []
  const lineSeriesCounts = new Map<string, number>()
  const priceLineCounts = new Map<string, number>()

  const createRenderKey = (counts: Map<string, number>, drawingId: string, kind: "line" | "price") => {
    const index = counts.get(drawingId) ?? 0
    counts.set(drawingId, index + 1)
    return `${drawingId}:${kind}:${index}`
  }

  const addLineSeries = (
    drawingId: string,
    options: FlintChartLineDrawingSeriesOptions,
    data: FlintChartLineDataPoint<TTime>[],
  ) => {
    lineSeries.push({ key: createRenderKey(lineSeriesCounts, drawingId, "line"), drawingId, options, data })
  }

  const addPriceLines = (drawingId: string, specs: readonly FlintChartPriceLineSpec[]) => {
    priceLines.push(...specs.map((priceLine) => ({
      key: createRenderKey(priceLineCounts, drawingId, "price"),
      drawingId,
      priceLine,
    })))
  }

  for (const drawing of getFlintChartVisibleDrawings(drawings)) {
    if (drawing.kind === "hline") {
      addPriceLines(drawing.id, [createFlintChartHLinePriceLine(drawing)])
      continue
    }

    if (drawing.kind === "vline") {
      markers.push(createFlintChartVLineMarker(drawing))
      continue
    }

    if (
      drawing.kind === "trendline" ||
      drawing.kind === "ray" ||
      drawing.kind === "extended_line" ||
      drawing.kind === "measure"
    ) {
      addLineSeries(
        drawing.id,
        createFlintChartLineDrawingSeriesOptions(drawing),
        createFlintChartLineDrawingData(drawing),
      )
      if (drawing.kind === "measure") {
        markers.push(createFlintChartMeasureMarker(drawing))
      }
      continue
    }

    if (drawing.kind === "circle") {
      for (const arc of createFlintChartCircleDrawingData(drawing)) {
        addLineSeries(drawing.id, createFlintChartLineDrawingSeriesOptions(drawing), arc)
      }
      continue
    }

    if (drawing.kind === "parallel_channel") {
      for (const segment of createFlintChartParallelChannelDrawingData(drawing)) {
        addLineSeries(drawing.id, createFlintChartLineDrawingSeriesOptions(drawing), segment)
      }
      continue
    }

    if (drawing.kind === "elliott_impulse" || drawing.kind === "elliott_correction") {
      addLineSeries(
        drawing.id,
        createFlintChartLineDrawingSeriesOptions(drawing),
        createFlintChartElliottWaveDrawingData(drawing),
      )
      markers.push(...createFlintChartElliottWaveMarkers(drawing))
      continue
    }

    if (drawing.kind === "brush") {
      addLineSeries(
        drawing.id,
        createFlintChartLineDrawingSeriesOptions(drawing),
        createFlintChartBrushDrawingData(drawing),
      )
      continue
    }

    if (drawing.kind === "fib") {
      addPriceLines(drawing.id, createFlintChartFibPriceLines(drawing))
      continue
    }

    if (drawing.kind === "fib_extension") {
      addPriceLines(drawing.id, createFlintChartFibExtensionPriceLines(drawing))
      continue
    }

    if (drawing.kind === "long_position" || drawing.kind === "short_position") {
      addPriceLines(drawing.id, createFlintChartPositionRiskPriceLines(drawing))
      continue
    }

    if (drawing.kind === "rect") {
      addPriceLines(drawing.id, createFlintChartRectPriceLines(drawing))
      continue
    }

    if (drawing.kind === "text") {
      markers.push(createFlintChartTextMarker(drawing))
      continue
    }

    if (drawing.kind === "callout") {
      markers.push(createFlintChartCalloutMarker(drawing))
      continue
    }

    if (drawing.kind === "price_label") {
      markers.push(createFlintChartPriceLabelMarker(drawing))
    }
  }

  markers.push(...createFlintChartDrawingHandleMarkers(drawings, selectedDrawingId))

  return { lineSeries, priceLines, markers }
}

function areFlintChartRenderSpecsEqual<TSpec>(previous: TSpec, next: TSpec): boolean {
  return JSON.stringify(previous) === JSON.stringify(next)
}

function createFlintChartRenderPlanPartDiff<TSpec extends { key: string }>(
  previous: readonly TSpec[],
  next: readonly TSpec[],
): FlintChartDrawingRenderPlanPartDiff<TSpec> {
  const previousByKey = new Map(previous.map((entry) => [entry.key, entry]))
  const nextByKey = new Map(next.map((entry) => [entry.key, entry]))
  const added: TSpec[] = []
  const updated: TSpec[] = []
  const unchanged: TSpec[] = []
  const removed: TSpec[] = []

  for (const nextSpec of next) {
    const previousSpec = previousByKey.get(nextSpec.key)
    if (!previousSpec) {
      added.push(nextSpec)
      continue
    }
    if (areFlintChartRenderSpecsEqual(previousSpec, nextSpec)) {
      unchanged.push(nextSpec)
      continue
    }
    updated.push(nextSpec)
  }

  for (const previousSpec of previous) {
    if (!nextByKey.has(previousSpec.key)) {
      removed.push(previousSpec)
    }
  }

  return { added, updated, unchanged, removed }
}

export function createFlintChartDrawingRenderPlanDiff<TTime>(
  previous: FlintChartDrawingRenderPlan<TTime>,
  next: FlintChartDrawingRenderPlan<TTime>,
): FlintChartDrawingRenderPlanDiff<TTime> {
  return {
    lineSeries: createFlintChartRenderPlanPartDiff(previous.lineSeries, next.lineSeries),
    priceLines: createFlintChartRenderPlanPartDiff(previous.priceLines, next.priceLines),
    markersChanged: !areFlintChartRenderSpecsEqual(previous.markers, next.markers),
    markers: next.markers,
  }
}
