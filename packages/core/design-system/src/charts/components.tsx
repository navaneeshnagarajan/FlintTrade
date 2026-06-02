import {
  AlignJustify,
  ArrowRight,
  ChevronRight,
  Circle,
  Crosshair,
  Eraser,
  Eye,
  EyeOff,
  GitBranch,
  GitMerge,
  Infinity,
  LayoutGrid,
  Lock,
  Minus,
  Pen,
  Ruler,
  Square,
  Star,
  Tag,
  Trash2,
  Triangle,
  TrendingDown,
  TrendingUp,
  Type,
  Unlock,
  MessageSquare,
} from "lucide-react"
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react"
import type { MouseEvent as ReactMouseEvent, ReactNode } from "react"

import { cn } from "../lib/utils"
import {
  FLINT_CHART_DRAWING_LINE_STYLES,
  FLINT_CHART_DRAWING_LINE_WIDTHS,
  FLINT_CHART_DRAWING_STYLE_COLORS,
  createFlintChartDrawingSummaries,
  getFlintChartElliottWaveLabels,
  getFlintChartDrawingDetail,
  getFlintChartDrawingLabel,
} from "./drawings"
import type {
  FlintChartDrawing,
  FlintChartDrawingLineWidth,
  FlintChartDrawingStyle,
  FlintChartDrawingStyleInput,
} from "./drawings"

export interface FlintChartLegendState {
  open: number
  high: number
  low: number
  close: number
  volume: number | null
  bull: boolean
}

export interface FlintChartCrosshairSeriesDataMap<TSeries = unknown> {
  get(series: TSeries): unknown
}

export interface FlintChartCrosshairEventLike<TSeries = unknown, TTime = unknown> {
  time?: TTime | null
  seriesData?: FlintChartCrosshairSeriesDataMap<TSeries> | null
}

export interface FlintChartCrosshairReadoutState<TTime = unknown> extends FlintChartLegendState {
  time: TTime
}

export interface FlintChartLegendProps {
  legend: FlintChartLegendState
  className?: string
}

export interface FlintMiniSparklineProps {
  points: readonly number[]
  ariaLabel: string
  positive?: boolean
  className?: string
}

export interface FlintBaselineSparklineProps {
  points: readonly number[]
  baseline: number
  ariaLabel: string
  positive?: boolean
  className?: string
}

export interface FlintCategoricalBarEntry {
  label: string
  value: number
  color?: string
}

export interface FlintCategoricalBarChartProps {
  entries: readonly FlintCategoricalBarEntry[]
  ariaLabel: string
  valueFormatter?: (value: number) => string
  width?: number
  height?: number
  className?: string
}

export interface FlintSignedCategoricalBarEntry {
  label: string
  value: number
  color?: string
}

export interface FlintSignedCategoricalBarChartProps {
  entries: readonly FlintSignedCategoricalBarEntry[]
  ariaLabel: string
  valueFormatter?: (value: number) => string
  positiveColor?: string
  negativeColor?: string
  width?: number
  height?: number
  className?: string
}

export interface FlintStackedBarSeries {
  label: string
  color: string
  values: readonly number[]
}

export interface FlintStackedBarChartProps {
  labels: readonly string[]
  series: readonly FlintStackedBarSeries[]
  ariaLabel: string
  valueFormatter?: (value: number) => string
  maxValue?: number
  className?: string
}

export interface FlintThresholdLinePoint {
  label: string
  value: number
}

export interface FlintThresholdBand {
  min: number
  max: number
  color: string
  label?: string
}

export interface FlintThresholdLine {
  value: number
  color?: string
  dash?: string
  label?: string
}

export interface FlintThresholdLineChartProps {
  points: readonly FlintThresholdLinePoint[]
  ariaLabel: string
  minValue?: number
  maxValue?: number
  bands?: readonly FlintThresholdBand[]
  thresholds?: readonly FlintThresholdLine[]
  yTicks?: readonly number[]
  xLabelIndices?: readonly number[]
  yFormatter?: (value: number) => string
  lineColor?: string
  fillColor?: string
  width?: number
  height?: number
  className?: string
}

export interface FlintMultiLinePoint {
  x: number
  y: number
  label?: string
}

export interface FlintMultiLineSeries {
  id: string
  label: string
  color: string
  points: readonly FlintMultiLinePoint[]
  dash?: string
  strokeWidth?: number
}

export interface FlintMultiLineChartProps {
  series: readonly FlintMultiLineSeries[]
  ariaLabel: string
  xDomain: readonly [number, number]
  yDomain: readonly [number, number]
  xTicks?: readonly number[]
  yTicks?: readonly number[]
  xFormatter?: (value: number) => string
  yFormatter?: (value: number) => string
  xAxisLabel?: string
  yAxisLabel?: string
  referenceLines?: readonly FlintScatterReferenceLine[]
  width?: number
  height?: number
  className?: string
}

export interface FlintBandedLineBand {
  id: string
  label?: string
  color: string
  upper: readonly FlintMultiLinePoint[]
  lower: readonly FlintMultiLinePoint[]
}

export interface FlintBandedLineMarker {
  id: string
  label: string
  x: number
  y: number
  color: string
  radius?: number
}

export interface FlintBandedLineChartProps {
  bands: readonly FlintBandedLineBand[]
  series: readonly FlintMultiLineSeries[]
  markers?: readonly FlintBandedLineMarker[]
  ariaLabel: string
  xDomain: readonly [number, number]
  yDomain: readonly [number, number]
  xTicks?: readonly number[]
  yTicks?: readonly number[]
  xFormatter?: (value: number) => string
  yFormatter?: (value: number) => string
  xAxisLabel?: string
  yAxisLabel?: string
  referenceLines?: readonly FlintScatterReferenceLine[]
  width?: number
  height?: number
  className?: string
}

export interface FlintPayoffPoint {
  x: number
  y: number
  label?: string
}

export interface FlintPayoffChartProps {
  points: readonly FlintPayoffPoint[]
  ariaLabel: string
  breakeven?: number
  breakevens?: readonly number[]
  strikeMarkers?: readonly number[]
  spotPrice?: number | null
  maxProfit?: number | null
  maxLoss?: number | null
  interactive?: boolean
  xDomain?: readonly [number, number]
  yDomain?: readonly [number, number]
  xTicks?: readonly number[]
  yTicks?: readonly number[]
  xFormatter?: (value: number) => string
  yFormatter?: (value: number) => string
  lineColor?: string
  profitFillColor?: string
  lossFillColor?: string
  breakevenColor?: string
  width?: number
  height?: number
  className?: string
}

export interface FlintScatterPoint {
  id: string
  label: string
  x: number
  y: number
  radius?: number
  color?: string
  strokeColor?: string
}

export interface FlintScatterReferenceLine {
  axis: "x" | "y"
  value: number
  color?: string
  dash?: string
}

export interface FlintScatterChartProps {
  points: readonly FlintScatterPoint[]
  ariaLabel: string
  xDomain: readonly [number, number]
  yDomain: readonly [number, number]
  xTicks?: readonly number[]
  yTicks?: readonly number[]
  xFormatter?: (value: number) => string
  yFormatter?: (value: number) => string
  xAxisLabel?: string
  yAxisLabel?: string
  referenceLines?: readonly FlintScatterReferenceLine[]
  activePointId?: string | null
  onPointHover?: (point: FlintScatterPoint | null) => void
  width?: number
  height?: number
  className?: string
}

export type FlintTrackerTone = "profit" | "loss" | "neutral"

export interface FlintTrackerSegment {
  key?: string
  tone: FlintTrackerTone
  label?: string
}

export interface FlintSegmentTrackerProps {
  segments: readonly FlintTrackerSegment[]
  ariaLabel: string
  className?: string
}

export interface FlintDonutSlice {
  label: string
  value: number
  color: string
}

export interface FlintDonutBreakdownProps {
  slices: readonly FlintDonutSlice[]
  ariaLabel: string
  centerValue?: ReactNode
  centerLabel?: ReactNode
  className?: string
}

export interface FlintLinearMeterProps {
  value: number
  ariaLabel: string
  minValue?: number
  maxValue?: number
  fillColor?: string
  trackColor?: string
  marker?: boolean
  markerColor?: string
  heightClassName?: string
  className?: string
}

export interface FlintDivergingBarEntry {
  label: string
  leftValue: number
  rightValue: number
  leftLabel?: string
  rightLabel?: string
}

export interface FlintDivergingBarListProps {
  entries: readonly FlintDivergingBarEntry[]
  ariaLabel: string
  valueFormatter?: (value: number) => string
  leftHeading?: string
  rightHeading?: string
  leftColor?: string
  rightColor?: string
  maxValue?: number
  className?: string
}

export interface FlintRadialGaugeProps {
  value: number
  ariaLabel?: string
  color?: string
  trackColor?: string
  size?: number
  strokeWidth?: number
  decorative?: boolean
  className?: string
}

export interface FlintRankedBarEntry {
  label: string
  value: number
  color?: string
}

export interface FlintRankedBarListProps {
  entries: readonly FlintRankedBarEntry[]
  ariaLabel: string
  valueFormatter: (value: number) => string
  maxValue?: number
  className?: string
}

export interface FlintWeightedHeatmapEntry {
  id: string
  label: string
  valueLabel: string
  detailLabel?: string
  weight: number
  color: string
  textColor?: string
}

export interface FlintWeightedHeatmapProps {
  entries: readonly FlintWeightedHeatmapEntry[]
  ariaLabel: string
  minWidthPercent?: number
  maxWidthPercent?: number
  className?: string
}

export interface FlintChartIntervalOption {
  label: string
  value: string
}

export interface FlintChartIntervalPillsProps {
  intervals: readonly FlintChartIntervalOption[]
  active: string
  onSelect: (value: string) => void
  maxVisible?: number
  size?: "standard" | "compact"
  className?: string
}

export type FlintChartDrawToolId =
  | "cursor" | "eraser"
  | "hline" | "vline" | "trendline" | "ray" | "extended_line" | "parallel_channel"
  | "fib" | "fib_extension"
  | "rect" | "circle" | "brush"
  | "text" | "callout" | "price_label"
  | "elliott_impulse" | "elliott_correction"
  | "long_position" | "short_position" | "measure"

export interface FlintChartToolDefinition<TTool extends string = FlintChartDrawToolId> {
  id: TTool
  label: string
  icon: ReactNode
  comingSoon?: boolean
}

export interface FlintChartToolGroup<TTool extends string = FlintChartDrawToolId> {
  key: string
  label?: string
  tools: readonly FlintChartToolDefinition<TTool>[]
}

export interface FlintChartDrawingToolbarProps<TTool extends string = FlintChartDrawToolId> {
  drawMode: TTool | null
  onToggle: (tool: TTool) => void
  onClearAll: () => void
  orientation?: FlintChartToolbarOrientation
  groups?: readonly FlintChartToolGroup<TTool>[]
  storageKeyPrefix?: string
  onHideAll?: () => void
  onLockAll?: () => void
  drawingsHidden?: boolean
  drawingsLocked?: boolean
  className?: string
}

export interface FlintChartDrawStatusProps<TTool extends string = FlintChartDrawToolId> {
  drawMode: TTool | null
  drawingCount: number
  pendingPoint?: unknown | null
  pendingPoints?: readonly unknown[]
  awaitingText?: unknown | null
  twoClickTools?: readonly TTool[]
  threeClickTools?: readonly TTool[]
  className?: string
}

export interface FlintChartDrawingListProps<TTime = unknown> {
  drawings: readonly FlintChartDrawing<TTime>[]
  selectedDrawingId: string | null
  onSelectDrawing: (drawingId: string) => void
  onDeleteDrawing: (drawingId: string) => void
  className?: string
}

export interface FlintChartDrawingStyleEditorProps<TTime = unknown> {
  drawing: FlintChartDrawing<TTime> | null
  value: FlintChartDrawingStyle
  onChange: (style: FlintChartDrawingStyleInput) => void
  className?: string
}

export interface FlintChartDrawingInspectorProps<TTime = unknown> {
  drawing: FlintChartDrawing<TTime> | null
  value: FlintChartDrawingStyle
  onStyleChange: (style: FlintChartDrawingStyleInput) => void
  onToggleHidden: (drawingId: string, hidden: boolean) => void
  onToggleLocked: (drawingId: string, locked: boolean) => void
  onDeleteDrawing: (drawingId: string) => void
  className?: string
}

export type FlintChartToolbarOrientation = "vertical" | "horizontal"

export interface FlintChartWorkspaceLayout {
  compact: boolean
  toolbarOrientation: FlintChartToolbarOrientation
}

export type FlintChartKeyboardAction =
  | { kind: "set-tool"; tool: FlintChartDrawToolId }
  | { kind: "cancel-drawing" }
  | { kind: "undo-drawing" }
  | { kind: "delete-last-drawing" }
  | { kind: "clear-all-drawings" }

