import { useQuery } from '@tanstack/react-query'
import { useDriverStore, type DriverData } from '../../store/driverStore'
import { useReplayStore } from '../../store/replayStore'
import TyreIcon from '../leaderboard/TyreIcon'
import TeamLogo from '../leaderboard/TeamLogo'

/* ── constants ────────────────────────────────────────────────────────── */

const TYRE_NAMES: Record<string, string> = {
  S: 'SOFT', M: 'MEDIUM', H: 'HARD', I: 'INTER', W: 'WET',
}

/* ── sub-components ───────────────────────────────────────────────────── */

function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div className="h-3 rounded-full overflow-hidden" style={{ background: '#1E1E2E' }}>
      <div
        className="h-full rounded-full transition-all duration-100"
        style={{ width: `${Math.min(100, Math.max(0, pct))}%`, background: color }}
      />
    </div>
  )
}

function SectorBadge({ label, time, color }: { label: string; time: number | null; color: 'purple' | 'green' | 'yellow' | null }) {
  const display = time != null ? time.toFixed(3) : '—'
  
  let bg = '#1E1E2E'
  let txtColor = '#6b7280' // text-gray-500
  let labelColor = '#6b7280'

  if (color === 'purple') {
    bg = '#9B59B6'
    txtColor = '#ffffff'
    labelColor = '#ffffff'
  } else if (color === 'green') {
    bg = '#27AE60'
    txtColor = '#ffffff'
    labelColor = '#ffffff'
  } else if (color === 'yellow') {
    bg = '#F39C12'
    txtColor = '#000000'
    labelColor = '#000000'
  }

  return (
    <div className="flex flex-col items-center justify-center rounded px-2 py-1 w-[4.5rem]" style={{ background: bg }}>
      <span className="text-[10px]" style={{ color: labelColor, opacity: 0.8 }}>{label}</span>
      <span
        className="text-xs font-mono font-bold"
        style={{ color: txtColor }}
      >
        {display}
      </span>
    </div>
  )
}

/* ── main component ───────────────────────────────────────────────────── */

