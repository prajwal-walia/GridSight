import { useUIStore } from '../../store/uiStore'
import { useDriverStore } from '../../store/driverStore'
import { Gauge } from 'lucide-react'

/* ── component ────────────────────────────────────────────────────────── */

export default function SpeedTrap() {
  const speedTrap = useUIStore(s => s.speedTrap)
  const drivers = useDriverStore(s => s.drivers)

  const entries = [
    { pos: 1, ...speedTrap.p1 },
    { pos: 2, ...speedTrap.p2 },
    { pos: 3, ...speedTrap.p3 },
  ]

  const hasData = entries.some(e => e.code && e.speed > 0)

  return (
    <div className="rounded-lg overflow-hidden" style={{ background: '#12121A' }}>
      {/* header */}
      <div
        className="flex items-center gap-2 px-3 py-1.5"
        style={{ borderBottom: '1px solid #1E1E2E' }}
      >
        <Gauge size={12} className="text-cyan-400" />
        <span className="text-[10px] font-extrabold tracking-widest text-gray-400">
          SPEED TRAP
        </span>
      </div>

      <div className="p-2 space-y-1">
        {hasData ? (
          entries.map(entry => {
            if (!entry.code) return null
            const driverData = drivers[entry.code]
            const teamColor = driverData?.teamColor || '#e2e2e2'

            return (
              <div
                key={entry.pos}
                className="flex items-center gap-2 px-2 py-1 rounded"
                style={{
                  background: entry.pos === 1
                    ? 'rgba(6, 182, 212, 0.08)'
                    : 'transparent',
                }}
              >
                <span
                  className="text-[10px] font-bold w-4 text-right"
                  style={{
                    color:
                      entry.pos === 1
                        ? '#FFD700'
                        : entry.pos === 2
                          ? '#C0C0C0'
                          : '#CD7F32',
                  }}
                >
                  {entry.pos}.
                </span>
                <span
                  className="text-xs font-extrabold w-10"
                  style={{ color: teamColor }}
                >
                  {String(entry.code || '').slice(0, 3)}
                </span>
                <span className="text-xs font-mono font-bold text-white/90 ml-auto">
                  {entry.speed.toFixed(0)}
                </span>
                <span className="text-[9px] text-gray-500">km/h</span>
              </div>
            )
          })
        ) : (
          <div className="text-center text-[10px] text-gray-600 py-2">
            No data yet
          </div>
        )}
      </div>
    </div>
  )
}
