import { useMemo, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip,
} from 'recharts'
import { useDriverStore } from '../../store/driverStore'
import { useReplayStore } from '../../store/replayStore'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import { useLiveTelemetry, type TelemetryPoint } from '../../hooks/useLiveTelemetry'

/* ── types ────────────────────────────────────────────────────────────── */

interface TelData {
  driver_code: string
  full_name: string
  team_color: string
  lap_time_ms: number | null
  distance: number[]
  speed: number[]
  throttle: number[]
  brake: number[]
  gear: number[]
  drs: number[]
  telemetry_available?: boolean
  message?: string
}

interface DataPoint {
  dist: number
  speed: number
  throttle: number
  brake: number
  gear: number
}

interface LiveDataPoint {
  t: number
  speed: number
  throttle: number
  brake: number
  gear: number
}

/* ── constants ────────────────────────────────────────────────────────── */

const GRID_COLOR = '#1E1E2E'
const BG = '#12121A'
const AXIS_TICK = { fill: '#555', fontSize: 10 }

/* ── sub-chart (replay mode: distance-based) ─────────────────────────── */

function MiniChart(
  { data, dataKey, color, height, yDomain, label, step }:
  {
    data: DataPoint[]
    dataKey: keyof DataPoint
    color: string
    height: number
    yDomain?: [number, number]
    label: string
    step?: boolean
  },
) {
  return (
    <div style={{ background: BG }} className="rounded-md overflow-hidden">
      <div className="flex items-center justify-between px-3 pt-1.5">
        <span className="text-[10px] text-gray-500 font-bold tracking-wide">{label}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data} margin={{ left: 8, right: 8, top: 4, bottom: 2 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="dist"
            tick={AXIS_TICK}
            tickFormatter={(v: number) => `${Math.round(v)}`}
            axisLine={{ stroke: GRID_COLOR }}
            tickLine={false}
            minTickGap={60}
          />
          <YAxis
            domain={yDomain ?? ['auto', 'auto']}
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip
            contentStyle={{ background: '#0A0A0F', border: `1px solid ${GRID_COLOR}`, fontSize: 11 }}
            labelFormatter={(v: any) => `${Math.round(Number(v))} m`}
          />
          <Line
            type={step ? 'stepAfter' : 'monotone'}
            dataKey={dataKey}
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── sub-chart (live mode: time-based) ───────────────────────────────── */

function LiveMiniChart(
  { data, dataKey, color, height, yDomain, label, step }:
  {
    data: LiveDataPoint[]
    dataKey: keyof LiveDataPoint
    color: string
    height: number
    yDomain?: [number, number]
    label: string
    step?: boolean
  },
) {
  if (!data || data.length === 0) return null

  // Normalise time to seconds-ago for readability
  const now = data[data.length - 1]?.t ?? Date.now()
  const chartData = data.map(p => ({
    ...p,
    tRel: -((now - p.t) / 1000),  // negative = seconds ago
  }))

  return (
    <div style={{ background: BG }} className="rounded-md overflow-hidden">
      <div className="flex items-center justify-between px-3 pt-1.5">
        <span className="text-[10px] text-gray-500 font-bold tracking-wide">{label}</span>
        <span className="text-[9px] text-gray-600 font-mono">LIVE</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ left: 8, right: 8, top: 4, bottom: 2 }}>
          <CartesianGrid stroke={GRID_COLOR} strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="tRel"
            tick={AXIS_TICK}
            tickFormatter={(v: number) => `${Math.round(v)}s`}
            axisLine={{ stroke: GRID_COLOR }}
            tickLine={false}
            minTickGap={40}
          />
          <YAxis
            domain={yDomain ?? ['auto', 'auto']}
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <Tooltip
            contentStyle={{ background: '#0A0A0F', border: `1px solid ${GRID_COLOR}`, fontSize: 11 }}
            labelFormatter={(v: any) => `${Number(v).toFixed(1)}s`}
          />
          <Line
            type={step ? 'stepAfter' : 'monotone'}
            dataKey={dataKey}
            stroke={color}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

/* ── main component ───────────────────────────────────────────────────── */

export default function TelemetryPanel() {
  const selectedDriver = useDriverStore(s => s.selectedDriver)
  const driver = useDriverStore(s => s.selectedDriver ? s.drivers[s.selectedDriver] : null)
  const isMobile = useBreakpoint() === 'mobile'
  const mode = useReplayStore(s => s.mode)

  const year = useReplayStore(s => s.year) || 2024
  const round = useReplayStore(s => s.round) || 1
  const sessionType = useReplayStore(s => s.sessionType)

  // ── Live telemetry buffer ─────────────────────────────────────────
  const liveBuffer = useLiveTelemetry(selectedDriver)

  // Force re-render every 500ms in live mode to show new data
  const [, setTick] = useState(0)
  useEffect(() => {
    if (mode !== 'live') return
    const iv = setInterval(() => setTick(t => t + 1), 500)
    return () => clearInterval(iv)
  }, [mode])

  // ── Replay telemetry fetch ────────────────────────────────────────
  const { data: tel, isLoading } = useQuery<TelData | null>({
    queryKey: ['driver-telemetry', year, round, sessionType, selectedDriver],
    queryFn: async () => {
      try {
        const r = await fetch(`/api/laps/${year}/${round}/${sessionType}/${selectedDriver}/telemetry`)
        if (!r.ok) {
          return {
            driver_code: selectedDriver, full_name: '', team_color: '#888',
            lap_time_ms: null, distance: [], speed: [], throttle: [], brake: [], gear: [], drs: [],
            telemetry_available: false, message: 'Could not load telemetry'
          }
        }
        return await r.json()
      } catch (err) {
        return {
          driver_code: selectedDriver, full_name: '', team_color: '#888',
          lap_time_ms: null, distance: [], speed: [], throttle: [], brake: [], gear: [], drs: [],
          telemetry_available: false, message: String(err)
        }
      }
    },
    enabled: !!selectedDriver && !!round && mode !== 'live',
    staleTime: 0,
    gcTime: 0,
  })

  const chartData = useMemo<DataPoint[]>(() => {
    if (!tel || tel.telemetry_available === false) return []
    if (!tel.distance || !tel.speed || tel.distance.length === 0 || tel.speed.length === 0) return []
    
    return tel.distance.map((d, i) => ({
      dist: d,
      speed: tel.speed[i] ?? 0,
      throttle: tel.throttle[i] ?? 0,
      brake: tel.brake[i] ?? 0,
      gear: tel.gear[i] ?? 0,
    }))
  }, [tel])

  const teamColor = tel?.team_color ?? driver?.teamColor ?? '#888'

  if (!selectedDriver) {
    return (
      <div className="rounded-lg p-6 flex items-center justify-center" style={{ background: BG }}>
        <span className="text-gray-600 text-xs">Select a driver for telemetry</span>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════════
  // LIVE MODE — rolling time-based charts
  // ═══════════════════════════════════════════════════════════════════
  if (mode === 'live') {
    if (!liveBuffer || liveBuffer.length === 0) {
      return (
        <div className="rounded-lg p-6 flex flex-col items-center justify-center space-y-2 h-full" style={{ background: BG }}>
          <span className="text-gray-400 text-sm font-bold tracking-wide">Waiting for live telemetry…</span>
          <span className="text-gray-600 text-xs">Data will appear once the game sends packets</span>
        </div>
      )
    }

    const liveData: LiveDataPoint[] = liveBuffer.map(p => ({
      t: p.t,
      speed: p.speed,
      throttle: p.throttle,
      brake: p.brake,
      gear: p.gear,
    }))

    return (
      <div className="space-y-1">
        {/* header */}
        <div className="flex items-center gap-2 px-2 py-1">
          <div className="w-1 h-4 rounded-full" style={{ background: teamColor }} />
          <span className="text-white text-xs font-bold">{selectedDriver}</span>
          <span className="text-gray-500 text-[10px]">{driver?.fullName}</span>
          <div className="ml-auto flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 bg-red-500 rounded-full animate-pulse" />
            <span className="text-red-400 text-[10px] font-bold tracking-widest">LIVE</span>
          </div>
        </div>

        {/* 4 stacked live charts */}
        <LiveMiniChart data={liveData} dataKey="speed"    color={teamColor} height={isMobile ? 180 : 120} label="SPEED (km/h)" />
        <LiveMiniChart data={liveData} dataKey="throttle" color="#00CC44"   height={80}  label="THROTTLE %" yDomain={[0, 100]} />
        <LiveMiniChart data={liveData} dataKey="gear"     color="#FFD700"   height={80}  label="GEAR"       yDomain={[0, 8]} step />
        <LiveMiniChart data={liveData} dataKey="brake"    color="#FF3333"   height={80}  label="BRAKE %"    yDomain={[0, 100]} />

        <div className="text-center text-[10px] text-gray-600 py-0.5">Time (seconds ago)</div>
      </div>
    )
  }

  // ═══════════════════════════════════════════════════════════════════
  // REPLAY MODE — distance-based charts from API
  // ═══════════════════════════════════════════════════════════════════

  if (isLoading) {
    return (
      <div className="rounded-lg p-6 flex items-center justify-center" style={{ background: BG }}>
        <span className="text-gray-500 text-xs animate-pulse">Loading telemetry…</span>
      </div>
    )
  }

  if (!tel || tel.telemetry_available === false || !chartData || chartData.length === 0) {
    return (
      <div className="rounded-lg p-6 flex flex-col items-center justify-center space-y-2 h-full" style={{ background: BG }}>
        <span className="text-gray-400 text-sm font-bold tracking-wide">Telemetry unavailable for this session</span>
        {tel?.message && <span className="text-gray-600 text-xs">{tel.message}</span>}
      </div>
    )
  }

  return (
    <div className="space-y-1">
      {/* header */}
      <div className="flex items-center gap-2 px-2 py-1">
        <div className="w-1 h-4 rounded-full" style={{ background: teamColor }} />
        <span className="text-white text-xs font-bold">{selectedDriver}</span>
        <span className="text-gray-500 text-[10px]">{tel?.full_name}</span>
        {tel?.lap_time_ms != null && (
          <span className="ml-auto text-gray-400 text-[10px] font-mono">
            {(tel.lap_time_ms / 1000).toFixed(3)}s
          </span>
        )}
      </div>

      {/* 4 stacked charts */}
      <MiniChart data={chartData} dataKey="speed"    color={teamColor} height={isMobile ? 180 : 120} label="SPEED (km/h)" />
      <MiniChart data={chartData} dataKey="throttle" color="#00CC44"   height={80}  label="THROTTLE %" yDomain={[0, 100]} />
      <MiniChart data={chartData} dataKey="gear"     color="#FFD700"   height={80}  label="GEAR"       yDomain={[0, 8]} step />
      <MiniChart data={chartData} dataKey="brake"    color="#FF3333"   height={80}  label="BRAKE %"    yDomain={[0, 100]} />

      <div className="text-center text-[10px] text-gray-600 py-0.5">Distance (m)</div>
      {isMobile && (
        <div className="text-center text-[10px] text-gray-400 py-2 animate-pulse">
          ← Scroll charts →
        </div>
      )}
    </div>
  )
}