export interface FlintChartKeyboardEventLike {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  altKey?: boolean
  shiftKey?: boolean
  target?: EventTarget | null
}

const ICON_SIZE = 13
const FLINT_CHART_COMPACT_WORKSPACE_WIDTH = 520

export const FLINT_CHART_TWO_CLICK_TOOLS: readonly FlintChartDrawToolId[] = [
  "trendline",
  "ray",
  "extended_line",
  "fib",
  "rect",
  "circle",
  "measure",
]

export const FLINT_CHART_THREE_CLICK_TOOLS: readonly FlintChartDrawToolId[] = [
  "parallel_channel",
  "fib_extension",
  "long_position",
  "short_position",
  "elliott_impulse",
  "elliott_correction",
]

function normaliseSparkPoints(points: readonly number[]): number[] {
  return points.filter((point) => Number.isFinite(point))
}

function buildSparklinePath(points: readonly number[], width: number, height: number, padding = 3): string {
  const values = normaliseSparkPoints(points)
  if (values.length === 0) return ""
  if (values.length === 1) {
    const y = height / 2
    return `M0 ${y.toFixed(2)} L${width} ${y.toFixed(2)}`
  }

  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const innerHeight = height - padding * 2

  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = padding + (1 - (value - min) / range) * innerHeight
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(" ")
}

export function FlintMiniSparkline({
  points,
  ariaLabel,
  positive = true,
  className,
}: FlintMiniSparklineProps) {
  const gradientId = useId().replace(/:/g, "")
  const width = 160
  const height = 42
  const linePath = buildSparklinePath(points, width, height)
  const areaPath = linePath ? `${linePath} L${width} ${height - 2} L0 ${height - 2} Z` : ""

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("block w-full text-profit", positive ? "text-profit" : "text-loss", className)}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="currentColor" stopOpacity="0.26" />
          <stop offset="100%" stopColor="currentColor" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {areaPath && <path d={areaPath} fill={`url(#${gradientId})`} aria-hidden="true" />}
      {linePath && (
        <path
          d={linePath}
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.5"
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />
      )}
    </svg>
  )
}

function buildBaselineSparklineState(
  points: readonly number[],
  baseline: number,
  width: number,
  height: number,
  padding = 3,
): { linePath: string; baselineY: number } {
  const values = normaliseSparkPoints(points)
  const safeBaseline = Number.isFinite(baseline) ? baseline : 0
  const domainValues = [...values, safeBaseline]
  const min = Math.min(...domainValues)
  const max = Math.max(...domainValues)
  const range = max - min || 1
  const innerHeight = height - padding * 2
  const yFor = (value: number) => padding + (1 - (value - min) / range) * innerHeight
  const baselineY = yFor(safeBaseline)

  if (values.length === 0) return { linePath: "", baselineY }
  if (values.length === 1) {
    const y = yFor(values[0])
    return { linePath: `M0 ${y.toFixed(2)} L${width} ${y.toFixed(2)}`, baselineY }
  }

  const linePath = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = yFor(value)
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(" ")

  return { linePath, baselineY }
}

export function FlintBaselineSparkline({
  points,
  baseline,
  ariaLabel,
  positive = true,
  className,
}: FlintBaselineSparklineProps) {
  const width = 160
  const height = 42
  const { linePath, baselineY } = buildBaselineSparklineState(points, baseline, width, height)

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={cn("block w-full text-profit", positive ? "text-profit" : "text-loss", className)}
    >
      <line
        x1="0"
        x2={width}
        y1={baselineY.toFixed(2)}
        y2={baselineY.toFixed(2)}
        stroke="var(--color-border-default, currentColor)"
        strokeOpacity="0.7"
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
        aria-hidden="true"
      />
      {linePath && (
        <path
          d={linePath}
          fill="none"
          stroke="currentColor"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth="2.5"
          vectorEffect="non-scaling-stroke"
          aria-hidden="true"
        />
      )}
    </svg>
  )
}

