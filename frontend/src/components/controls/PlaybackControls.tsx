import { useCallback, useEffect } from 'react'
import { useReplayStore, type PlaybackSpeed } from '../../store/replayStore'
import { useUIStore } from '../../store/uiStore'
import { Play, Pause, SkipBack, ChevronsLeft, ChevronsRight } from 'lucide-react'
import type { ControlMessage } from '../../hooks/useReplaySocket'

/* ── constants ────────────────────────────────────────────────────────── */

const SPEEDS: PlaybackSpeed[] = [0.5, 1, 2, 4, 8, 16, 32, 64]
const SEEK_STEP = 5 // seconds

/* ── props ────────────────────────────────────────────────────────────── */

interface Props {
  send: (msg: ControlMessage) => void
  isConnected: boolean
  compact?: boolean
}

/* ── component ────────────────────────────────────────────────────────── */

export default function PlaybackControls({ send, isConnected }: Props) {
  const isPlaying = useReplayStore(s => s.isPlaying)
  const speed = useReplayStore(s => s.playbackSpeed)
  const timestamp = useReplayStore(s => s.currentTimestamp)
  const duration = useReplayStore(s => s.totalDuration)
  const setPlaying = useReplayStore(s => s.setPlaying)
  const setSpeed = useReplayStore(s => s.setSpeed)
  const seek = useReplayStore(s => s.seek)
  const toggleAllHUD = useUIStore(s => s.toggleAllHUD)

  /* ── actions ──────────────────────────────────────────────────────── */

  const togglePlay = useCallback(() => {
    if (isPlaying) {
      send({ action: 'pause' })
      setPlaying(false)
    } else {
      send({ action: 'play' })
      setPlaying(true)
    }
  }, [isPlaying, send, setPlaying])

  const restart = useCallback(() => {
    send({ action: 'seek', timestamp: 0 })
    seek(0)
  }, [send, seek])

  const seekDelta = useCallback((delta: number) => {
    const t = Math.max(0, Math.min(duration, timestamp + delta))
    send({ action: 'seek', timestamp: t })
    seek(t)
  }, [send, seek, timestamp, duration])

  const selectSpeed = useCallback((s: PlaybackSpeed) => {
    send({ action: 'speed', value: s })
    setSpeed(s)
  }, [send, setSpeed])

  const speedUp = useCallback(() => {
    const idx = SPEEDS.indexOf(speed)
    if (idx < SPEEDS.length - 1) selectSpeed(SPEEDS[idx + 1])
  }, [speed, selectSpeed])

  const speedDown = useCallback(() => {
    const idx = SPEEDS.indexOf(speed)
    if (idx > 0) selectSpeed(SPEEDS[idx - 1])
  }, [speed, selectSpeed])

  /* ── keyboard shortcuts ───────────────────────────────────────────── */

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // ignore when typing in inputs
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) return

      switch (e.code) {
        case 'Space':
          e.preventDefault()
          togglePlay()
          break
        case 'ArrowLeft':
          e.preventDefault()
          seekDelta(-SEEK_STEP)
          break
        case 'ArrowRight':
          e.preventDefault()
          seekDelta(SEEK_STEP)
          break
        case 'ArrowUp':
          e.preventDefault()
          speedUp()
          break
        case 'ArrowDown':
          e.preventDefault()
          speedDown()
          break
        case 'KeyR':
          restart()
          break
        case 'KeyH':
          toggleAllHUD()
          break
      }
    }

    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [togglePlay, seekDelta, speedUp, speedDown, restart, toggleAllHUD])

  /* ── render ───────────────────────────────────────────────────────── */

  return (
    <div
      className="flex items-center gap-2 px-3 py-1.5"
      style={{ background: '#12121A', borderBottom: '1px solid #1A1A24' }}
    >
      {/* ── transport buttons ──────────────────────────────────────── */}
      <Btn onClick={restart} disabled={!isConnected} title="Restart (R)">
        <SkipBack size={14} />
      </Btn>

      <Btn onClick={() => seekDelta(-SEEK_STEP)} disabled={!isConnected} title="Back 5s (←)">
        <ChevronsLeft size={14} />
      </Btn>

      <button
        onClick={togglePlay}
        disabled={!isConnected}
        className="w-8 h-8 rounded-full flex items-center justify-center transition-colors disabled:opacity-30"
        style={{ background: '#E10600' }}
        title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
      >
        {isPlaying
          ? <Pause size={16} fill="#fff" color="#fff" />
          : <Play size={16} fill="#fff" color="#fff" />
        }
      </button>

      <Btn onClick={() => seekDelta(SEEK_STEP)} disabled={!isConnected} title="Forward 5s (→)">
        <ChevronsRight size={14} />
      </Btn>

      {/* ── spacer ─────────────────────────────────────────────────── */}
      <div className="w-px h-5 mx-1" style={{ background: '#1E1E2E' }} />

      {/* ── speed selector ─────────────────────────────────────────── */}
      <div className="flex items-center gap-0.5">
        {SPEEDS.map(s => (
          <button
            key={s}
            onClick={() => selectSpeed(s)}
            disabled={!isConnected}
            className="px-1.5 py-0.5 rounded text-[10px] font-bold transition-colors disabled:opacity-30"
            style={{
              background: speed === s ? '#E10600' : '#1E1E2E',
              color: speed === s ? '#FFFFFF' : '#666',
            }}
          >
            {s}×
          </button>
        ))}
      </div>
    </div>
  )
}

/* ── small icon button ────────────────────────────────────────────────── */

function Btn(
  { children, onClick, disabled, title }:
  { children: React.ReactNode; onClick: () => void; disabled: boolean; title: string },
) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="w-7 h-7 rounded flex items-center justify-center text-gray-300 hover:text-white transition-colors disabled:opacity-30"
      style={{ background: '#1E1E2E' }}
    >
      {children}
    </button>
  )
}