export default function DriverInfoPanel() {
  const selectedDriver = useDriverStore(s => s.selectedDriver)
  const drivers = useDriverStore(s => s.drivers)

  const sessionYear = useReplayStore(s => s.year) || 2024
  const sessionRound = useReplayStore(s => s.round) || 1
  const sessionType = useReplayStore(s => s.sessionType)
  const era = sessionYear >= 2026 ? 'active_aero' : 'ground_effect'

  const driver: DriverData | undefined = selectedDriver ? drivers[selectedDriver] : undefined

  console.log('Telemetry fetch:', sessionYear, sessionRound, sessionType, selectedDriver)

  // fetch detailed telemetry on select
  const { data: telemetry } = useQuery({
    queryKey: ['driver-telemetry', sessionYear, sessionRound, sessionType, selectedDriver],
    queryFn: async () => {
      try {
        const r = await fetch(`/api/laps/${sessionYear}/${sessionRound}/${sessionType}/${selectedDriver}/telemetry`)
        if (!r.ok) return null
        return await r.json()
      } catch (err) {
        return null
      }
    },
    enabled: !!selectedDriver && !!sessionRound,
    staleTime: 0,
    gcTime: 0,
  })

  console.log('Telemetry data received in DriverInfoPanel:', telemetry)

  if (!selectedDriver || !driver) {
    return (
      <div
        className="rounded-lg p-4 flex items-center justify-center"
        style={{ background: '#12121A', minHeight: 200 }}
      >
        <span className="text-gray-600 text-xs">Select a driver</span>
      </div>
    )
  }

  const teamColor = driver.teamColor || '#666'

  return (
    <div className="rounded-lg overflow-hidden" style={{ background: '#12121A' }}>
      {/* header */}
      <div
        className="flex items-center gap-2 px-3 py-2"
        style={{ borderBottom: `2px solid ${teamColor}` }}
      >
        <div className="w-1 self-stretch rounded-full" style={{ background: teamColor }} />
        <div className="flex items-center justify-center shrink-0 ml-1.5">
          <TeamLogo team={driver.team} size={28} />
        </div>
        <div className="flex-1 min-w-0 ml-1.5">
          <div className="text-white font-bold text-sm truncate">{selectedDriver}</div>
          <div className="text-gray-400 text-[10px] truncate">{driver.fullName}</div>
        </div>
        <div className="text-right">
          <span className="text-[10px] text-gray-500">P</span>
          <span className="text-white font-bold text-lg leading-none">{driver.position}</span>
        </div>
      </div>

      <div className="p-3 space-y-3 overflow-y-auto" style={{ maxHeight: 380 }}>
        {/* ── speed + gear row ────────────────────────────────────── */}
        <div className="flex items-end gap-4">
          <div>
            <span className="text-[10px] text-gray-500 block">SPEED</span>
            <span
              className="text-3xl font-extrabold leading-none tracking-tight"
              style={{ fontFamily: "'Courier New', monospace", color: '#fff' }}
            >
              {Math.round(driver.speed)}
            </span>
            <span className="text-[10px] text-gray-500 ml-1">km/h</span>
          </div>
          <div>
            <span className="text-[10px] text-gray-500 block">GEAR</span>
            <span
              className="text-3xl font-extrabold leading-none"
              style={{ fontFamily: "'Courier New', monospace", color: '#fff' }}
            >
              {driver.gear <= 0 ? 'N' : driver.gear}
            </span>
          </div>
          <div className="ml-auto">
            {era === 'active_aero' ? (
              driver.overtake_mode_active ? (
                <span className="text-[10px] font-bold bg-purple-500 text-white px-2 py-0.5 rounded">OVT</span>
              ) : driver.straight_mode_active ? (
                <span className="text-[10px] font-bold bg-blue-500 text-white px-2 py-0.5 rounded">SM</span>
              ) : null
            ) : driver.isDRS ? (
              <span className="text-[10px] font-bold bg-green-500 text-white px-2 py-0.5 rounded">
                DRS ACTIVE
              </span>
            ) : (
              <span className="text-[10px] font-bold bg-gray-700 text-gray-400 px-2 py-0.5 rounded">
                DRS
              </span>
            )}
          </div>
        </div>

        {/* ── throttle / brake / battery ──────────────────────────── */}
        <div className="space-y-1.5">
          <div>
            <div className="flex justify-between text-[10px] text-gray-400 mb-0.5">
              <span>THROTTLE</span>
              <span>{Math.round(driver.throttle)}%</span>
            </div>
            <Bar pct={driver.throttle} color="#00CC44" />
          </div>
          <div>
            <div className="flex justify-between text-[10px] text-gray-400 mb-0.5">
              <span>BRAKE</span>
              <span>{Math.round(driver.brake)}%</span>
            </div>
            <Bar pct={driver.brake} color="#FF3333" />
          </div>
          {era === 'active_aero' && (
            <div>
              <div className="flex justify-between text-[10px] text-gray-400 mb-0.5 font-bold">
                {driver.batteryPct != null ? (
                  <>
                    <span style={{ color: '#3B82F6' }}>BATTERY</span>
                    <span style={{ color: '#3B82F6' }}>{Math.round(driver.batteryPct)}%</span>
                  </>
                ) : (
                  <span style={{ color: '#6b7280' }}>BATTERY N/A</span>
                )}
              </div>
              {driver.batteryPct != null && (
                <Bar pct={driver.batteryPct} color="#3B82F6" />
              )}
            </div>
          )}
        </div>

        {/* ── gaps ────────────────────────────────────────────────── */}
        {(driver.gapAhead || driver.gapBehind) && (
          <div className="flex justify-between text-[10px]">
            <span className="text-gray-500">
              GAP AHEAD <span className="text-white font-mono">{driver.gapAhead || '—'}</span>
            </span>
            <span className="text-gray-500">
              BEHIND <span className="text-white font-mono">{driver.gapBehind || '—'}</span>
            </span>
          </div>
        )}

        {/* ── sectors ─────────────────────────────────────────────── */}
        <div
          className="flex justify-around py-2 rounded gap-1"
          style={{ background: '#0A0A0F' }}
        >
          {(() => {
            const s1 = driver?.sector1 ?? null
            const s2 = driver?.sector2 ?? null
            const lapTime = driver?.last_lap_time ?? null

            const s3 = (lapTime && s1 && s2)
                ? Math.max(0, parseFloat((lapTime - s1 - s2).toFixed(3)))
                : driver?.sector3 ?? null

            return (
              <>
                <SectorBadge label="S1" time={s1} color={driver?.sector1Color ?? null} />
                <SectorBadge label="S2" time={s2} color={driver?.sector2Color ?? null} />
                <SectorBadge label="S3" time={s3} color={driver?.sector3Color ?? null} />
              </>
            )
          })()}
        </div>

        {/* ── tyre ────────────────────────────────────────────────── */}
        <div className="flex items-center gap-3">
          <TyreIcon compound={driver.tyre} size={32} />
          <div>
            <div className="text-white text-xs font-semibold">{TYRE_NAMES[driver.tyre]}</div>
            <div className="text-[10px] text-gray-500">{driver.tyreAge} laps</div>
          </div>

          {/* fetched lap time from API */}
          {telemetry?.lap_time_ms != null && (
            <div className="ml-auto text-right">
              <span className="text-[10px] text-gray-500 block">BEST LAP</span>
              <span className="text-white text-xs font-mono font-bold">
                {(telemetry.lap_time_ms / 1000).toFixed(3)}s
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
