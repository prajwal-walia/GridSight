import { useDriverStore } from '../../store/driverStore'
import { useUIStore } from '../../store/uiStore'

function formatTime(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const ms = Math.floor((sec % 1) * 1000)
  if (m > 0) return `${m}:${s.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
  return `${s}.${ms.toString().padStart(3, '0')}`
}

export default function FastestLapBanner() {
  const show = useUIStore(s => s.showFastestLapBanner)
  const driver = useDriverStore(s => s.fastestLapDriver)
  const time = useDriverStore(s => s.fastestLapTime)
  const lapNumber = useDriverStore(s => s.fastestLapNumber)
  const driverData = useDriverStore(s => driver ? s.drivers[driver] : null)
  const teamColor = driverData?.teamColor || '#FFFFFF'

  return (
    <div
      className="fixed bottom-0 left-0 right-0 z-50"
      style={{
        transition: 'transform 0.5s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.4s ease',
        transform: show && driver ? 'translateY(0)' : 'translateY(100%)',
        opacity: show && driver ? 1 : 0,
        pointerEvents: 'none',
      }}
    >
      <div
        className="w-full flex items-center justify-center gap-4 py-3"
        style={{
          background: 'linear-gradient(135deg, #9B59B6 0%, #7D3C98 100%)',
          boxShadow: '0 -4px 30px rgba(155, 89, 182, 0.5)',
        }}
      >
        <span className="text-white/70 text-xs font-extrabold tracking-[0.15em]">
          ⚡ FASTEST LAP
        </span>
        <span className="text-white text-sm font-extrabold tracking-wider">
          —
        </span>
        <span className="text-sm font-extrabold" style={{ color: teamColor }}>
          {driver}
        </span>
        <span className="text-white text-sm font-extrabold tracking-wider">
          —
        </span>
        {time != null && (
          <span className="text-purple-100 text-sm font-mono font-bold">
            {formatTime(time)}
          </span>
        )}
        {lapNumber != null && (
          <>
            <span className="text-white text-sm font-extrabold tracking-wider">—</span>
            <span className="text-purple-100 text-sm font-extrabold">LAP {lapNumber}</span>
          </>
        )}
      </div>
    </div>
  )
}
