import { useEffect, useRef, useState } from 'react'
import { useUIStore, type TrackStatus } from '../../store/uiStore'

/* ── status configs ───────────────────────────────────────────────────── */

interface StatusConfig {
  bg: string
  color: string
  label: string
  border?: string
}

const STATUS_CONFIG: Record<TrackStatus, StatusConfig> = {
  GREEN:  { bg: 'transparent', color: '#16a34a', label: '' },
  YELLOW: { bg: '#F1C40F', color: '#000000', label: 'YELLOW FLAG' },
  SC:     { bg: '#E67E22', color: '#FFFFFF', label: 'SAFETY CAR DEPLOYED' },
  VSC:    { bg: '#1A1A27', color: '#F1C40F', label: 'VIRTUAL SAFETY CAR', border: '2px solid #F1C40F' },
  RED:    { bg: '#E74C3C', color: '#FFFFFF', label: 'RED FLAG - SESSION SUSPENDED' },
}

/* ── component ────────────────────────────────────────────────────────── */

export default function TrackStatusBanner() {
  const status = useUIStore(s => s.trackStatus)
  const prevStatus = useRef<TrackStatus>(status)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    if (status !== prevStatus.current) {
      prevStatus.current = status
      if (status === 'GREEN') {
        // slide out
        setVisible(false)
      } else {
        // slide in
        setVisible(true)
      }
    }
  }, [status])

  const cfg = STATUS_CONFIG[status]

  if (status === 'GREEN' && !visible) return null

  return (
    <div
      className="w-full overflow-hidden"
      style={{
        transition: 'transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s ease',
        transform: visible ? 'translateY(0)' : 'translateY(-100%)',
        opacity: visible ? 1 : 0,
      }}
    >
      <div
        className="w-full text-center py-2 text-xs font-extrabold tracking-[0.2em]"
        style={{
          background: cfg.bg,
          color: cfg.color,
          border: cfg.border ?? 'none',
        }}
      >
        {cfg.label}
      </div>
    </div>
  )
}
