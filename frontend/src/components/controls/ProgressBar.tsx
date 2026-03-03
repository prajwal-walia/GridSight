import { useCallback, useRef } from 'react'
import { useReplayStore } from '../../store/replayStore'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import type { ControlMessage } from '../../hooks/useReplaySocket'

/* ── helpers ──────────────────────────────────────────────────────────── */

function fmtElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m}:${s.toString().padStart(2, '0')}`
}

/* ── F1 car SVG (pixel art, ~24×10 viewBox) ───────────────────────────── */

function F1CarIcon({ style }: { style?: React.CSSProperties }) {
  return (
    <svg
      width="28"
      height="14"
      viewBox="0 0 28 14"
      fill="none"
      style={style}
    >
      {/* body */}
      <rect x="4" y="4" width="18" height="6" rx="1" fill="#E10600" />
      {/* nose */}
      <rect x="22" y="5" width="5" height="4" rx="1" fill="#E10600" />
      {/* cockpit */}
      <rect x="10" y="3" width="4" height="3" rx="1" fill="#1A1A27" />
      {/* rear wing */}
      <rect x="2" y="2" width="3" height="10" rx="1" fill="#C40500" />
      {/* front wheel */}
      <rect x="19" y="2" width="3" height="3" rx="0.5" fill="#333" />
      <rect x="19" y="9" width="3" height="3" rx="0.5" fill="#333" />
      {/* rear wheel */}
      <rect x="5" y="2" width="3" height="3" rx="0.5" fill="#333" />
      <rect x="5" y="9" width="3" height="3" rx="0.5" fill="#333" />
    </svg>
  )
}

/* ── props ────────────────────────────────────────────────────────────── */

interface Props {
  send: (msg: ControlMessage) => void
}

/* ── component ────────────────────────────────────────────────────────── */

export default function ProgressBar({ send }: Props) {
  const timestamp = useReplayStore(s => s.currentTimestamp)
  const duration = useReplayStore(s => s.totalDuration)
  const totalLaps = useReplayStore(s => s.totalLaps)
  const currentLap = useReplayStore(s => s.currentLap)
  const seek = useReplayStore(s => s.seek)
  const barRef = useRef<HTMLDivElement>(null)

  const progress = duration > 0 ? (timestamp / duration) * 100 : 0

  const handleClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const t = pct * duration
    send({ action: 'seek', timestamp: t })
    seek(t)
  }, [duration, send, seek])

  // generate lap marker positions (evenly spaced for now)
  const lapMarkers: number[] = []
  if (totalLaps > 1) {
    for (let i = 1; i <= totalLaps; i++) {
      lapMarkers.push((i / totalLaps) * 100)
    }
  }

  const isMobile = useBreakpoint() === 'mobile'

  if (isMobile) {
    return (
      <div className="w-full bg-[#0D0D14]">
        <div
          ref={barRef}
          className="w-full h-1 cursor-pointer relative"
          style={{ background: '#1E1E2E' }}
          onClick={handleClick}
        >
          <div
            className="h-full transition-[width] duration-75"
            style={{ width: `${progress}%`, background: '#E10600' }}
          />
        </div>
      </div>
    )
  }

  return (
    <div
      className="w-full px-3 py-2"
      style={{ background: '#0D0D14' }}
    >
      {/* time + lap display */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[10px] font-mono text-gray-400">
          {fmtElapsed(timestamp)}
        </span>
        <span className="text-[10px] font-mono text-gray-500">
          LAP {currentLap}/{totalLaps || '—'}
        </span>
        <span className="text-[10px] font-mono text-gray-400">
          {fmtElapsed(duration)}
        </span>
      </div>

      {/* bar container */}
      <div
        ref={barRef}
        className="relative h-3 rounded-full cursor-pointer group"
        style={{ background: '#1E1E2E' }}
        onClick={handleClick}
      >
        {/* lap markers */}
        {lapMarkers.map((pct, i) => (
          <div
            key={i}
            className="absolute top-0 bottom-0 w-px"
            style={{
              left: `${pct}%`,
              background: 'rgba(255,255,255,0.08)',
            }}
          />
        ))}

        {/* filled track */}
        <div
          className="h-full rounded-full transition-[width] duration-75"
          style={{
            width: `${progress}%`,
            background: 'linear-gradient(90deg, #E10600, #FF1A1A)',
          }}
        />

        {/* car playhead */}
        <div
          className="absolute top-1/2 -translate-y-1/2 transition-[left] duration-75 pointer-events-none"
          style={{
            left: `${progress}%`,
            transform: `translateX(-50%) translateY(-50%)`,
          }}
        >
          <F1CarIcon
            style={{
              filter: 'drop-shadow(0 0 4px rgba(225, 6, 0, 0.6))',
            }}
          />
        </div>
      </div>
    </div>
  )
}