export function FlintCategoricalBarChart({
  entries,
  ariaLabel,
  valueFormatter = (value) => value.toLocaleString("en-IN"),
  width = 200,
  height = 60,
  className,
}: FlintCategoricalBarChartProps) {
  const visibleEntries = entries.map((entry) => ({
    ...entry,
    value: Number.isFinite(entry.value) ? Math.max(0, entry.value) : 0,
  }))
  const topPadding = 10
  const bottomPadding = 18
  const sidePadding = 4
  const chartWidth = Math.max(1, width - sidePadding * 2)
  const chartHeight = Math.max(1, height - topPadding - bottomPadding)
  const maxValue = Math.max(...visibleEntries.map((entry) => entry.value), 1)
  const slotWidth = chartWidth / Math.max(visibleEntries.length, 1)
  const barWidth = Math.max(2, Math.min(32, slotWidth * 0.72))

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="categorical-bar"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
    >
      {visibleEntries.map((entry, index) => {
        const value = entry.value
        const barHeight = value > 0 ? Math.max(1, (value / maxValue) * chartHeight) : 0
        const slotStart = sidePadding + index * slotWidth
        const x = slotStart + (slotWidth - barWidth) / 2
        const y = topPadding + chartHeight - barHeight
        const barColor = entry.color ?? "rgba(99,102,241,0.55)"

        return (
          <g key={`${entry.label}-${index}`}>
            <title>{`${entry.label}: ${valueFormatter(value)}`}</title>
            <rect
              data-categorical-bar={entry.label}
              x={x}
              y={y}
              width={barWidth}
              height={barHeight}
              rx={2}
              fill={barColor}
              aria-hidden="true"
            />
            <text
              x={slotStart + slotWidth / 2}
              y={height - 4}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-text-muted, #666)"
              aria-hidden="true"
            >
              {entry.label}
            </text>
            {value > 0 && (
              <text
                x={slotStart + slotWidth / 2}
                y={Math.max(8, y - 3)}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-text-secondary, #999)"
                aria-hidden="true"
              >
                {valueFormatter(value)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function FlintSignedCategoricalBarChart({
  entries,
  ariaLabel,
  valueFormatter = (value) => value.toLocaleString("en-IN"),
  positiveColor = "var(--color-profit, #22c55e)",
  negativeColor = "var(--color-loss, #ef4444)",
  width = 220,
  height = 90,
  className,
}: FlintSignedCategoricalBarChartProps) {
  const visibleEntries = entries.map((entry) => ({
    ...entry,
    value: Number.isFinite(entry.value) ? entry.value : 0,
  }))
  const topPadding = 14
  const bottomPadding = 18
  const sidePadding = 4
  const chartWidth = Math.max(1, width - sidePadding * 2)
  const chartHeight = Math.max(1, height - topPadding - bottomPadding)
  const baselineY = topPadding + chartHeight / 2
  const maxMagnitude = Math.max(...visibleEntries.map((entry) => Math.abs(entry.value)), 1)
  const slotWidth = chartWidth / Math.max(visibleEntries.length, 1)
  const barWidth = Math.max(2, Math.min(30, slotWidth * 0.68))
  const halfHeight = Math.max(1, chartHeight / 2 - 4)

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="signed-categorical-bar"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
    >
      <line
        x1={sidePadding}
        x2={width - sidePadding}
        y1={baselineY}
        y2={baselineY}
        stroke="var(--color-border-default, currentColor)"
        strokeOpacity="0.65"
        strokeWidth="1"
        vectorEffect="non-scaling-stroke"
        aria-hidden="true"
      />
      {visibleEntries.map((entry, index) => {
        const value = entry.value
        const magnitude = Math.abs(value)
        const barHeight = magnitude > 0 ? Math.max(1, (magnitude / maxMagnitude) * halfHeight) : 0
        const slotStart = sidePadding + index * slotWidth
        const x = slotStart + (slotWidth - barWidth) / 2
        const y = value >= 0 ? baselineY - barHeight : baselineY
        const labelY = height - 4
        const valueY = value >= 0 ? Math.max(9, y - 4) : Math.min(height - bottomPadding + 10, y + barHeight + 10)
        const barColor = entry.color ?? (value >= 0 ? positiveColor : negativeColor)

        return (
          <g key={`${entry.label}-${index}`}>
            <title>{`${entry.label}: ${valueFormatter(value)}`}</title>
            <rect
              data-signed-categorical-bar={entry.label}
              x={x}
              y={y}
              width={barWidth}
              height={barHeight}
              rx={2}
              fill={barColor}
              aria-hidden="true"
            />
            <text
              x={slotStart + slotWidth / 2}
              y={labelY}
              textAnchor="middle"
              fontSize={9}
              fill="var(--color-text-muted, #666)"
              aria-hidden="true"
            >
              {entry.label}
            </text>
            {magnitude > 0 && (
              <text
                x={slotStart + slotWidth / 2}
                y={valueY}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-text-secondary, #999)"
                aria-hidden="true"
              >
                {valueFormatter(value)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export function FlintStackedBarChart({
  labels,
  series,
  ariaLabel,
  valueFormatter = (value) => `${value.toFixed(1)}%`,
  maxValue = 100,
  className,
}: FlintStackedBarChartProps) {
  const safeMaxValue = Number.isFinite(maxValue) && maxValue > 0 ? maxValue : 100
  const visibleSeries = series
    .map((entry) => ({
      ...entry,
      values: entry.values.map((value) => Number.isFinite(value) ? Math.max(0, value) : 0),
    }))
    .filter((entry) => entry.values.some((value) => value > 0))

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="stacked-bar"
      className={cn("space-y-2", className)}
    >
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {visibleSeries.map((entry) => (
          <div key={entry.label} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
              style={{ backgroundColor: entry.color }}
              aria-hidden="true"
            />
            <span className="text-xs text-text-secondary">{entry.label}</span>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        {labels.map((label, labelIndex) => {
          const segments = visibleSeries
            .map((entry) => {
              const value = entry.values[labelIndex] ?? 0
              const width = Math.min(100, Math.max(0, (value / safeMaxValue) * 100))
              return { ...entry, value, width }
            })
            .filter((entry) => entry.value > 0)

          return (
            <div key={`${label}-${labelIndex}`} className="flex items-center gap-3">
              <span className="w-20 shrink-0 text-right text-xs text-text-muted">{label}</span>
              <div className="flex h-6 flex-1 overflow-hidden rounded bg-surface-elevated">
                {segments.map((segment) => (
                  <div
                    key={`${label}-${segment.label}`}
                    data-stacked-bar-segment={segment.label}
                    className="flex h-full items-center justify-center overflow-hidden transition-[width] duration-300 ease-out"
                    style={{
                      width: `${segment.width}%`,
                      backgroundColor: segment.color,
                      minWidth: segment.width > 2 ? "1.5rem" : undefined,
                    }}
                    aria-label={`${segment.label}: ${valueFormatter(segment.value)}`}
                    title={`${segment.label}: ${valueFormatter(segment.value)}`}
                  >
                    {segment.width > 6 && (
                      <span className="truncate px-1 font-mono text-xxs font-semibold text-white">
                        {valueFormatter(segment.value)}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function FlintThresholdLineChart({
  points,
  ariaLabel,
  minValue,
  maxValue,
  bands = [],
  thresholds = [],
  yTicks = [],
  xLabelIndices,
  yFormatter = (value) => value.toFixed(1),
  lineColor = "currentColor",
  fillColor = "currentColor",
  width = 500,
  height = 180,
  className,
}: FlintThresholdLineChartProps) {
  const clipId = useId().replace(/:/g, "")
  const padding = { top: 12, right: 16, bottom: 30, left: 36 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const values = points.filter((point) => Number.isFinite(point.value))
  const pointValues = values.map((point) => point.value)
  const domainMin = minValue ?? Math.min(...pointValues, 0)
  const domainMax = maxValue ?? Math.max(...pointValues, 1)
  const safeMax = domainMax > domainMin ? domainMax : domainMin + 1
  const xFor = (index: number) => (
    values.length > 1 ? (index / (values.length - 1)) * chartWidth : chartWidth / 2
  )
  const yFor = (value: number) => chartHeight - ((value - domainMin) / (safeMax - domainMin)) * chartHeight
  const linePath = values
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(index).toFixed(1)},${yFor(point.value).toFixed(1)}`)
    .join(" ")
  const areaPath = values.length > 0
    ? [
        `M ${xFor(0).toFixed(1)},${yFor(values[0].value).toFixed(1)}`,
        ...values.slice(1).map((point, index) => `L ${xFor(index + 1).toFixed(1)},${yFor(point.value).toFixed(1)}`),
        `L ${xFor(values.length - 1).toFixed(1)},${chartHeight.toFixed(1)}`,
        `L ${xFor(0).toFixed(1)},${chartHeight.toFixed(1)}`,
        "Z",
      ].join(" ")
    : ""
  const labelIndices = xLabelIndices
    ? Array.from(new Set(xLabelIndices)).filter((index) => index >= 0 && index < values.length)
    : [0, Math.floor(values.length / 2), values.length - 1].filter((index, pos, all) => index >= 0 && all.indexOf(index) === pos)

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="threshold-line"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full text-accent", className)}
      style={{ height }}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={chartWidth} height={chartHeight} />
        </clipPath>
      </defs>

      <g transform={`translate(${padding.left},${padding.top})`}>
        {bands.map((band) => {
          const y1 = yFor(Math.min(Math.max(band.max, domainMin), safeMax))
          const y2 = yFor(Math.min(Math.max(band.min, domainMin), safeMax))
          if (y1 >= y2) return null
          return (
            <rect
              key={`${band.label ?? "band"}-${band.min}-${band.max}`}
              data-threshold-band={band.label ?? `${band.min}-${band.max}`}
              x={0}
              y={y1}
              width={chartWidth}
              height={y2 - y1}
              fill={band.color}
              aria-hidden="true"
            />
          )
        })}

        {thresholds.map((threshold) => {
          if (threshold.value < domainMin || threshold.value > safeMax) return null
          const y = yFor(threshold.value)
          return (
            <line
              key={`${threshold.label ?? "threshold"}-${threshold.value}`}
              data-threshold-line={threshold.label ?? threshold.value}
              x1={0}
              y1={y}
              x2={chartWidth}
              y2={y}
              stroke={threshold.color ?? "var(--color-border-default, currentColor)"}
              strokeWidth={0.75}
              strokeDasharray={threshold.dash}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          )
        })}

        {areaPath && <path d={areaPath} fill={fillColor} clipPath={`url(#${clipId})`} opacity={1} aria-hidden="true" />}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke={lineColor}
            strokeWidth={1.5}
            strokeLinecap="round"
            strokeLinejoin="round"
            clipPath={`url(#${clipId})`}
            vectorEffect="non-scaling-stroke"
            aria-hidden="true"
          />
        )}

        {values.length > 0 && (
          <circle
            cx={xFor(values.length - 1)}
            cy={yFor(values[values.length - 1].value)}
            r={3.5}
            fill={lineColor}
            stroke="var(--color-surface-base, #0a0a0f)"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            aria-hidden="true"
          />
        )}

        {yTicks.filter((value) => value >= domainMin && value <= safeMax).map((value) => (
          <g key={value} aria-hidden="true">
            <line x1={-4} x2={0} y1={yFor(value)} y2={yFor(value)} stroke="var(--color-border-default, #2a2a3a)" />
            <text x={-6} y={yFor(value) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted, #666)">
              {yFormatter(value)}
            </text>
          </g>
        ))}

        {labelIndices.map((index) => (
          <text
            key={`${values[index].label}-${index}`}
            x={xFor(index)}
            y={chartHeight + 18}
            textAnchor="middle"
            fontSize={8}
            fill="var(--color-text-muted, #666)"
            aria-hidden="true"
          >
            {values[index].label}
          </text>
        ))}

        <line x1={0} y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
        <line x1={0} y1={0} x2={0} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
      </g>
    </svg>
  )
}

export function FlintMultiLineChart({
  series,
  ariaLabel,
  xDomain,
  yDomain,
  xTicks = [],
  yTicks = [],
  xFormatter = (value) => String(value),
  yFormatter = (value) => String(value),
  xAxisLabel,
  yAxisLabel,
  referenceLines = [],
  width = 520,
  height = 180,
  className,
}: FlintMultiLineChartProps) {
  const clipId = useId().replace(/:/g, "")
  const padding = { top: 12, right: 16, bottom: 28, left: 42 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const [xMin, rawXMax] = xDomain
  const [yMin, rawYMax] = yDomain
  const xMax = rawXMax > xMin ? rawXMax : xMin + 1
  const yMax = rawYMax > yMin ? rawYMax : yMin + 1
  const xFor = (value: number) => ((value - xMin) / (xMax - xMin)) * chartWidth
  const yFor = (value: number) => chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight
  const visibleSeries = series.map((entry) => ({
    ...entry,
    points: entry.points.filter((point) => (
      Number.isFinite(point.x)
      && Number.isFinite(point.y)
      && point.x >= xMin
      && point.x <= xMax
      && point.y >= yMin
      && point.y <= yMax
    )),
  }))

  const pathFor = (points: readonly FlintMultiLinePoint[]) => points
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
    .join(" ")

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="multi-line"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={chartWidth} height={chartHeight} />
        </clipPath>
      </defs>

      <g transform={`translate(${padding.left},${padding.top})`}>
        {yTicks.filter((tick) => tick >= yMin && tick <= yMax).map((tick) => (
          <g key={`y-${tick}`} aria-hidden="true">
            <line x1={0} y1={yFor(tick)} x2={chartWidth} y2={yFor(tick)} stroke="rgba(255,255,255,0.06)" />
            <text x={-6} y={yFor(tick) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted, #666)">
              {yFormatter(tick)}
            </text>
          </g>
        ))}

        {xTicks.filter((tick) => tick >= xMin && tick <= xMax).map((tick) => (
          <text
            key={`x-${tick}`}
            x={xFor(tick)}
            y={chartHeight + 14}
            textAnchor="middle"
            fontSize={8}
            fill="var(--color-text-muted, #666)"
            aria-hidden="true"
          >
            {xFormatter(tick)}
          </text>
        ))}

        {referenceLines.map((line) => {
          if (line.axis === "x") {
            if (line.value < xMin || line.value > xMax) return null
            const x = xFor(line.value)
            return (
              <line
                key={`x-ref-${line.value}`}
                x1={x}
                y1={0}
                x2={x}
                y2={chartHeight}
                stroke={line.color ?? "rgba(156,163,175,0.35)"}
                strokeDasharray={line.dash}
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
              />
            )
          }

          if (line.value < yMin || line.value > yMax) return null
          const y = yFor(line.value)
          return (
            <line
              key={`y-ref-${line.value}`}
              x1={0}
              y1={y}
              x2={chartWidth}
              y2={y}
              stroke={line.color ?? "rgba(156,163,175,0.35)"}
              strokeDasharray={line.dash}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          )
        })}

        {visibleSeries.map((entry) => {
          const linePath = pathFor(entry.points)
          if (entry.points.length < 2 || !linePath) return null

          return (
            <path
              key={entry.id}
              data-line-series={entry.id}
              d={linePath}
              fill="none"
              stroke={entry.color}
              strokeWidth={1.75}
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipId})`}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            >
              <title>{entry.label}</title>
            </path>
          )
        })}

        {visibleSeries.map((entry) => {
          const last = entry.points[entry.points.length - 1]
          if (!last) return null

          return (
            <circle
              key={`${entry.id}-endpoint`}
              data-series-endpoint={entry.id}
              cx={xFor(last.x)}
              cy={yFor(last.y)}
              r={3.5}
              fill={entry.color}
              stroke="var(--color-surface-base, #0a0a0f)"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            >
              <title>{last.label ?? entry.label}</title>
            </circle>
          )
        })}

        <line x1={0} y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
        <line x1={0} y1={0} x2={0} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />

        {xAxisLabel && (
          <text x={chartWidth / 2} y={chartHeight + 24} textAnchor="middle" fontSize={8} fill="var(--color-text-muted, #666)">
            {xAxisLabel}
          </text>
        )}
        {yAxisLabel && (
          <text x={-padding.left + 6} y={-4} fontSize={8} fill="var(--color-text-muted, #666)">
            {yAxisLabel}
          </text>
        )}
      </g>
    </svg>
  )
}

export function FlintBandedLineChart({
  bands,
  series,
  markers = [],
  ariaLabel,
  xDomain,
  yDomain,
  xTicks = [],
  yTicks = [],
  xFormatter = (value) => String(value),
  yFormatter = (value) => String(value),
  xAxisLabel,
  yAxisLabel,
  referenceLines = [],
  width = 520,
  height = 200,
  className,
}: FlintBandedLineChartProps) {
  const clipId = useId().replace(/:/g, "")
  const padding = { top: 16, right: 20, bottom: 32, left: 40 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const [xMin, rawXMax] = xDomain
  const [yMin, rawYMax] = yDomain
  const xMax = rawXMax > xMin ? rawXMax : xMin + 1
  const yMax = rawYMax > yMin ? rawYMax : yMin + 1
  const xFor = (value: number) => ((value - xMin) / (xMax - xMin)) * chartWidth
  const yFor = (value: number) => chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight
  const finitePoints = (points: readonly FlintMultiLinePoint[]) => points.filter((point) => (
    Number.isFinite(point.x)
    && Number.isFinite(point.y)
    && point.x >= xMin
    && point.x <= xMax
    && point.y >= yMin
    && point.y <= yMax
  ))
  const pathFor = (points: readonly FlintMultiLinePoint[]) => finitePoints(points)
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
    .join(" ")
  const bandPathFor = (upper: readonly FlintMultiLinePoint[], lower: readonly FlintMultiLinePoint[]) => {
    const top = finitePoints(upper)
    const bottom = finitePoints(lower)
    if (top.length < 2 || bottom.length < 2) return ""

    const topPath = top
      .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
      .join(" ")
    const bottomPath = [...bottom]
      .reverse()
      .map((point) => `L${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
      .join(" ")

    return `${topPath} ${bottomPath} Z`
  }

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="banded-line"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={chartWidth} height={chartHeight} />
        </clipPath>
      </defs>

      <g transform={`translate(${padding.left},${padding.top})`}>
        {yTicks.filter((tick) => tick >= yMin && tick <= yMax).map((tick) => (
          <g key={`y-${tick}`} aria-hidden="true">
            <line x1={0} y1={yFor(tick)} x2={chartWidth} y2={yFor(tick)} stroke="rgba(255,255,255,0.06)" />
            <text x={-6} y={yFor(tick) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted, #666)">
              {yFormatter(tick)}
            </text>
          </g>
        ))}

        {bands.map((band) => {
          const d = bandPathFor(band.upper, band.lower)
          if (!d) return null

          return (
            <path
              key={band.id}
              data-banded-line-band={band.id}
              d={d}
              fill={band.color}
              clipPath={`url(#${clipId})`}
              aria-hidden="true"
            >
              {band.label && <title>{band.label}</title>}
            </path>
          )
        })}

        {referenceLines.map((line) => {
          if (line.axis === "x") {
            if (line.value < xMin || line.value > xMax) return null
            const x = xFor(line.value)
            return (
              <line
                key={`x-ref-${line.value}`}
                x1={x}
                y1={0}
                x2={x}
                y2={chartHeight}
                stroke={line.color ?? "var(--color-border-default, currentColor)"}
                strokeDasharray={line.dash}
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
              />
            )
          }

          if (line.value < yMin || line.value > yMax) return null
          const y = yFor(line.value)
          return (
            <line
              key={`y-ref-${line.value}`}
              x1={0}
              y1={y}
              x2={chartWidth}
              y2={y}
              stroke={line.color ?? "var(--color-border-default, currentColor)"}
              strokeDasharray={line.dash}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          )
        })}

        {series.map((entry) => {
          const d = pathFor(entry.points)
          if (!d) return null

          return (
            <path
              key={entry.id}
              data-banded-line-series={entry.id}
              d={d}
              fill="none"
              stroke={entry.color}
              strokeWidth={entry.strokeWidth ?? 1.25}
              strokeDasharray={entry.dash}
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipId})`}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            >
              <title>{entry.label}</title>
            </path>
          )
        })}

        {markers.filter((marker) => (
          Number.isFinite(marker.x)
          && Number.isFinite(marker.y)
          && marker.x >= xMin
          && marker.x <= xMax
          && marker.y >= yMin
          && marker.y <= yMax
        )).map((marker) => (
          <circle
            key={marker.id}
            data-banded-line-marker={marker.id}
            cx={xFor(marker.x)}
            cy={yFor(marker.y)}
            r={marker.radius ?? 4.5}
            fill={marker.color}
            stroke="var(--color-surface-base, #0a0a0f)"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
            aria-hidden="true"
          >
            <title>{marker.label}</title>
          </circle>
        ))}

        {xTicks.filter((tick) => tick >= xMin && tick <= xMax).map((tick) => (
          <text
            key={`x-${tick}`}
            x={xFor(tick)}
            y={chartHeight + 18}
            textAnchor="middle"
            fontSize={9}
            fill="var(--color-text-muted, #666)"
            aria-hidden="true"
          >
            {xFormatter(tick)}
          </text>
        ))}

        <line x1={0} y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
        <line x1={0} y1={0} x2={0} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />

        {xAxisLabel && (
          <text x={chartWidth / 2} y={chartHeight + 29} textAnchor="middle" fontSize={8} fill="var(--color-text-muted, #666)">
            {xAxisLabel}
          </text>
        )}
        {yAxisLabel && (
          <text x={-padding.left + 6} y={-5} fontSize={8} fill="var(--color-text-muted, #666)">
            {yAxisLabel}
          </text>
        )}
      </g>
    </svg>
  )
}

export function FlintPayoffChart({
  points,
  ariaLabel,
  breakeven,
  breakevens = [],
  strikeMarkers = [],
  spotPrice = null,
  maxProfit = null,
  maxLoss = null,
  interactive = false,
  xDomain,
  yDomain,
  xTicks = [],
  yTicks = [],
  xFormatter = (value) => String(value),
  yFormatter = (value) => String(value),
  lineColor = "rgba(99,102,241,0.85)",
  profitFillColor = "rgba(34,197,94,0.15)",
  lossFillColor = "rgba(239,68,68,0.15)",
  breakevenColor = "rgba(245,158,11,0.6)",
  width = 500,
  height = 140,
  className,
}: FlintPayoffChartProps) {
  const clipId = useId().replace(/:/g, "")
  const [tooltip, setTooltip] = useState<{
    x: number
    y: number
    xValue: number
    yValue: number
    visible: boolean
  }>({ x: 0, y: 0, xValue: 0, yValue: 0, visible: false })
  const padding = { top: 12, right: 16, bottom: 28, left: 52 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const visiblePoints = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y))
  const domainPoints = visiblePoints.length > 0 ? visiblePoints : [{ x: 0, y: 0 }]
  const xValues = domainPoints.map((point) => point.x)
  const yValues = [...domainPoints.map((point) => point.y), 0]
  const [xMin, rawXMax] = xDomain ?? [Math.min(...xValues), Math.max(...xValues)]
  const [yMin, rawYMax] = yDomain ?? [Math.min(...yValues), Math.max(...yValues)]
  const xMax = rawXMax > xMin ? rawXMax : xMin + 1
  const yMax = rawYMax > yMin ? rawYMax : yMin + 1
  const xFor = (value: number) => ((value - xMin) / (xMax - xMin)) * chartWidth
  const yFor = (value: number) => chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight
  const zeroY = yFor(0)
  const linePath = visiblePoints
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
    .join(" ")
  const allBreakevens = Array.from(new Set([
    ...(Number.isFinite(breakeven) && breakeven !== undefined ? [breakeven] : []),
    ...breakevens.filter((value) => Number.isFinite(value)),
  ])).sort((a, b) => a - b)
  const visibleStrikeMarkers = Array.from(new Set(strikeMarkers.filter((value) => (
    Number.isFinite(value) && value >= xMin && value <= xMax
  )))).sort((a, b) => a - b)

  const buildZonePath = (zone: "profit" | "loss") => {
    if (visiblePoints.length < 2) return ""
    const hasZone = zone === "profit"
      ? visiblePoints.some((point) => point.y > 0)
      : visiblePoints.some((point) => point.y < 0)

    if (!hasZone) return ""

    const clampedPoints = visiblePoints.map((point) => ({
      x: point.x,
      y: zone === "profit" ? Math.max(point.y, 0) : Math.min(point.y, 0),
    }))
    const zonePath = clampedPoints
      .map((point) => `L ${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
      .join(" ")

    return [
      `M ${xFor(clampedPoints[0].x).toFixed(1)},${zeroY.toFixed(1)}`,
      zonePath,
      `L ${xFor(clampedPoints[clampedPoints.length - 1].x).toFixed(1)},${zeroY.toFixed(1)}`,
      "Z",
    ].join(" ")
  }

  const profitPath = buildZonePath("profit")
  const lossPath = buildZonePath("loss")
  const payoffSegments = (() => {
    if (visiblePoints.length === 0) return []
    type Segment = { above: boolean; points: FlintPayoffPoint[] }
    const segments: Segment[] = []
    let current: Segment = { above: visiblePoints[0].y >= 0, points: [visiblePoints[0]] }

    for (let index = 1; index < visiblePoints.length; index += 1) {
      const previous = visiblePoints[index - 1]
      const currentPoint = visiblePoints[index]
      const previousAbove = previous.y >= 0
      const currentAbove = currentPoint.y >= 0

      if (previousAbove !== currentAbove) {
        const ratio = -previous.y / (currentPoint.y - previous.y)
        const crossing = {
          x: previous.x + ratio * (currentPoint.x - previous.x),
          y: 0,
        }
        current.points.push(crossing)
        segments.push(current)
        current = { above: currentAbove, points: [crossing, currentPoint] }
      } else {
        current.points.push(currentPoint)
      }
    }

    segments.push(current)
    return segments
  })()
  const pathFor = (segmentPoints: readonly FlintPayoffPoint[]) => segmentPoints
    .map((point, index) => `${index === 0 ? "M" : "L"}${xFor(point.x).toFixed(1)},${yFor(point.y).toFixed(1)}`)
    .join(" ")
  const spotX = spotPrice !== null && Number.isFinite(spotPrice) && spotPrice >= xMin && spotPrice <= xMax
    ? xFor(spotPrice)
    : null
  const maxProfitY = maxProfit !== null && Number.isFinite(maxProfit) ? yFor(maxProfit) : null
  const maxLossY = maxLoss !== null && Number.isFinite(maxLoss) ? yFor(maxLoss) : null
  const interpolateAtX = (xValue: number) => {
    if (visiblePoints.length === 0) return 0
    const first = visiblePoints[0]
    const last = visiblePoints[visiblePoints.length - 1]
    if (xValue <= first.x) return first.y
    if (xValue >= last.x) return last.y

    for (let index = 1; index < visiblePoints.length; index += 1) {
      const previous = visiblePoints[index - 1]
      const current = visiblePoints[index]
      if (xValue >= previous.x && xValue <= current.x) {
        const span = current.x - previous.x || 1
        const ratio = (xValue - previous.x) / span
        return previous.y + ratio * (current.y - previous.y)
      }
    }

    return last.y
  }
  const handleMouseMove = (event: ReactMouseEvent<SVGSVGElement>) => {
    if (!interactive) return
    const rect = event.currentTarget.getBoundingClientRect()
    if (rect.width <= 0) return
    const svgX = (event.clientX - rect.left) * (width / rect.width)
    const localX = svgX - padding.left
    if (localX < 0 || localX > chartWidth) {
      setTooltip((state) => ({ ...state, visible: false }))
      return
    }

    const xValue = xMin + (localX / chartWidth) * (xMax - xMin)
    const yValue = interpolateAtX(xValue)
    setTooltip({
      x: localX,
      y: yFor(yValue),
      xValue,
      yValue,
      visible: true,
    })
  }
  const handleMouseLeave = () => {
    if (!interactive) return
    setTooltip((state) => ({ ...state, visible: false }))
  }

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="payoff"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
      onMouseMove={interactive ? handleMouseMove : undefined}
      onMouseLeave={interactive ? handleMouseLeave : undefined}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={0} y={0} width={chartWidth} height={chartHeight} />
        </clipPath>
      </defs>

      <g transform={`translate(${padding.left},${padding.top})`}>
        {zeroY >= 0 && zeroY <= chartHeight && (
          <line
            data-testid="zero-line"
            x1={0}
            y1={zeroY}
            x2={chartWidth}
            y2={zeroY}
            stroke="rgba(156,163,175,0.4)"
            strokeWidth={0.75}
            strokeDasharray="3,2"
            vectorEffect="non-scaling-stroke"
            aria-hidden="true"
          />
        )}

        {maxProfitY !== null && maxProfitY >= 0 && maxProfitY <= chartHeight && maxProfit !== null && (
          <g data-payoff-max-profit="">
            <line
              x1={0}
              y1={maxProfitY}
              x2={chartWidth}
              y2={maxProfitY}
              stroke="var(--color-profit, #22c55e)"
              strokeWidth={0.75}
              strokeDasharray="4,3"
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
            <text x={chartWidth - 2} y={maxProfitY - 3} textAnchor="end" fontSize={8} fill="var(--color-profit, #22c55e)">
              {yFormatter(maxProfit)}
            </text>
          </g>
        )}

        {maxLossY !== null && maxLossY >= 0 && maxLossY <= chartHeight && maxLoss !== null && (
          <g data-payoff-max-loss="">
            <line
              x1={0}
              y1={maxLossY}
              x2={chartWidth}
              y2={maxLossY}
              stroke="var(--color-loss, #ef4444)"
              strokeWidth={0.75}
              strokeDasharray="4,3"
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
            <text x={chartWidth - 2} y={maxLossY + 9} textAnchor="end" fontSize={8} fill="var(--color-loss, #ef4444)">
              {yFormatter(maxLoss)}
            </text>
          </g>
        )}

        {visibleStrikeMarkers.map((strike) => {
          const x = xFor(strike)
          return (
            <g key={`strike-${strike}`} data-payoff-strike={strike}>
              <line
                x1={x}
                y1={0}
                x2={x}
                y2={chartHeight}
                stroke="var(--color-border-default, #2a2a3a)"
                strokeWidth={0.75}
                strokeDasharray="3,3"
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
              />
              <text
                x={x}
                y={-3}
                textAnchor="middle"
                fontSize={8}
                fill="var(--color-text-muted, #666)"
                aria-label={`Strike ${strike}`}
              >
                {xFormatter(strike)}
              </text>
            </g>
          )
        })}

        {profitPath && (
          <path
            data-payoff-zone="profit"
            d={profitPath}
            fill={profitFillColor}
            clipPath={`url(#${clipId})`}
            aria-hidden="true"
          />
        )}

        {lossPath && (
          <path
            data-payoff-zone="loss"
            d={lossPath}
            fill={lossFillColor}
            clipPath={`url(#${clipId})`}
            aria-hidden="true"
          />
        )}

        {payoffSegments.map((segment, index) => {
          const d = pathFor(segment.points)
          if (!d) return null
          return (
            <path
              key={`segment-${index}`}
              data-payoff-line=""
              data-payoff-segment={segment.above ? "profit" : "loss"}
              d={d}
              fill="none"
              stroke={segment.above ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)"}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath={`url(#${clipId})`}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          )
        })}

        {payoffSegments.length === 0 && linePath && (
          <path
            data-payoff-line=""
            d={linePath}
            fill="none"
            stroke={lineColor}
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            clipPath={`url(#${clipId})`}
            vectorEffect="non-scaling-stroke"
            aria-hidden="true"
          />
        )}

        {allBreakevens.map((value) => {
          const x = xFor(value)
          if (x < 0 || x > chartWidth) return null
          return (
            <g key={`breakeven-${value}`}>
              <line
                data-payoff-breakeven=""
                x1={x}
                y1={0}
                x2={x}
                y2={chartHeight}
                stroke={breakevenColor}
                strokeWidth={1}
                strokeDasharray="4,2"
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
              />
              <text
                x={x + 2}
                y={chartHeight / 2}
                fontSize={8}
                fill={breakevenColor}
                aria-label={`Breakeven ${value}`}
              >
                {xFormatter(value)}
              </text>
            </g>
          )
        })}

        {spotX !== null && spotPrice !== null && (
          <g data-payoff-spot="">
            <line
              x1={spotX}
              y1={0}
              x2={spotX}
              y2={chartHeight}
              stroke="var(--color-accent, #7c6af7)"
              strokeWidth={1}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
            <text x={spotX + 2} y={10} fontSize={8} fill="var(--color-accent, #7c6af7)">
              {xFormatter(spotPrice)}
            </text>
          </g>
        )}

        {tooltip.visible && (
          <g>
            <line
              x1={tooltip.x}
              y1={0}
              x2={tooltip.x}
              y2={chartHeight}
              stroke="var(--color-text-muted, #888)"
              strokeWidth={0.5}
              strokeDasharray="2,2"
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
            <circle
              data-payoff-tooltip-point=""
              cx={tooltip.x}
              cy={Math.max(0, Math.min(chartHeight, tooltip.y))}
              r={3}
              fill={tooltip.yValue >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)"}
              stroke="var(--color-surface-card, #16161f)"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
            <rect
              x={Math.min(chartWidth - 96, tooltip.x + 4)}
              y={Math.max(0, Math.min(chartHeight - 32, tooltip.y - 16))}
              width={96}
              height={32}
              rx={3}
              fill="var(--color-surface-card, #16161f)"
              stroke="var(--color-border-default, #2a2a3a)"
              strokeWidth={0.75}
              aria-hidden="true"
            />
            <text x={Math.min(chartWidth - 90, tooltip.x + 10)} y={Math.max(11, Math.min(chartHeight - 21, tooltip.y - 5))} fontSize={8} fill="var(--color-text-muted, #888)">
              {xFormatter(tooltip.xValue)}
            </text>
            <text
              x={Math.min(chartWidth - 90, tooltip.x + 10)}
              y={Math.max(23, Math.min(chartHeight - 9, tooltip.y + 7))}
              fontSize={8}
              fontWeight={600}
              fill={tooltip.yValue >= 0 ? "var(--color-profit, #22c55e)" : "var(--color-loss, #ef4444)"}
            >
              {tooltip.yValue >= 0 ? "+" : ""}
              {yFormatter(tooltip.yValue)}
            </text>
          </g>
        )}

        {yTicks.filter((tick) => tick >= yMin && tick <= yMax).map((tick) => (
          <g key={`y-${tick}`} aria-hidden="true">
            <line x1={-4} x2={0} y1={yFor(tick)} y2={yFor(tick)} stroke="var(--color-border-default, #2a2a3a)" />
            <text x={-6} y={yFor(tick) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted, #666)">
              {yFormatter(tick)}
            </text>
          </g>
        ))}

        {xTicks.filter((tick) => tick >= xMin && tick <= xMax).map((tick, index) => (
          <text
            key={`x-${tick}`}
            x={xFor(tick)}
            y={chartHeight + 16}
            textAnchor={index === 0 ? "start" : index === xTicks.length - 1 ? "end" : "middle"}
            fontSize={8}
            fill="var(--color-text-muted, #666)"
            aria-hidden="true"
          >
            {xFormatter(tick)}
          </text>
        ))}

        <line x1={0} y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
        <line x1={0} y1={0} x2={0} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
      </g>
    </svg>
  )
}

export function FlintScatterChart({
  points,
  ariaLabel,
  xDomain,
  yDomain,
  xTicks = [],
  yTicks = [],
  xFormatter = (value) => String(value),
  yFormatter = (value) => String(value),
  xAxisLabel,
  yAxisLabel,
  referenceLines = [],
  activePointId = null,
  onPointHover,
  width = 340,
  height = 120,
  className,
}: FlintScatterChartProps) {
  const padding = { top: 10, right: 16, bottom: 28, left: 40 }
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const [xMin, rawXMax] = xDomain
  const [yMin, rawYMax] = yDomain
  const xMax = rawXMax > xMin ? rawXMax : xMin + 1
  const yMax = rawYMax > yMin ? rawYMax : yMin + 1
  const xFor = (value: number) => ((value - xMin) / (xMax - xMin)) * chartWidth
  const yFor = (value: number) => chartHeight - ((value - yMin) / (yMax - yMin)) * chartHeight
  const visiblePoints = points.filter((point) => (
    Number.isFinite(point.x)
    && Number.isFinite(point.y)
    && point.x >= xMin
    && point.x <= xMax
    && point.y >= yMin
    && point.y <= yMax
  ))

  return (
    <svg
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="scatter"
      viewBox={`0 0 ${width} ${height}`}
      className={cn("block w-full", className)}
      style={{ height }}
    >
      <g transform={`translate(${padding.left},${padding.top})`}>
        {yTicks.filter((tick) => tick >= yMin && tick <= yMax).map((tick) => (
          <g key={`y-${tick}`} aria-hidden="true">
            <line x1={0} y1={yFor(tick)} x2={chartWidth} y2={yFor(tick)} stroke="rgba(255,255,255,0.06)" />
            <text x={-4} y={yFor(tick) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted, #666)">
              {yFormatter(tick)}
            </text>
          </g>
        ))}

        {xTicks.filter((tick) => tick >= xMin && tick <= xMax).map((tick) => (
          <text
            key={`x-${tick}`}
            x={xFor(tick)}
            y={chartHeight + 14}
            textAnchor="middle"
            fontSize={8}
            fill="var(--color-text-muted, #666)"
            aria-hidden="true"
          >
            {xFormatter(tick)}
          </text>
        ))}

        {referenceLines.map((line) => {
          if (line.axis === "x") {
            if (line.value < xMin || line.value > xMax) return null
            const x = xFor(line.value)
            return (
              <line
                key={`x-ref-${line.value}`}
                x1={x}
                y1={0}
                x2={x}
                y2={chartHeight}
                stroke={line.color ?? "var(--color-border-default, currentColor)"}
                strokeDasharray={line.dash}
                vectorEffect="non-scaling-stroke"
                aria-hidden="true"
              />
            )
          }

          if (line.value < yMin || line.value > yMax) return null
          const y = yFor(line.value)
          return (
            <line
              key={`y-ref-${line.value}`}
              x1={0}
              y1={y}
              x2={chartWidth}
              y2={y}
              stroke={line.color ?? "var(--color-border-default, currentColor)"}
              strokeDasharray={line.dash}
              vectorEffect="non-scaling-stroke"
              aria-hidden="true"
            />
          )
        })}

        <line x1={0} y1={0} x2={0} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />
        <line x1={0} y1={chartHeight} x2={chartWidth} y2={chartHeight} stroke="var(--color-border-default, #2a2a3a)" aria-hidden="true" />

        {visiblePoints.map((point) => {
          const active = activePointId === point.id
          const radius = point.radius ?? 4

          return (
            <circle
              key={point.id}
              data-testid={`scatter-point-${point.id}`}
              data-scatter-point={point.id}
              cx={xFor(point.x)}
              cy={yFor(point.y)}
              r={active ? radius + 2 : radius}
              fill={point.color ?? "currentColor"}
              fillOpacity={active ? 0.9 : 0.72}
              stroke={point.strokeColor ?? "rgba(255,255,255,0.15)"}
              strokeWidth={active ? 2 : 0.5}
              style={{ cursor: onPointHover ? "pointer" : undefined, transition: "r 0.15s ease, fill-opacity 0.15s ease" }}
              onMouseEnter={onPointHover ? () => onPointHover(point) : undefined}
              onMouseLeave={onPointHover ? () => onPointHover(null) : undefined}
              aria-hidden="true"
            >
              <title>{point.label}</title>
            </circle>
          )
        })}

        {xAxisLabel && (
          <text x={chartWidth / 2} y={chartHeight + 24} textAnchor="middle" fontSize={8} fill="var(--color-text-muted, #666)">
            {xAxisLabel}
          </text>
        )}
        {yAxisLabel && (
          <text
            transform={`translate(${-26}, ${chartHeight / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={8}
            fill="var(--color-text-muted, #666)"
          >
            {yAxisLabel}
          </text>
        )}
      </g>
    </svg>
  )
}

function trackerToneClass(tone: FlintTrackerTone): string {
  if (tone === "profit") return "bg-profit/75 shadow-[0_0_12px_rgba(52,211,153,0.22)]"
  if (tone === "loss") return "bg-loss/75 shadow-[0_0_12px_rgba(248,113,113,0.2)]"
  return "bg-surface-elevated"
}

export function FlintSegmentTracker({
  segments,
  ariaLabel,
  className,
}: FlintSegmentTrackerProps) {
  if (segments.length === 0) return null

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      className={cn("flex h-5 w-full items-center gap-1", className)}
    >
      {segments.map((segment, index) => (
        <div
          key={segment.key ?? `${segment.tone}-${index}`}
          title={segment.label}
          className={cn("h-full min-w-2 flex-1 rounded-[3px]", trackerToneClass(segment.tone))}
          aria-hidden="true"
        />
      ))}
    </div>
  )
}

function normaliseDonutSlices(slices: readonly FlintDonutSlice[]): FlintDonutSlice[] {
  return slices.filter((slice) => slice.value > 0 && Number.isFinite(slice.value))
}

function buildDonutGradient(slices: readonly FlintDonutSlice[]): string {
  const visible = normaliseDonutSlices(slices)
  const total = visible.reduce((sum, slice) => sum + slice.value, 0)
  if (total <= 0) return "#1f2937 0% 100%"

  let cursor = 0
  return visible
    .map((slice) => {
      const start = cursor
      cursor += (slice.value / total) * 100
      return `${slice.color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`
    })
    .join(", ")
}

export function FlintDonutBreakdown({
  slices,
  ariaLabel,
  centerValue,
  centerLabel,
  className,
}: FlintDonutBreakdownProps) {
  const gradient = buildDonutGradient(slices)
  const hasCenterContent = centerValue !== undefined || centerLabel !== undefined

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="donut"
      className={cn("relative size-36 shrink-0 rounded-full", className)}
      style={{ background: `conic-gradient(${gradient})` }}
    >
      <div className="absolute inset-[22%] rounded-full bg-surface-card" aria-hidden="true">
        {hasCenterContent && (
          <div className="flex h-full w-full flex-col items-center justify-center px-1 text-center">
            {centerValue !== undefined && (
              <span className="font-mono text-[11px] font-semibold leading-tight text-text-primary">
                {centerValue}
              </span>
            )}
            {centerLabel !== undefined && (
              <span className="mt-0.5 max-w-full truncate text-[9px] leading-tight text-text-muted">
                {centerLabel}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export function FlintRadialGauge({
  value,
  ariaLabel,
  color = "currentColor",
  trackColor = "var(--color-surface-hover, #1e1e2e)",
  size = 56,
  strokeWidth = 5,
  decorative = false,
  className,
}: FlintRadialGaugeProps) {
  const clampedValue = Math.min(100, Math.max(0, Number.isFinite(value) ? value : 0))
  const center = size / 2
  const radius = Math.max(1, (size - strokeWidth - 3) / 2)
  const circumference = 2 * Math.PI * radius
  const filled = (clampedValue / 100) * circumference

  return (
    <svg
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : ariaLabel}
      aria-hidden={decorative ? "true" : undefined}
      data-flint-chart="radial-gauge"
      viewBox={`0 0 ${size} ${size}`}
      className={cn("block", className)}
      style={{ width: size, height: size, transform: "rotate(-90deg)" }}
    >
      <circle
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke={trackColor}
        strokeWidth={strokeWidth}
        vectorEffect="non-scaling-stroke"
        aria-hidden="true"
      />
      <circle
        data-gauge-value={clampedValue.toFixed(0)}
        cx={center}
        cy={center}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeDasharray={`${filled.toFixed(2)} ${circumference.toFixed(2)}`}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        aria-hidden="true"
        style={{ transition: "stroke-dasharray 0.6s ease" }}
      />
    </svg>
  )
}

export function FlintRankedBarList({
  entries,
  ariaLabel,
  valueFormatter,
  maxValue,
  className,
}: FlintRankedBarListProps) {
  const visible = entries.filter((entry) => Number.isFinite(entry.value))
  const max = Number.isFinite(maxValue) && Number(maxValue) > 0
    ? Number(maxValue)
    : Math.max(...visible.map((entry) => Math.abs(entry.value)), 1)

  return (
    <div
      role="list"
      aria-label={ariaLabel}
      data-flint-chart="ranked-bar-list"
      className={cn("space-y-2", className)}
    >
      {visible.map((entry) => {
        const width = Math.max(4, (Math.abs(entry.value) / max) * 100)
        return (
          <div key={entry.label} role="listitem" className="space-y-1">
            <div className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-text-secondary">{entry.label}</span>
              <span className="font-mono tabular-nums text-text-primary">{valueFormatter(entry.value)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-elevated" aria-hidden="true">
              <div
                data-ranked-bar-fill={entry.label}
                className="h-full rounded-full"
                style={{ width: `${width}%`, backgroundColor: entry.color ?? "currentColor" }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function FlintLinearMeter({
  value,
  ariaLabel,
  minValue = 0,
  maxValue = 100,
  fillColor = "var(--color-primary, #818cf8)",
  trackColor = "var(--color-surface-elevated, rgba(255,255,255,0.10))",
  marker = false,
  markerColor = "var(--color-text-primary, #ffffff)",
  heightClassName = "h-2",
  className,
}: FlintLinearMeterProps) {
  const safeMin = Number.isFinite(minValue) ? minValue : 0
  const safeMax = Number.isFinite(maxValue) && maxValue > safeMin ? maxValue : safeMin + 100
  const safeValue = Number.isFinite(value) ? value : safeMin
  const percent = Math.min(100, Math.max(0, ((safeValue - safeMin) / (safeMax - safeMin)) * 100))

  return (
    <div
      role="img"
      aria-label={ariaLabel}
      data-flint-chart="linear-meter"
      className={cn("relative w-full rounded-full", heightClassName, className)}
      style={{ background: trackColor }}
    >
      <div
        data-linear-meter-fill
        className="absolute left-0 top-0 h-full rounded-full transition-[width] duration-300 ease-out"
        style={{ width: `${percent}%`, background: fillColor }}
        aria-hidden="true"
      />
      {marker && (
        <span
          data-linear-meter-marker
          className="absolute top-1/2 block h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-primary shadow"
          style={{ left: `${percent}%`, background: markerColor }}
          aria-hidden="true"
        />
      )}
    </div>
  )
}

export function FlintDivergingBarList({
  entries,
  ariaLabel,
  valueFormatter = (value) => value.toLocaleString("en-IN"),
  leftHeading,
  rightHeading,
  leftColor = "rgba(239, 68, 68, 0.65)",
  rightColor = "rgba(16, 185, 129, 0.65)",
  maxValue,
  className,
}: FlintDivergingBarListProps) {
  const visible = entries.map((entry) => ({
    ...entry,
    leftValue: Number.isFinite(entry.leftValue) ? Math.max(0, entry.leftValue) : 0,
    rightValue: Number.isFinite(entry.rightValue) ? Math.max(0, entry.rightValue) : 0,
  }))
  const max = Number.isFinite(maxValue) && Number(maxValue) > 0
    ? Number(maxValue)
    : Math.max(...visible.flatMap((entry) => [entry.leftValue, entry.rightValue]), 1)

  return (
    <div
      role="list"
      aria-label={ariaLabel}
      data-flint-chart="diverging-bar-list"
      className={cn("space-y-1", className)}
    >
      {(leftHeading || rightHeading) && (
        <div className="grid grid-cols-[4rem_1fr_5rem_1fr_4rem] items-center gap-2 px-1 text-xxs text-text-muted">
          <span className="text-right">{leftHeading}</span>
          <span />
          <span className="text-center">Strike</span>
          <span />
          <span>{rightHeading}</span>
        </div>
      )}
      {visible.map((entry) => {
        const leftWidth = Math.min(100, Math.max(0, (entry.leftValue / max) * 100))
        const rightWidth = Math.min(100, Math.max(0, (entry.rightValue / max) * 100))
        const leftText = entry.leftLabel ?? (entry.leftValue > 0 ? valueFormatter(entry.leftValue) : "")
        const rightText = entry.rightLabel ?? (entry.rightValue > 0 ? valueFormatter(entry.rightValue) : "")

        return (
          <div
            key={entry.label}
            role="listitem"
            className="grid grid-cols-[4rem_1fr_5rem_1fr_4rem] items-center gap-2 px-1 py-0.5"
          >
            <span className="truncate text-right font-mono text-xxs text-text-muted">{leftText}</span>
            <div className="relative h-4 overflow-hidden rounded-l bg-surface-elevated">
              <div
                data-diverging-bar-side="left"
                className="absolute right-0 top-0 h-full rounded-l transition-[width] duration-300 ease-out"
                style={{ width: `${leftWidth}%`, minWidth: entry.leftValue > 0 ? "2px" : undefined, backgroundColor: leftColor }}
                title={leftText}
                aria-hidden="true"
              />
            </div>
            <span className="text-center font-mono text-xs text-text-muted">{entry.label}</span>
            <div className="relative h-4 overflow-hidden rounded-r bg-surface-elevated">
              <div
                data-diverging-bar-side="right"
                className="absolute left-0 top-0 h-full rounded-r transition-[width] duration-300 ease-out"
                style={{ width: `${rightWidth}%`, minWidth: entry.rightValue > 0 ? "2px" : undefined, backgroundColor: rightColor }}
                title={rightText}
                aria-hidden="true"
              />
            </div>
            <span className="truncate font-mono text-xxs text-text-muted">{rightText}</span>
          </div>
        )
      })}
    </div>
  )
}

export function FlintWeightedHeatmap({
  entries,
  ariaLabel,
  minWidthPercent = 12,
  maxWidthPercent = 28,
  className,
}: FlintWeightedHeatmapProps) {
  const visible = entries.map((entry) => ({
    ...entry,
    weight: Number.isFinite(entry.weight) ? Math.max(0, entry.weight) : 0,
  }))
  const totalWeight = Math.max(visible.reduce((sum, entry) => sum + entry.weight, 0), 1)

  return (
    <div
      role="list"
      aria-label={ariaLabel}
      data-flint-chart="weighted-heatmap"
      className={cn("flex flex-wrap gap-1.5", className)}
    >
      {visible.map((entry) => {
        const weightPercent = (entry.weight / totalWeight) * 100
        const widthPercent = Math.max(minWidthPercent, Math.min(maxWidthPercent, weightPercent * 0.8))
        const height = weightPercent >= 10 ? 84 : weightPercent >= 6 ? 72 : 62

        return (
          <div
            key={entry.id}
            role="listitem"
            data-weighted-heatmap-tile={entry.id}
            className="flex shrink-0 cursor-default flex-col justify-between rounded-md p-2.5 transition-opacity hover:opacity-90"
            style={{
              backgroundColor: entry.color,
              width: `calc(${widthPercent}% - 6px)`,
              height,
            }}
            title={`${entry.label}: ${entry.valueLabel}`}
          >
            <div className="truncate text-xs font-medium leading-tight text-white/75">
              {entry.label}
            </div>
            <div className="flex items-end justify-between gap-1">
              <div className="font-mono text-sm font-bold" style={{ color: entry.textColor }}>
                {entry.valueLabel}
              </div>
              {entry.detailLabel && (
                <div className="font-mono text-xxs text-white/40">
                  {entry.detailLabel}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export const FLINT_CHART_KEYBOARD_TOOL_MAP: Readonly<Record<string, FlintChartDrawToolId>> = {
  "1": "cursor",
  "2": "trendline",
  "3": "ray",
  "4": "hline",
  "5": "vline",
  "6": "fib",
  "7": "rect",
  "8": "text",
}

export const FLINT_CHART_DRAW_TOOL_GROUPS: readonly FlintChartToolGroup[] = [
  {
    key: "cursor",
    tools: [
      { id: "cursor", label: "Cursor", icon: <Crosshair size={ICON_SIZE} /> },
      { id: "eraser", label: "Eraser", icon: <Eraser size={ICON_SIZE} /> },
    ],
  },
  {
    key: "lines",
    tools: [
      { id: "trendline", label: "Trend Line", icon: <TrendingUp size={ICON_SIZE} /> },
      { id: "ray", label: "Ray", icon: <ArrowRight size={ICON_SIZE} /> },
      { id: "extended_line", label: "Extended Line", icon: <Infinity size={ICON_SIZE} /> },
      { id: "hline", label: "Horizontal Line", icon: <Minus size={ICON_SIZE} /> },
      {
        id: "vline",
        label: "Vertical Line",
        icon: <AlignJustify size={ICON_SIZE} style={{ transform: "rotate(90deg)" }} />,
      },
      { id: "parallel_channel", label: "Parallel Channel", icon: <LayoutGrid size={ICON_SIZE} /> },
    ],
  },
  {
    key: "fib",
    tools: [
      { id: "fib", label: "Fib Retracement", icon: <Triangle size={ICON_SIZE} /> },
      { id: "fib_extension", label: "Fib Extension", icon: <TrendingDown size={ICON_SIZE} /> },
    ],
  },
  {
    key: "shapes",
    tools: [
      { id: "rect", label: "Rectangle", icon: <Square size={ICON_SIZE} /> },
      { id: "circle", label: "Circle", icon: <Circle size={ICON_SIZE} /> },
      { id: "brush", label: "Brush", icon: <Pen size={ICON_SIZE} /> },
    ],
  },
  {
    key: "text",
    tools: [
      { id: "text", label: "Text", icon: <Type size={ICON_SIZE} /> },
      { id: "callout", label: "Callout", icon: <MessageSquare size={ICON_SIZE} /> },
      { id: "price_label", label: "Price Label", icon: <Tag size={ICON_SIZE} /> },
    ],
  },
  {
    key: "patterns",
    tools: [
      { id: "elliott_impulse", label: "Elliott Impulse", icon: <GitBranch size={ICON_SIZE} /> },
      { id: "elliott_correction", label: "Elliott Correction", icon: <GitMerge size={ICON_SIZE} /> },
    ],
  },
  {
    key: "prediction",
    tools: [
      { id: "long_position", label: "Long Position", icon: <TrendingUp size={ICON_SIZE} /> },
      { id: "short_position", label: "Short Position", icon: <TrendingDown size={ICON_SIZE} /> },
      { id: "measure", label: "Measure", icon: <Ruler size={ICON_SIZE} /> },
    ],
  },
]

export function getFlintChartWorkspaceLayout(width: number): FlintChartWorkspaceLayout {
  const compact = Number.isFinite(width) && width > 0 && width < FLINT_CHART_COMPACT_WORKSPACE_WIDTH
  return {
    compact,
    toolbarOrientation: compact ? "horizontal" : "vertical",
  }
}

function readFiniteNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const numberValue = Number(value)
    return Number.isFinite(numberValue) ? numberValue : null
  }
  return null
}

function readNumericField(value: unknown, field: string): number | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return readFiniteNumber((value as Record<string, unknown>)[field])
}

export function getFlintChartCrosshairReadout<TSeries = unknown, TTime = unknown>(
  event: FlintChartCrosshairEventLike<TSeries, TTime> | null | undefined,
  candleSeries: TSeries,
  volumeSeries?: TSeries | null,
): FlintChartCrosshairReadoutState<TTime> | null {
  if (!event || event.time == null || !event.seriesData) return null

  const candle = event.seriesData.get(candleSeries)
  const open = readNumericField(candle, "open")
  const high = readNumericField(candle, "high")
  const low = readNumericField(candle, "low")
  const close = readNumericField(candle, "close")

  if (open == null || high == null || low == null || close == null) {
    return null
  }

  const volume =
    volumeSeries == null
      ? null
      : readNumericField(event.seriesData.get(volumeSeries), "value")

  return {
    time: event.time,
    open,
    high,
    low,
    close,
    volume,
    bull: close >= open,
  }
}

function formatPrice(value: number | null | undefined): string {
  if (value == null) return "--"
  return Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function formatVolume(value: number | null): string {
  if (value == null) return "--"
  if (value >= 1_00_00_000) return `${(value / 1_00_00_000).toFixed(2)}Cr`
  if (value >= 1_00_000) return `${(value / 1_00_000).toFixed(2)}L`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`
  return String(value)
}

function canUseLocalStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined"
}

function isEditableChartTarget(target: EventTarget | null | undefined): boolean {
  if (!target || typeof HTMLElement === "undefined" || !(target instanceof HTMLElement)) {
    return false
  }

  const tagName = target.tagName.toLowerCase()
  return (
    target.isContentEditable ||
    tagName === "input" ||
    tagName === "textarea" ||
    tagName === "select" ||
    target.getAttribute("role") === "textbox"
  )
}

export function getFlintChartKeyboardAction(
  event: FlintChartKeyboardEventLike,
): FlintChartKeyboardAction | null {
  if (isEditableChartTarget(event.target)) return null

  const key = event.key.toLowerCase()
  const hasCommandModifier = event.ctrlKey === true || event.metaKey === true
  if (event.altKey) return null

  if (event.key === "Escape") return { kind: "cancel-drawing" }
  if (hasCommandModifier && key === "z") return { kind: "undo-drawing" }

  if (event.key === "Delete" || event.key === "Backspace") {
    return event.shiftKey ? { kind: "clear-all-drawings" } : { kind: "delete-last-drawing" }
  }

  if (!hasCommandModifier && !event.shiftKey && FLINT_CHART_KEYBOARD_TOOL_MAP[key]) {
    return { kind: "set-tool", tool: FLINT_CHART_KEYBOARD_TOOL_MAP[key] }
  }

  return null
}

function safeReadJson(value: string | null): unknown {
  if (!value) return null
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function implementedToolIds<TTool extends string>(
  groups: readonly FlintChartToolGroup<TTool>[],
): Set<TTool> {
  return new Set(groups.flatMap((group) => group.tools.filter((tool) => !tool.comingSoon).map((tool) => tool.id)))
}

function getDefaultToolForGroup<TTool extends string>(
  group: FlintChartToolGroup<TTool>,
): FlintChartToolDefinition<TTool> | undefined {
  return group.tools.find((tool) => !tool.comingSoon) ?? group.tools[0]
}

function loadActiveTools<TTool extends string>(
  storageKey: string,
  groups: readonly FlintChartToolGroup<TTool>[],
): Record<string, TTool> {
  if (!canUseLocalStorage()) return {}
  const parsed = safeReadJson(window.localStorage.getItem(storageKey))
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {}
  const allowed = implementedToolIds(groups)
  const next: Record<string, TTool> = {}
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value === "string" && allowed.has(value as TTool)) {
      next[key] = value as TTool
    }
  }
  return next
}

function loadFavourites<TTool extends string>(
  storageKey: string,
  groups: readonly FlintChartToolGroup<TTool>[],
): TTool[] {
  if (!canUseLocalStorage()) return []
  const parsed = safeReadJson(window.localStorage.getItem(storageKey))
  if (!Array.isArray(parsed)) return []
  const allowed = implementedToolIds(groups)
  return parsed.filter((value): value is TTool =>
    typeof value === "string" && allowed.has(value as TTool),
  )
}

function saveJson(storageKey: string, value: unknown): void {
  if (!canUseLocalStorage()) return
  try {
    window.localStorage.setItem(storageKey, JSON.stringify(value))
  } catch {
    // Ignore storage quota/privacy failures; the toolbar still works.
  }
}

function Tooltip({
  text,
  children,
  side = "right",
}: {
  text: string
  children: ReactNode
  side?: "right" | "bottom"
}) {
  const [visible, setVisible] = useState(false)
  return (
    <div
      className="relative flex items-center justify-center"
      onMouseEnter={() => setVisible(true)}
      onMouseLeave={() => setVisible(false)}
    >
      {children}
      {visible && (
        <div
          className={cn(
            "pointer-events-none absolute z-200 whitespace-nowrap rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-primary shadow-2xl",
            side === "bottom"
              ? "left-1/2 top-full mt-2 -translate-x-1/2"
              : "left-full top-1/2 ml-2 -translate-y-1/2",
          )}
        >
          {text}
        </div>
      )}
    </div>
  )
}

export function FlintChartLegend({ legend, className }: FlintChartLegendProps) {
  const closeClass = legend.bull ? "text-profit" : "text-loss"

  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded border border-border-default/70 bg-surface-card/85 px-2 py-0.5 shadow-sm",
        className,
      )}
    >
      <span className="text-xxs uppercase text-text-muted">O</span>
      <span className="font-mono text-xs text-text-primary">{formatPrice(legend.open)}</span>
      <span className="text-xxs uppercase text-text-muted">H</span>
      <span className="font-mono text-xs text-profit">{formatPrice(legend.high)}</span>
      <span className="text-xxs uppercase text-text-muted">L</span>
      <span className="font-mono text-xs text-loss">{formatPrice(legend.low)}</span>
      <span className="text-xxs uppercase text-text-muted">C</span>
      <span className={cn("font-mono text-xs", closeClass)}>{formatPrice(legend.close)}</span>
      {legend.volume != null && (
        <>
          <span className="text-xxs uppercase text-text-muted">V</span>
          <span className="font-mono text-xs text-text-primary">{formatVolume(legend.volume)}</span>
        </>
      )}
    </div>
  )
}

export function FlintChartIntervalPills({
  intervals,
  active,
  onSelect,
  maxVisible,
  size = "standard",
  className,
}: FlintChartIntervalPillsProps) {
  const visible = typeof maxVisible === "number" ? intervals.slice(0, maxVisible) : intervals
  const compact = size === "compact"

  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {visible.map((interval) => (
        <button
          key={interval.value}
          type="button"
          onClick={() => onSelect(interval.value)}
          className={cn(
            "rounded border border-transparent font-mono transition-colors",
            compact ? "px-1.5 py-0.5 text-xxs" : "px-2 py-1 text-xs",
            active === interval.value
              ? "border-accent/40 bg-accent/15 text-accent"
              : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
          )}
          aria-pressed={active === interval.value}
        >
          {interval.label}
        </button>
      ))}
    </div>
  )
}

export function getFlintChartDrawInstruction<TTool extends string>({
  drawMode,
  pendingPoint,
  pendingPoints,
  awaitingText,
  twoClickTools = FLINT_CHART_TWO_CLICK_TOOLS as readonly TTool[],
  threeClickTools = FLINT_CHART_THREE_CLICK_TOOLS as readonly TTool[],
}: Pick<
  FlintChartDrawStatusProps<TTool>,
  "drawMode" | "pendingPoint" | "pendingPoints" | "awaitingText" | "twoClickTools" | "threeClickTools"
>): string | null {
  if (!drawMode) return null
  if ((drawMode === "text" || drawMode === "callout") && awaitingText != null) return "Type text below"
  if (drawMode === "eraser") return "Click drawing to erase"
  if (drawMode === "brush") return "Drag to draw"
  if (threeClickTools.includes(drawMode)) {
    const pendingCount = pendingPoints?.length ?? (pendingPoint == null ? 0 : 1)
    if (drawMode === "elliott_impulse" || drawMode === "elliott_correction") {
      const elliottMode = drawMode as "elliott_impulse" | "elliott_correction"
      const labels = getFlintChartElliottWaveLabels(elliottMode)
      return `Click wave ${labels[pendingCount] ?? labels.at(-1) ?? pendingCount}`
    }
    if (drawMode === "long_position" || drawMode === "short_position") {
      if (pendingCount <= 0) return "Click entry point"
      if (pendingCount === 1) return "Click target point"
      return "Click stop point"
    }
    if (pendingCount <= 0) return "Click first point"
    if (pendingCount === 1) return "Click second point"
    if (drawMode === "fib_extension") return "Click extension anchor"
    return "Click channel width"
  }
  if (twoClickTools.includes(drawMode)) {
    return pendingPoint == null ? "Click first point" : "Click second point"
  }
  return "Click chart to place"
}

export function FlintChartDrawStatus<TTool extends string = FlintChartDrawToolId>({
  drawMode,
  drawingCount,
  pendingPoint = null,
  pendingPoints = [],
  awaitingText = null,
  twoClickTools = FLINT_CHART_TWO_CLICK_TOOLS as readonly TTool[],
  threeClickTools = FLINT_CHART_THREE_CLICK_TOOLS as readonly TTool[],
  className,
}: FlintChartDrawStatusProps<TTool>) {
  const instruction = getFlintChartDrawInstruction({
    drawMode,
    pendingPoint,
    pendingPoints,
    awaitingText,
    twoClickTools,
    threeClickTools,
  })

  if (drawingCount === 0 && !instruction) return null

  return (
    <div className={cn("flex items-center gap-2", className)}>
      {drawingCount > 0 && (
        <span className="text-xxs text-text-muted">
          {drawingCount} drawing{drawingCount !== 1 ? "s" : ""}
        </span>
      )}
      {instruction && (
        <span className="text-xxs text-accent animate-pulse">{instruction}</span>
      )}
    </div>
  )
}

export function FlintChartDrawingList<TTime = unknown>({
  drawings,
  selectedDrawingId,
  onSelectDrawing,
  onDeleteDrawing,
  className,
}: FlintChartDrawingListProps<TTime>) {
  const summaries = useMemo(() => createFlintChartDrawingSummaries(drawings), [drawings])
  if (summaries.length === 0) return null

  return (
    <div
      role="list"
      aria-label="Chart drawings"
      className={cn(
        "flex min-w-0 items-center gap-1 overflow-x-auto overflow-y-hidden rounded border border-border-default/70 bg-surface-card/70 px-1 py-0.5",
        className,
      )}
    >
      {summaries.map((summary) => {
        const selected = summary.id === selectedDrawingId
        return (
          <div
            key={summary.id}
            role="listitem"
            className={cn(
              "flex min-w-28 max-w-48 shrink-0 items-center rounded border transition-colors",
              selected
                ? "border-accent/50 bg-accent/15"
                : "border-border-default/60 bg-surface-base/70 hover:border-border-strong",
            )}
          >
            <button
              type="button"
              aria-label={`Select ${summary.label}`}
              aria-pressed={selected}
              onClick={() => onSelectDrawing(summary.id)}
              className="flex min-w-0 flex-1 flex-col px-2 py-1 text-left"
            >
              <span className={cn(
                "truncate text-xxs font-medium",
                selected ? "text-accent" : "text-text-secondary",
              )}
              >
                {summary.label}
              </span>
              <span className="truncate font-mono text-[10px] leading-tight text-text-muted">
                {summary.detail}
              </span>
              {(summary.locked || summary.hidden) && (
                <span className="mt-0.5 flex items-center gap-1 text-[9px] uppercase tracking-wide">
                  {summary.locked && (
                    <span className="rounded bg-surface-hover px-1 text-text-muted">Locked</span>
                  )}
                  {summary.hidden && (
                    <span className="rounded bg-surface-hover px-1 text-text-muted">Hidden</span>
                  )}
                </span>
              )}
            </button>
            <button
              type="button"
              aria-label={`Delete ${summary.label}`}
              title={summary.locked ? "Locked drawing cannot be deleted" : `Delete ${summary.label}`}
              disabled={summary.locked}
              onClick={(event) => {
                event.stopPropagation()
                if (summary.locked) return
                onDeleteDrawing(summary.id)
              }}
              className="mr-1 flex h-5 w-5 shrink-0 items-center justify-center rounded text-text-muted transition-colors hover:bg-surface-hover hover:text-loss disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-text-muted"
            >
              <Trash2 size={10} />
            </button>
          </div>
        )
      })}
    </div>
  )
}

export function FlintChartDrawingStyleEditor<TTime = unknown>({
  drawing,
  value,
  onChange,
  className,
}: FlintChartDrawingStyleEditorProps<TTime>) {
  if (!drawing) return null
  const disabled = drawing.locked === true

  return (
    <div
      aria-label="Selected drawing style"
      className={cn(
        "flex shrink-0 items-center gap-1 rounded border border-border-default/70 bg-surface-card/70 px-1 py-0.5",
        className,
      )}
    >
      <div className="flex items-center gap-0.5">
        {FLINT_CHART_DRAWING_STYLE_COLORS.map((color) => (
          <button
            key={color.value}
            type="button"
            aria-label={`Set drawing colour ${color.label}`}
            aria-pressed={value.color === color.value}
            title={color.label}
            disabled={disabled}
            onClick={() => !disabled && onChange({ color: color.value })}
            className={cn(
              "h-5 w-5 rounded-sm border transition-transform hover:scale-105 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100",
              value.color === color.value ? "border-text-primary" : "border-border-default",
            )}
            style={{ backgroundColor: color.value }}
          />
        ))}
      </div>

      <div className="mx-0.5 h-4 w-px bg-border-default" />

      <div className="flex items-center gap-0.5">
        {FLINT_CHART_DRAWING_LINE_STYLES.map((lineStyle) => (
          <button
            key={lineStyle}
            type="button"
            aria-label={`Set drawing line style ${lineStyle}`}
            aria-pressed={value.lineStyle === lineStyle}
            disabled={disabled}
            onClick={() => !disabled && onChange({ lineStyle })}
            className={cn(
              "flex h-5 w-7 items-center justify-center rounded border text-[10px] leading-none transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              value.lineStyle === lineStyle
                ? "border-accent/50 bg-accent/15 text-accent"
                : "border-border-default text-text-muted hover:bg-surface-hover hover:text-text-primary",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "block h-0 w-4 border-t",
                lineStyle === "dotted" && "border-dotted",
                lineStyle === "dashed" && "border-dashed",
              )}
            />
          </button>
        ))}
      </div>

      <div className="mx-0.5 h-4 w-px bg-border-default" />

      <div className="flex items-center gap-0.5">
        {FLINT_CHART_DRAWING_LINE_WIDTHS.map((lineWidth: FlintChartDrawingLineWidth) => (
          <button
            key={lineWidth}
            type="button"
            aria-label={`Set drawing line width ${lineWidth}`}
            aria-pressed={value.lineWidth === lineWidth}
            disabled={disabled}
            onClick={() => !disabled && onChange({ lineWidth })}
            className={cn(
              "flex h-5 w-5 items-center justify-center rounded border font-mono text-[10px] transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              value.lineWidth === lineWidth
                ? "border-accent/50 bg-accent/15 text-accent"
                : "border-border-default text-text-muted hover:bg-surface-hover hover:text-text-primary",
            )}
          >
            {lineWidth}
          </button>
        ))}
      </div>
    </div>
  )
}

export function FlintChartDrawingInspector<TTime = unknown>({
  drawing,
  value,
  onStyleChange,
  onToggleHidden,
  onToggleLocked,
  onDeleteDrawing,
  className,
}: FlintChartDrawingInspectorProps<TTime>) {
  if (!drawing) return null

  const label = getFlintChartDrawingLabel(drawing)
  const detail = getFlintChartDrawingDetail(drawing)
  const hidden = drawing.hidden === true
  const locked = drawing.locked === true

  const actionButtonClass =
    "flex h-6 w-6 shrink-0 items-center justify-center rounded border border-border-default text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-text-muted"

  return (
    <div
      aria-label="Selected drawing inspector"
      className={cn(
        "flex min-w-0 shrink-0 items-center gap-1 overflow-x-auto overflow-y-hidden rounded border border-border-default/70 bg-surface-card/70 px-1 py-0.5",
        className,
      )}
    >
      <div className="flex min-w-32 shrink-0 flex-col px-1 leading-tight">
        <span className="text-[9px] uppercase tracking-wide text-text-muted">Selected drawing</span>
        <span className="max-w-44 truncate text-xxs font-medium text-accent">{label}</span>
        <span className="max-w-44 truncate font-mono text-[10px] text-text-muted">{detail}</span>
        {(locked || hidden) && (
          <span className="mt-0.5 flex items-center gap-1 text-[9px] uppercase tracking-wide">
            {locked && <span className="rounded bg-surface-hover px-1 text-text-muted">Locked</span>}
            {hidden && <span className="rounded bg-surface-hover px-1 text-text-muted">Hidden</span>}
          </span>
        )}
      </div>

      <FlintChartDrawingStyleEditor
        drawing={drawing}
        value={value}
        onChange={onStyleChange}
        className="border-0 bg-transparent px-0 py-0"
      />

      <div className="mx-0.5 h-5 w-px shrink-0 bg-border-default" />

      <button
        type="button"
        aria-label={`${hidden ? "Show" : "Hide"} ${label}`}
        aria-pressed={hidden}
        title={hidden ? "Show drawing" : "Hide drawing"}
        onClick={() => onToggleHidden(drawing.id, !hidden)}
        className={cn(actionButtonClass, hidden && "border-accent/50 bg-accent/15 text-accent")}
      >
        {hidden ? <Eye size={12} /> : <EyeOff size={12} />}
      </button>

      <button
        type="button"
        aria-label={`${locked ? "Unlock" : "Lock"} ${label}`}
        aria-pressed={locked}
        title={locked ? "Unlock drawing" : "Lock drawing"}
        onClick={() => onToggleLocked(drawing.id, !locked)}
        className={cn(actionButtonClass, locked && "border-accent/50 bg-accent/15 text-accent")}
      >
        {locked ? <Unlock size={12} /> : <Lock size={12} />}
      </button>

      <button
        type="button"
        aria-label={`Delete selected ${label}`}
        title={locked ? "Locked drawing cannot be deleted" : `Delete ${label}`}
        disabled={locked}
        onClick={() => !locked && onDeleteDrawing(drawing.id)}
        className={cn(actionButtonClass, "hover:text-loss")}
      >
        <Trash2 size={12} />
      </button>
    </div>
  )
}

export function FlintChartDrawingToolbar<TTool extends string = FlintChartDrawToolId>({
  drawMode,
  onToggle,
  onClearAll,
  orientation = "vertical",
  groups = FLINT_CHART_DRAW_TOOL_GROUPS as readonly FlintChartToolGroup<TTool>[],
  storageKeyPrefix = "flinttrade:chart-drawing-toolbar",
  onHideAll,
  onLockAll,
  drawingsHidden = false,
  drawingsLocked = false,
  className,
}: FlintChartDrawingToolbarProps<TTool>) {
  const activeStorageKey = `${storageKeyPrefix}:active`
  const favouritesStorageKey = `${storageKeyPrefix}:favourites`
  const toolbarRef = useRef<HTMLDivElement>(null)
  const comingSoonTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [activeTools, setActiveTools] = useState<Record<string, TTool>>(() =>
    loadActiveTools(activeStorageKey, groups),
  )
  const [favourites, setFavourites] = useState<TTool[]>(() =>
    loadFavourites(favouritesStorageKey, groups),
  )
  const [openGroup, setOpenGroup] = useState<string | null>(null)
  const [comingSoonTip, setComingSoonTip] = useState<string | null>(null)
  const horizontal = orientation === "horizontal"

  const groupedTools = useMemo(() => groups.flatMap((group) => group.tools), [groups])

  useEffect(() => {
    function handleOutside(event: MouseEvent) {
      if (toolbarRef.current && !toolbarRef.current.contains(event.target as Node)) {
        setOpenGroup(null)
      }
    }
    document.addEventListener("mousedown", handleOutside)
    return () => document.removeEventListener("mousedown", handleOutside)
  }, [])

  useEffect(() => { saveJson(activeStorageKey, activeTools) }, [activeStorageKey, activeTools])
  useEffect(() => { saveJson(favouritesStorageKey, favourites) }, [favouritesStorageKey, favourites])

  const showComingSoon = useCallback((label: string) => {
    if (comingSoonTimer.current) clearTimeout(comingSoonTimer.current)
    setComingSoonTip(`${label} - coming soon`)
    comingSoonTimer.current = setTimeout(() => setComingSoonTip(null), 2000)
  }, [])

  const handleToolClick = useCallback((tool: FlintChartToolDefinition<TTool>, groupKey: string) => {
    if (tool.comingSoon) {
      showComingSoon(tool.label)
      return
    }
    setActiveTools((prev) => ({ ...prev, [groupKey]: tool.id }))
    setOpenGroup(null)
    onToggle(tool.id)
  }, [onToggle, showComingSoon])

  const toggleFavourite = useCallback((id: TTool) => {
    setFavourites((prev) =>
      prev.includes(id) ? prev.filter((tool) => tool !== id) : [...prev, id],
    )
  }, [])

  function findToolDef(id: TTool): FlintChartToolDefinition<TTool> | undefined {
    return groupedTools.find((tool) => tool.id === id)
  }

  function renderToolMenuItem(tool: FlintChartToolDefinition<TTool>, groupKey: string) {
    const isFavourite = favourites.includes(tool.id)
    const isSelected = drawMode === tool.id

    return (
      <div
        key={tool.id}
        role="menuitem"
        className={cn(
          "grid grid-cols-[1fr_auto] items-center gap-1 rounded transition-colors",
          tool.comingSoon
            ? "opacity-50"
            : isSelected
              ? "bg-accent/15 text-accent"
              : "text-text-secondary hover:bg-surface-hover hover:text-text-primary",
        )}
      >
        <button
          type="button"
          disabled={tool.comingSoon}
          onClick={() => handleToolClick(tool, groupKey)}
          className="flex min-w-0 items-center gap-2 px-2 py-1 text-left disabled:cursor-not-allowed"
        >
          <span className="shrink-0" aria-hidden="true">{tool.icon}</span>
          <span className="flex-1 whitespace-nowrap text-xs">{tool.label}</span>
          {tool.comingSoon && <span className="text-xxs text-text-muted">soon</span>}
        </button>
        {!tool.comingSoon && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              toggleFavourite(tool.id)
            }}
            className={cn(
              "mr-1 rounded p-0.5 transition-colors",
              isFavourite ? "text-amber-400 hover:text-amber-300" : "text-text-muted hover:text-text-primary",
            )}
            title={isFavourite ? "Remove from favourites" : "Add to favourites"}
            aria-label={isFavourite ? "Remove from favourites" : "Add to favourites"}
          >
            <Star size={9} fill={isFavourite ? "currentColor" : "none"} />
          </button>
        )}
      </div>
    )
  }

  function renderToolRow(group: FlintChartToolGroup<TTool>) {
    const defaultFace = getDefaultToolForGroup(group)
    const faceId = activeTools[group.key] ?? defaultFace?.id
    const faceDef = group.tools.find((tool) => tool.id === faceId && !tool.comingSoon) ?? defaultFace
    if (!faceDef) return null

    const isOpen = openGroup === group.key
    const faceComingSoon = faceDef.comingSoon === true
    const faceLabel = faceComingSoon ? `${faceDef.label} coming soon` : faceDef.label
    const isActive = !faceComingSoon && drawMode === faceDef.id
    const hasArrow = group.tools.length > 1

    return (
      <div
        key={group.key}
        className={cn("relative flex items-center", horizontal ? "w-auto" : "w-full")}
      >
        <Tooltip text={faceLabel} side={horizontal ? "bottom" : "right"}>
          <button
            type="button"
            disabled={faceComingSoon}
            onClick={() => !faceComingSoon && handleToolClick(faceDef, group.key)}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded transition-colors",
              faceComingSoon
                ? "cursor-not-allowed opacity-50 text-text-muted"
                : isActive
                ? "bg-accent/15 text-accent"
                : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
            )}
            aria-label={faceLabel}
            aria-pressed={isActive}
          >
            {faceDef.icon}
          </button>
        </Tooltip>

        {hasArrow && (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              setOpenGroup(isOpen ? null : group.key)
            }}
            className="-ml-0.5 flex h-5 w-3 items-center justify-center text-text-muted transition-colors hover:text-text-primary"
            aria-label={`Expand ${group.label ?? group.key} tools`}
            aria-expanded={isOpen}
          >
            <ChevronRight size={8} />
          </button>
        )}

        {isOpen && (
          <div
            role="menu"
            className={cn(
              "absolute z-150 min-w-[8.75rem] rounded-lg border border-border-default bg-surface-card p-1 shadow-2xl",
              horizontal ? "left-0 top-full mt-1" : "left-full top-0 ml-1",
            )}
          >
            <div className="mb-0.5 select-none px-2 py-0.5 text-xxs uppercase tracking-wider text-text-muted">
              {group.label ?? group.key}
            </div>
            {group.tools.map((tool) => renderToolMenuItem(tool, group.key))}
          </div>
        )}
      </div>
    )
  }

  function renderFavouritesRow() {
    if (favourites.length === 0) return null
    const isOpen = openGroup === "favourites"

    return (
      <div className={cn("relative flex items-center", horizontal ? "w-auto" : "w-full")}>
        <Tooltip text="Favourites" side={horizontal ? "bottom" : "right"}>
          <button
            type="button"
            onClick={() => setOpenGroup(isOpen ? null : "favourites")}
            className="flex h-7 w-7 items-center justify-center rounded text-amber-400 transition-colors hover:bg-surface-hover"
            aria-label="Favourites"
            aria-expanded={isOpen}
          >
            <Star size={ICON_SIZE} fill="currentColor" />
          </button>
        </Tooltip>

        {isOpen && (
          <div
            role="menu"
            className={cn(
              "absolute z-150 min-w-[8.75rem] rounded-lg border border-border-default bg-surface-card p-1 shadow-2xl",
              horizontal ? "left-0 top-full mt-1" : "left-full top-0 ml-1",
            )}
          >
            <div className="mb-0.5 select-none px-2 py-0.5 text-xxs uppercase tracking-wider text-text-muted">
              Favourites
            </div>
            {favourites.map((id) => {
              const tool = findToolDef(id)
              if (!tool) return null
              const groupKey = groups.find((group) => group.tools.some((candidate) => candidate.id === id))?.key ?? ""
              return renderToolMenuItem(tool, groupKey)
            })}
          </div>
        )}
      </div>
    )
  }

  const actions = [
    {
      key: "lock",
      label: "Lock drawings",
      icon: <Lock size={ICON_SIZE} />,
      onClick: () => { onLockAll?.(); setOpenGroup(null) },
      destructive: false,
      active: drawingsLocked,
    },
    {
      key: "hide",
      label: "Hide drawings",
      icon: <EyeOff size={ICON_SIZE} />,
      onClick: () => { onHideAll?.(); setOpenGroup(null) },
      destructive: false,
      active: drawingsHidden,
    },
    {
      key: "clear",
      label: "Clear all drawings",
      icon: <Trash2 size={ICON_SIZE} />,
      onClick: () => { onClearAll(); setOpenGroup(null) },
      destructive: true,
      active: false,
    },
  ] as const

  return (
    <div
      ref={toolbarRef}
      role="toolbar"
      aria-label="Drawing tools"
      aria-orientation={orientation}
      data-orientation={orientation}
      className={cn(
        "relative flex shrink-0 select-none items-center gap-0.5 overflow-visible bg-surface-base",
        horizontal
          ? "h-8 w-full flex-row border-b border-border-default px-1 py-0"
          : "w-8 flex-col border-r border-border-default py-1",
        className,
      )}
    >
      {comingSoonTip && (
        <div
          className={cn(
            "pointer-events-none absolute z-200 whitespace-nowrap rounded border border-border-default bg-surface-card px-2 py-1 text-xs text-text-muted shadow-2xl",
            horizontal ? "left-2 top-full mt-2" : "left-full top-2 ml-2",
          )}
        >
          {comingSoonTip}
        </div>
      )}

      {renderFavouritesRow()}
      {favourites.length > 0 && (
        <div className={cn("bg-border-default", horizontal ? "mx-0.5 h-5 w-px" : "mx-1 my-0.5 h-px w-full")} />
      )}

      {groups.map((group, index) => (
        <div
          key={group.key}
          className={cn("flex items-center", horizontal ? "w-auto flex-row" : "w-full flex-col")}
        >
          {renderToolRow(group)}
          {index < groups.length - 1 && (
            <div className={cn("bg-border-default", horizontal ? "mx-0.5 h-5 w-px" : "mx-1 my-0.5 h-px w-full")} />
          )}
        </div>
      ))}

      <div className={cn("bg-border-default", horizontal ? "mx-0.5 h-5 w-px" : "mx-1 my-0.5 h-px w-full")} />

      {actions.map((action) => (
        <Tooltip key={action.key} text={action.label} side={horizontal ? "bottom" : "right"}>
          <button
            type="button"
            onClick={action.onClick}
            className={cn(
              "flex h-7 w-7 items-center justify-center rounded transition-colors",
              action.active
                ? "bg-accent/15 text-accent"
                : action.destructive
                ? "text-text-muted hover:bg-surface-hover hover:text-loss"
                : "text-text-muted hover:bg-surface-hover hover:text-text-primary",
            )}
            aria-label={action.label}
            aria-pressed={action.active}
          >
            {action.icon}
          </button>
        </Tooltip>
      ))}
    </div>
  )
}
