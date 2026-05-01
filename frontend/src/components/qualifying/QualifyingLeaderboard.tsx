import { useMemo } from 'react'
import { useDriverStore } from '../../store/driverStore'
import DriverRow from '../leaderboard/DriverRow'

/* ── component ────────────────────────────────────────────────────────── */

export default function QualifyingLeaderboard() {
  const drivers = useDriverStore(s => s.drivers)
  const selectedDriver = useDriverStore(s => s.selectedDriver)
  const selectDriver = useDriverStore(s => s.selectDriver)

  // sort by position (which in Q mode represents best lap ranking)
  const sorted = useMemo(
    () =>
      Object.entries(drivers)
        .sort(([, a], [, b]) => a.position - b.position),
    [drivers],
  )

  // find fastest driver (P1)
  const fastestCode = sorted.length > 0 ? sorted[0][0] : null

  return (
    <div
      className="flex flex-col rounded-lg overflow-hidden h-full"
      style={{ background: '#12121A' }}
    >
      {/* header */}
      <div className="flex items-center gap-2 px-3 py-2" style={{ borderBottom: '1px solid #1E1E2E' }}>
        <div className="w-1 self-stretch rounded-full" style={{ background: '#E10600' }} />
        <span className="text-xs font-bold tracking-widest" style={{ color: '#E10600' }}>
          QUALIFYING
        </span>
      </div>

      {/* driver rows */}
      <div className="flex-1 overflow-y-auto gs-scrollbar">
        {sorted.map(([code, d]) => (
          <div
            key={code}
            style={{
              background: code === fastestCode ? 'rgba(155,89,182,0.12)' : undefined,
              borderLeft: code === fastestCode ? '3px solid #9B59B6' : undefined,
            }}
          >
            <DriverRow
              code={code}
              driver={d}
              selected={selectedDriver === code}
              gapMode="gap"
              closeBattle={false}
              onClick={() => selectDriver(selectedDriver === code ? null : code)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}
