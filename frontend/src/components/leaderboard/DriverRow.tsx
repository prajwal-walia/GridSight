import { useEffect, useRef, useState, memo } from 'react'
import type { DriverData } from '../../store/driverStore'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { useDriverStore } from '../../store/driverStore'
import { useReplayStore } from '../../store/replayStore'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import TyreIcon, { TYRE_COLORS } from './TyreIcon'
import TeamLogo from './TeamLogo'

/* ── constants ────────────────────────────────────────────────────────── */



const PODIUM: Record<number, string> = {
  1: '#FFD700', 2: '#C0C0C0', 3: '#CD7F32',
}

const FLASH_MS = 800

/* ── props ────────────────────────────────────────────────────────────── */

interface Props {
  driver: DriverData
  code: string
  selected: boolean
  gapMode: 'gap' | 'interval'
  closeBattle: boolean
  compact?: boolean
  onClick: () => void
}

/* ── component ────────────────────────────────────────────────────────── */

const DriverRow = memo(function DriverRow({ driver, code, selected, gapMode, closeBattle, compact, onClick }: Props) {
  const prevPos = useRef(driver.position)
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)

  const isFastestLap = Boolean(driver.fastestLap) || useDriverStore(s => s.fastestLapDriver === code)
  const sessionYear = useReplayStore(s => s.year) || 2024
  const era = sessionYear >= 2026 ? 'active_aero' : 'ground_effect'

  const isMobile = useBreakpoint() === 'mobile'

  // detect position change → flash
  useEffect(() => {
    if (driver.position !== prevPos.current) {
      setFlash(driver.position < prevPos.current ? 'up' : 'down')
      prevPos.current = driver.position
      const t = setTimeout(() => setFlash(null), FLASH_MS)
      return () => clearTimeout(t)
    }
  }, [driver.position])

  const posColor = PODIUM[driver.position] ?? '#ffffff'
  const teamColor = driver.teamColor || '#666666'
  const isOut = driver.isOut

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center overflow-hidden text-left transition-colors duration-150 relative group border-b border-[#1E1E2E]"
      style={{
        height: isMobile ? 44 : 48,
        background: selected
          ? `${teamColor}33`
          : flash
            ? flash === 'up' ? 'rgba(0,255,0,0.08)' : 'rgba(255,0,0,0.08)'
            : closeBattle
              ? `${teamColor}1A`
              : 'transparent',
        boxShadow: closeBattle ? `inset 0 0 8px ${teamColor}` : 'none',
        opacity: isOut ? 0.45 : 1,
        borderLeft: selected ? `3px solid ${teamColor}` : isFastestLap ? `3px solid #A855F7` : '3px solid transparent',
      }}
    >
      {/* position */}
      <div
        className="flex items-center justify-center font-bold shrink-0"
        style={{ width: '28px', textAlign: 'center', color: posColor, flexShrink: 0 }}
      >
        {driver.position}
      </div>

      {/* team color bar 4px */}
      <div className="w-1 shrink-0 self-stretch rounded-sm mx-1 my-1" style={{ background: teamColor, flexShrink: 0 }} />

      {/* main content flex-col */}
      <div className="flex-1 flex flex-col justify-center min-w-0 py-0.5 pr-2 gap-[2px]">
        {/* LINE 1 */}
        <div className="flex items-center min-w-0" style={{ height: '22px' }}>
          {!compact && (
            <div className="flex items-center justify-center shrink-0 mr-1.5" style={{ width: '18px', height: '18px', flexShrink: 0 }}>
              <TeamLogo team={driver.team} size={18} />
            </div>
          )}

          <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span className="text-white shrink-0 font-bold" style={{ fontSize: '13px', flexShrink: 0 }}>
              {String(code || '').slice(0, 3)}
            </span>
            {isFastestLap && (
              <span style={{
                background: '#A855F7',
                color: 'white',
                fontSize: '9px',
                padding: '1px 4px',
                borderRadius: '3px',
                marginLeft: '4px',
                fontWeight: 'bold'
              }}>FL</span>
            )}
            {!isOut && era === 'active_aero' && Boolean(driver.overtake_mode_active) && (
              <span style={{ 
                background: '#7C3AED', 
                color: 'white', 
                fontSize: '9px', 
                padding: '1px 3px', 
                borderRadius: '2px',
                fontWeight: 'bold',
                lineHeight: 1
              }}>OVT</span>
            )}
            {!compact && Boolean(driver.underInvestigation) && <span title="Under Investigation" style={{ fontSize: '11px' }}>⚠️</span>}
          </div>

          <div className="flex-1 flex items-center justify-end gap-1 overflow-hidden ml-2" style={{ width: '60px', flexShrink: 0 }}>
            {flash === 'up' && <ChevronUp size={12} className="text-green-400 animate-bounce shrink-0" />}
            {flash === 'down' && <ChevronDown size={12} className="text-red-400 animate-bounce shrink-0" />}

            {isOut ? (
              <span className="text-[9px] font-bold bg-red-600 text-white px-1 py-0.5 rounded leading-none shrink-0" style={{ flexShrink: 0 }}>OUT</span>
            ) : driver.speed < 60 && driver.speed > 0 ? (
              <span className="text-[9px] font-bold bg-orange-500 text-white px-1 py-0.5 rounded leading-none shrink-0" style={{ flexShrink: 0 }}>PIT</span>
            ) : (
              <span 
                className={driver.position === 1 ? "font-mono font-bold text-white shrink-0" : "font-mono font-bold shrink-0"} 
                style={{ 
                  fontSize: '11px', 
                  color: driver.position === 1 ? '#ffffff' : '#8A8A9A',
                  flexShrink: 0,
                  maxWidth: '7ch',
                  overflow: 'hidden',
                  whiteSpace: 'nowrap'
                }}
              >
                {driver.position === 1 
                  ? 'LEADER' 
                  : gapMode === 'gap' 
                    ? driver.gapToLeader != null ? `+${driver.gapToLeader.toFixed(3)}` : '–'
                    : driver.interval != null ? `+${driver.interval.toFixed(3)}` : '–'
                }
              </span>
            )}

            {!isOut && era === 'active_aero' && (
              <>
                {Boolean(driver.straight_mode_active) && (
                  <span className="text-[9px] font-bold text-blue-400 border border-blue-400 px-1 py-0.5 rounded leading-none shrink-0" style={{ flexShrink: 0 }}>
                    SM
                  </span>
                )}

              </>
            )}
            {!isOut && era !== 'active_aero' && Boolean(driver.isDRS) && (
              <span className="text-[9px] font-bold text-green-400 border border-green-400 px-1 py-0.5 rounded leading-none shrink-0" style={{ flexShrink: 0 }}>
                 DRS
              </span>
            )}
          </div>
        </div>

        {/* LINE 2 */}
        <div className="flex items-center gap-1 overflow-hidden" style={{ height: '20px', color: '#8A8A9A' }}>
          <TyreIcon compound={driver.tyre} size={20} />
          {driver.tyreAge != null && (
            <span style={{ color: TYRE_COLORS[driver.tyre] || '#888', fontWeight: 'bold', fontSize: '11px', marginRight: '2px' }}>
              {driver.tyreAge}
            </span>
          )}

          {!compact && driver.tyreHistory && driver.tyreHistory.length > 0 && (
            <div className="flex gap-[2px] opacity-80 shrink-0 mx-0.5">
              {driver.tyreHistory.slice(isMobile ? -2 : -3).map((compound, i) => (
                <TyreIcon key={i} compound={compound} size={12} />
              ))}
            </div>
          )}

          {era === 'active_aero' && driver.batteryPct !== null && driver.batteryPct !== undefined && typeof driver.batteryPct === 'number' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '3px', marginLeft: '4px' }}>
              <span style={{ fontSize: '9px', color: '#3B82F6' }}>⚡</span>
              <div style={{ 
                width: '28px', height: '5px', 
                background: '#1E1E2E', 
                borderRadius: '2px', 
                overflow: 'hidden',
                border: '1px solid #3B82F6'
              }}>
                <div style={{ 
                  width: `${Math.max(0, Math.min(100, driver.batteryPct))}%`, 
                  height: '100%',
                  background: driver.batteryPct > 50 ? '#3B82F6' : 
                              driver.batteryPct > 20 ? '#F59E0B' : '#EF4444',
                  borderRadius: '2px'
                }} />
              </div>
              <span style={{ fontSize: '9px', color: '#3B82F6', minWidth: '22px' }}>
                {Math.round(driver.batteryPct)}%
              </span>
            </div>
          ) : null}

          {!compact && driver.pitCount != null && driver.pitCount > 0 && (
            <span className="bg-[#2A2A3A] text-gray-400 rounded-full px-1.5 py-0.5 font-bold flex items-center shrink-0 mx-0.5 leading-none" style={{ fontSize: '10px' }}>
              {driver.pitCount}🔧
            </span>
          )}

          {!compact && driver.gridPosition != null && driver.gridPosition !== driver.position && (
            <div className="flex items-center shrink-0 mx-0.5">
              {driver.position < driver.gridPosition ? (
                <span className="text-green-400 font-bold shrink-0" style={{ fontSize: '10px' }}>
                  ▲{driver.gridPosition - driver.position}
                </span>
              ) : (
                <span className="text-red-400 font-bold shrink-0" style={{ fontSize: '10px' }}>
                  ▼{driver.position - driver.gridPosition}
                </span>
              )}
            </div>
          )}

          {!compact && !isMobile && driver.pitPrediction && (
            <div className="flex items-center gap-[2px] shrink-0 mx-0.5" style={{ fontSize: '10px' }}>
              <span>↩ P{driver.pitPrediction.predicted_position}</span>
              {driver.pitPrediction.margin_behind != null && (
                <span style={{ 
                  color: driver.pitPrediction.margin_behind < 1.0 ? '#ef4444' 
                       : driver.pitPrediction.margin_behind < 2.5 ? '#eab308' 
                       : '#8A8A9A' 
                }}>
                  {driver.pitPrediction.margin_behind > 0 ? '+' : ''}{driver.pitPrediction.margin_behind.toFixed(1)}s
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </button>
  )
})

export default DriverRow
