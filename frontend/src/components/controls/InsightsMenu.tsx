import { useState } from 'react'
import { useUIStore, type Panels } from '../../store/uiStore'
import { Settings2 } from 'lucide-react'

/* ── panel labels ─────────────────────────────────────────────────────── */

const PANEL_LABELS: Record<keyof Panels, string> = {
  leaderboard: 'Leaderboard',
  telemetry: 'Telemetry',
  weather: 'Weather',
  driverInfo: 'Driver Info',
  speedTrap: 'Speed Trap',
  overtakes: 'Overtakes',
  progressBar: 'Progress Bar',
  hud: 'HUD Overlays',
  raceControl: 'Race Control',
}

/* ── component ────────────────────────────────────────────────────────── */

export default function InsightsMenu() {
  const [open, setOpen] = useState(false)
  const panels = useUIStore(s => s.panels)
  const togglePanel = useUIStore(s => s.togglePanel)

  return (
    <div className="relative">
      {/* expanded panel list */}
      {open && (
        <div
          className="absolute right-0 top-full mt-2 rounded-lg overflow-hidden z-50 origin-top-right shadow-2xl"
          style={{
            background: 'rgba(18, 18, 26, 0.95)',
            backdropFilter: 'blur(12px)',
            border: '1px solid #1E1E2E',
            minWidth: 180,
          }}
        >
          <div
            className="px-3 py-1.5 text-[10px] font-extrabold tracking-widest text-gray-400"
            style={{ borderBottom: '1px solid #1E1E2E' }}
          >
            PANELS
          </div>
          {(Object.keys(PANEL_LABELS) as (keyof Panels)[]).map(key => (
            <button
              key={key}
              onClick={() => togglePanel(key)}
              className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-white/5 transition-colors"
            >
              <div
                className="w-3 h-3 rounded-sm border flex items-center justify-center"
                style={{
                  borderColor: panels[key] ? '#E10600' : '#333',
                  background: panels[key] ? '#E10600' : 'transparent',
                }}
              >
                {panels[key] && (
                  <svg width="8" height="8" viewBox="0 0 8 8" fill="none">
                    <path d="M1.5 4L3.2 5.7L6.5 2.3" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
              <span
                className="text-xs"
                style={{ color: panels[key] ? '#e2e2e2' : '#555' }}
              >
                {PANEL_LABELS[key]}
              </span>
            </button>
          ))}
        </div>
      )}

      {/* inline button */}
      <button
        onClick={() => setOpen(!open)}
        className="text-gray-400 hover:text-white transition-colors flex items-center justify-center p-1 rounded hover:bg-white/5"
        title="Toggle Panels"
      >
        <Settings2 size={16} className={open ? 'text-white' : ''} />
      </button>
    </div>
  )
}
