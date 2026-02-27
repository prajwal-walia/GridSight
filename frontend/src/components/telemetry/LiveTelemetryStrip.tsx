import { useState } from 'react'
import { useDriverStore } from '../../store/driverStore'

function PipBar({ value, max, color }: { value: number; max: number; color: string }) {
  const heights = [4, 6, 8, 10, 12]
  // 5 pips. Calculate how many are filled based on value being chunked into 5 segments.
  const pips = Math.ceil((value / max) * 5)

  return (
    <div className="flex items-end gap-[1px] h-3">
      {heights.map((h, i) => (
        <div
          key={i}
          style={{
            width: 3,
            height: h,
            background: color,
            opacity: i < pips ? 1 : 0.2,
          }}
        />
      ))}
    </div>
  )
}

export default function LiveTelemetryStrip() {
  const drivers = useDriverStore(s => s.drivers)
  const selectedCode = useDriverStore(s => s.selectedDriver)
  const [visible, setVisible] = useState(true)

  if (Object.keys(drivers).length === 0) return null

  // Determine drivers to show: selected + P1, or P1 + P2
  let d1Code = ''
  let d2Code = ''

  const sorted = Object.entries(drivers).sort((a, b) => a[1].position - b[1].position)
  const p1 = sorted.length > 0 ? sorted[0][0] : null
  const p2 = sorted.length > 1 ? sorted[1][0] : null

  if (selectedCode && drivers[selectedCode]) {
    d1Code = selectedCode
    if (selectedCode === p1) {
      d2Code = p2 || ''
    } else {
      d2Code = p1 || ''
    }
  } else {
    d1Code = p1 || ''
    d2Code = p2 || ''
  }

  const dsToShow = [d1Code, d2Code].filter(Boolean).map(c => ({ code: c, ...drivers[c] }))

  if (!visible) {
    return (
      <div className="z-40 text-right pr-2 pb-2">
        <button 
           onClick={() => setVisible(true)}
           className="bg-[#0A0A0F]/90 text-gray-300 text-[10px] font-bold px-2 py-1 rounded border border-[#1E1E2E] hover:bg-gray-800 backdrop-blur-sm"
        >
          Show Telemetry
        </button>
      </div>
    )
  }

  return (
    <div className="w-full z-40 flex flex-col backdrop-blur-sm shrink-0" style={{ background: 'rgba(10, 10, 15, 0.95)' }}>
      <button 
        onClick={() => setVisible(false)}
        className="self-end bg-[#0A0A0F]/95 text-gray-400 text-[9px] px-2 py-1 hover:text-white transition-colors border-b border-[#1E1E2E]"
      >
        Hide Telemetry
      </button>

      {dsToShow.map((d) => {
        // Fake RPM mapping (7000 to ~12500 based heavily on throttle & gear)
        const rpm = Math.min(15000, Math.max(0, 7000 + (d.throttle * 55)))
        const rpmK = (rpm / 1000).toFixed(1)
        
        return (
          <div key={d.code} className="flex items-center h-[40px] border-t border-[#1E1E2E] px-2 gap-4">
            {/* team color bar */}
            <div className="w-1 h-full py-1 shrink-0">
               <div className="w-full h-full rounded-sm" style={{ background: d.teamColor || '#999' }} />
            </div>
            
            {/* Code */}
            <div className="text-white font-bold text-sm w-10 shrink-0">{String(d.code || '').slice(0, 3)}</div>
            
            {/* Speed */}
            <div className="flex items-center gap-1 shrink-0 w-24">
               <span className="text-[10px] text-gray-500 font-bold">SPD</span>
               <span className="text-white font-mono font-bold text-base w-8 text-right leading-none">{Math.round(d.speed)}</span>
               <span className="text-[9px] text-gray-500 leading-none">km/h</span>
            </div>

            {/* Throttle */}
            <div className="flex items-center gap-1.5 shrink-0 w-[4.5rem]">
               <span className="text-[10px] text-gray-500 font-bold">THR</span>
               <PipBar value={d.throttle} max={100} color="#27AE60" />
            </div>

            {/* Brake */}
            <div className="flex items-center gap-1.5 shrink-0 w-[4.5rem]">
               <span className="text-[10px] text-gray-500 font-bold">BRK</span>
               <PipBar value={d.brake} max={100} color="#E74C3C" />
            </div>

            {/* Gear */}
            <div className="flex items-center gap-1.5 shrink-0 w-12 justify-center">
               <span className="text-[10px] text-gray-500 font-bold">GEAR</span>
               <span className="text-white font-mono font-bold text-base leading-none">{d.gear > 0 ? d.gear : 'N'}</span>
            </div>

            {/* RPM */}
            <div className="flex items-center gap-1.5 shrink-0 w-[6.5rem]">
               <span className="text-[10px] text-gray-500 font-bold">RPM</span>
               <span className="text-white font-mono font-bold text-[13px] w-6 text-right leading-none">{rpmK}k</span>
               <PipBar value={rpm} max={15000} color="#F39C12" />
            </div>
            
            <div className="flex-1" />

            {/* DRS */}
            <div className="shrink-0 flex items-center justify-end w-12 mr-2">
               {d.isDRS && (
                 <span className="bg-[#27AE60] text-white text-[9px] font-bold px-1.5 py-0.5 rounded tracking-wider">DRS</span>
               )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
