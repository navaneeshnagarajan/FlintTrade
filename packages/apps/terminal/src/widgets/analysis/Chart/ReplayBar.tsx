// ReplayBar — slim control bar rendered below the chart during replay mode.
//
// Layout:  [Play/Pause] [|] [speed pills] [|] [progress scrubber] [|] [Reset] [Live]
//
// Accessibility:
// - role="toolbar" on the outer wrapper
// - Space / k toggles play/pause
// - Left / Right arrow keys step one bar at a time (fine seek)
// - Shift+Left / Shift+Right jump 10%
// - 1/2/3/4 numpad keys set speed 1x/2x/5x/10x

import { useEffect, useRef, useCallback } from "react";
import { Play, Pause, RotateCcw, Radio } from "lucide-react";
import type { ReplaySpeed } from "./useChartReplay";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ReplayBarProps {
  isPlaying: boolean;
  replayIndex: number;
  totalBars: number;
  replaySpeed: ReplaySpeed;
  onPlay: () => void;
  onPause: () => void;
  onReset: () => void;
  onSeek: (index: number) => void;
  onSetSpeed: (speed: ReplaySpeed) => void;
  onExitReplay: () => void;
}

// ---------------------------------------------------------------------------
// Speed selector pills
// ---------------------------------------------------------------------------

const SPEEDS: ReplaySpeed[] = [1, 2, 5, 10];

function SpeedPills({
  active,
  onSelect,
}: {
  active: ReplaySpeed;
  onSelect: (s: ReplaySpeed) => void;
}) {
  return (
    <div className="flex items-center gap-0.5" role="group" aria-label="Playback speed">
      {SPEEDS.map((s) => (
        <button
          key={s}
          onClick={() => onSelect(s)}
          aria-pressed={active === s}
          aria-label={`${s}x speed`}
          className={`px-2 py-0.5 text-xs font-mono rounded transition-colors ${
            active === s
              ? "bg-accent/20 text-accent border border-accent/50"
              : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
          }`}
        >
          {s}x
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress scrubber
// ---------------------------------------------------------------------------

function ProgressScrubber({
  index,
  total,
  onSeek,
}: {
  index: number;
  total: number;
  onSeek: (i: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);

  const pct = total > 1 ? (index / (total - 1)) * 100 : 0;

  const seekFromEvent = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track || total <= 1) return;
      const rect = track.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onSeek(Math.round(ratio * (total - 1)));
    },
    [total, onSeek],
  );

  function handlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId);
    seekFromEvent(e.clientX);
  }

  function handlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (e.buttons !== 1) return;
    seekFromEvent(e.clientX);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowLeft") { e.preventDefault(); onSeek(Math.max(0, index - 1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); onSeek(Math.min(total - 1, index + 1)); }
    else if (e.key === "Home") { e.preventDefault(); onSeek(0); }
    else if (e.key === "End") { e.preventDefault(); onSeek(total - 1); }
  }

  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      <span className="text-xxs font-mono text-text-muted shrink-0 tabular-nums w-8 text-right">
        {index + 1}
      </span>
      {/* Track */}
      <div
        ref={trackRef}
        role="slider"
        aria-label="Replay position"
        aria-valuemin={0}
        aria-valuemax={total - 1}
        aria-valuenow={index}
        tabIndex={0}
        className="relative flex-1 h-1.5 bg-border-default rounded-full cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onKeyDown={handleKeyDown}
      >
        {/* Fill */}
        <div
          className="absolute inset-y-0 left-0 bg-accent rounded-full pointer-events-none"
          style={{ width: `${pct}%` }}
        />
        {/* Thumb */}
        <div
          className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full bg-accent shadow-sm pointer-events-none"
          style={{ left: `${pct}%` }}
        />
      </div>
      <span className="text-xxs font-mono text-text-muted shrink-0 tabular-nums w-8">
        {total}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ReplayBar({
  isPlaying,
  replayIndex,
  totalBars,
  replaySpeed,
  onPlay,
  onPause,
  onReset,
  onSeek,
  onSetSpeed,
  onExitReplay,
}: ReplayBarProps) {
  // Keyboard shortcuts (global while replay bar is mounted)
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      // Guard: ignore when focus is in an input / textarea
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      if (e.key === " " || e.key === "k") {
        e.preventDefault();
        if (isPlaying) onPause(); else onPlay();
      } else if (e.key === "ArrowLeft" && !e.shiftKey) {
        e.preventDefault();
        onSeek(Math.max(0, replayIndex - 1));
      } else if (e.key === "ArrowRight" && !e.shiftKey) {
        e.preventDefault();
        onSeek(Math.min(totalBars - 1, replayIndex + 1));
      } else if (e.key === "ArrowLeft" && e.shiftKey) {
        e.preventDefault();
        onSeek(Math.max(0, replayIndex - Math.round(totalBars * 0.1)));
      } else if (e.key === "ArrowRight" && e.shiftKey) {
        e.preventDefault();
        onSeek(Math.min(totalBars - 1, replayIndex + Math.round(totalBars * 0.1)));
      } else if (e.key === "1") { onSetSpeed(1); }
      else if (e.key === "2") { onSetSpeed(2); }
      else if (e.key === "5") { onSetSpeed(5); }
      else if (e.key === "0") { onSetSpeed(10); }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [isPlaying, replayIndex, totalBars, onPlay, onPause, onSeek, onSetSpeed]);

  return (
    <div
      role="toolbar"
      aria-label="Chart replay controls"
      className="flex items-center gap-2 px-3 py-1.5 bg-surface-card/80 backdrop-blur-sm border-t border-border-default shrink-0"
    >
      {/* Replay indicator badge */}
      <span className="text-xxs font-mono text-accent uppercase tracking-wider shrink-0 border border-accent/30 rounded px-1.5 py-0.5">
        Replay
      </span>

      {/* Divider */}
      <div className="w-px h-4 bg-border-default" aria-hidden="true" />

      {/* Play / Pause */}
      <button
        onClick={isPlaying ? onPause : onPlay}
        aria-label={isPlaying ? "Pause replay" : "Play replay"}
        title={`${isPlaying ? "Pause" : "Play"} (Space / k)`}
        className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        {isPlaying ? <Pause size={13} /> : <Play size={13} />}
      </button>

      {/* Reset */}
      <button
        onClick={onReset}
        aria-label="Reset to start"
        title="Reset to start"
        className="flex items-center justify-center w-6 h-6 rounded text-text-secondary hover:text-text-primary hover:bg-surface-hover transition-colors"
      >
        <RotateCcw size={12} />
      </button>

      {/* Divider */}
      <div className="w-px h-4 bg-border-default" aria-hidden="true" />

      {/* Speed pills */}
      <SpeedPills active={replaySpeed} onSelect={onSetSpeed} />

      {/* Divider */}
      <div className="w-px h-4 bg-border-default" aria-hidden="true" />

      {/* Progress scrubber */}
      <ProgressScrubber index={replayIndex} total={totalBars} onSeek={onSeek} />

      {/* Divider */}
      <div className="w-px h-4 bg-border-default" aria-hidden="true" />

      {/* Live button */}
      <button
        onClick={onExitReplay}
        aria-label="Exit replay and resume live data"
        title="Exit replay and resume live data"
        className="flex items-center gap-1 px-2 py-0.5 rounded text-xs text-text-secondary hover:text-profit hover:bg-surface-hover transition-colors shrink-0"
      >
        <Radio size={11} />
        <span>Live</span>
      </button>
    </div>
  );
}
