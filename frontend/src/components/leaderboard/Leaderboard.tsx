import { useMemo, useState } from 'react'
import { useDriverStore } from '../../store/driverStore'
import { useReplayStore } from '../../store/replayStore'
import DriverRow from './DriverRow'

export default function Leaderboard({ compact = false }: { compact?: boolean }) {
  const drivers = useDriverStore(s => s.drivers)
  const selectedDriver = useDriverStore(s => s.selectedDriver)
  const selectDriver = useDriverStore(s => s.selectDriver)

  const currentLap = useReplayStore(s => s.currentLap)
  const totalLaps = useReplayStore(s => s.totalLaps)
  const sessionType = useReplayStore(s => s.sessionType)

  const [gapMode, setGapMode] = useState<'gap' | 'interval'>('gap')

  const sorted = useMemo(
    () =>
      Object.entries(drivers)
        .sort(([, a], [, b]) => a.position - b.position),
    [drivers],
  )

  const title = sessionType === 'Q' ? 'QUALIFYING' : 'RACE CONTROL'

  return (
    <div
      className="flex flex-col h-full bg-[#12121A] w-full"
    >
      {/* ── header (fixed 80px) ─────────────────────────────────────────────────── */}
      <div className="shrink-0 flex flex-col justify-between" style={{ height: '80px', borderBottom: '1px solid #1E1E2E' }}>
        <div className="flex items-center gap-2 px-3 py-2 justify-between">
          <div className="flex items-center gap-2">
            <div className="w-1 self-stretch rounded-full" style={{ background: '#E10600' }} />
            <span className="text-xs font-bold tracking-widest" style={{ color: '#E10600' }}>
              {title}
            </span>
          </div>
          <button 
            onClick={() => setGapMode(m => m === 'gap' ? 'interval' : 'gap')}
            className="text-[9px] font-bold text-gray-400 hover:text-white px-1.5 py-0.5 rounded border border-gray-700 hover:border-gray-500 transition-colors"
          >
            {gapMode === 'gap' ? 'GAP' : 'INT'}
          </button>
        </div>

        {/* ── lap counter ────────────────────────────────────────────── */}
        {sessionType !== 'Q' && totalLaps > 0 && (
          <div className="px-3 py-1.5 text-white text-xs font-bold mt-auto">
            LAP {currentLap} / {totalLaps}
          </div>
        )}
      </div>

      {/* ── driver rows ────────────────────────────────────────────── */}
      <div 
        className="flex-1 overflow-y-auto overflow-x-hidden scrollable"
      >
        {sorted.map(([code, d], index) => {
          const isCloseToCarAhead = d.interval != null && d.position !== 1 && d.interval < 1.0;
          let isCloseToCarBehind = false;
          if (index < sorted.length - 1) {
             const carBehind = sorted[index + 1][1];
             if (carBehind.interval != null && carBehind.position !== 1 && carBehind.interval < 1.0) {
                 isCloseToCarBehind = true;
             }
          }
          const closeBattle = Boolean(isCloseToCarAhead || isCloseToCarBehind);
          
          return (
            <DriverRow
              key={code}
              code={code}
              driver={d}
              selected={selectedDriver === code}
              gapMode={gapMode}
              closeBattle={closeBattle}
              compact={compact}
              onClick={() => selectDriver(selectedDriver === code ? null : code)}
            />
          )
        })}
      </div>
    </div>
  )
}
