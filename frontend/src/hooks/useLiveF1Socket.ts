import { useEffect, useRef, useCallback, useState } from 'react'
import { useDriverStore, type DriverData, type TyreCompound } from '../store/driverStore'
import { useReplayStore } from '../store/replayStore'
import { useUIStore, type TrackStatus } from '../store/uiStore'
import DRIVER_COLOR_FALLBACK from '../utils/driverColors'

// ── constants ────────────────────────────────────────────────────────────

const RECONNECT_MS = 5_000

const TYRE_MAP: Record<string, TyreCompound> = {
  SOFT: 'S', S: 'S',
  MEDIUM: 'M', M: 'M',
  HARD: 'H', H: 'H',
  INTERMEDIATE: 'I', I: 'I',
  WET: 'W', W: 'W',
}

const FLAG_TO_STATUS: Record<string, TrackStatus> = {
  GREEN: 'GREEN',
  YELLOW: 'YELLOW',
  SAFETY_CAR: 'SC',
  SC: 'SC',
  SC_ENDING: 'SC',
  VSC: 'VSC',
  VSC_ENDING: 'VSC',
  RED: 'RED',
  // lowercase variants from live_state.py
  green: 'GREEN',
  yellow: 'YELLOW',
  sc: 'SC',
  vsc: 'VSC',
  red: 'RED',
}

// ── types ────────────────────────────────────────────────────────────────

/** Driver shape from the live SignalR state manager (camelCase GridSight schema) */
interface LiveDriver {
  code: string
  position: number | null
  x: number
  y: number
  speed: number | null
  gear: number | null
  drs: number | null
  throttle: number | null
  brake: boolean
  tyre: string | null       // compound name like "MEDIUM"
  tyreAge: number | null
  tyreHistory?: string[]
  isOut: boolean
  teamColor: string
  team: string
  gapToLeader: string | null
  interval: string | null
  sector1?: number | null
  sector2?: number | null
  sector3?: number | null
  sector1Color?: string | null
  sector2Color?: string | null
  sector3Color?: string | null
  fastestLap: boolean
  pitCount: number
  gridPosition: number | null
  underInvestigation: string | null
  pitPrediction: number | null
}

interface LiveFrame {
  type: 'frame'
  timestamp: number
  lap: number
  drivers: LiveDriver[]
  weather: {
    air_temp: number | null
    track_temp: number | null
    rainfall: boolean
    humidity?: number | null
    wind_speed?: number | null
    flag: string
  }
}

type ServerMsg =
  | LiveFrame
  | { type: 'ready'; mode: string; session: string }
  | { type: 'delay_ack'; seconds: number }
  | { type: 'session_ended'; message: string; replay: boolean }
  | { type: 'finished'; message?: string }
  | { type: 'error'; detail?: string; message?: string }

export type LiveSocketStatus = 'disconnected' | 'connecting' | 'ready'

// ── hook ─────────────────────────────────────────────────────────────────

export function useLiveF1Socket(
  sessionInfo: { year: number; round: number; type: string } | null,
  delay: number = 0,
) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const prevPositions = useRef<Record<string, number>>({})
  const intentionalDisconnect = useRef(false)
  const [socketStatus, setSocketStatus] = useState<LiveSocketStatus>('disconnected')
  const statusRef = useRef<LiveSocketStatus>('disconnected')
  const [sessionEnded, setSessionEnded] = useState(false)
  const delayRef = useRef(delay)

  // Keep delay ref in sync
  useEffect(() => {
    delayRef.current = delay
    // Send delay update to backend if connected
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ command: 'delay', seconds: delay }))
    }
  }, [delay])

  const updateStatus = useCallback((s: LiveSocketStatus) => {
    statusRef.current = s
    setSocketStatus(s)
  }, [])

  // ── store accessors (non-reactive for perf) ────────────────────────
  const setDrivers = useDriverStore.getState().setDrivers


  // ── parse gap helper ────────────────────────────────────────────────
  const parseGap = (gap: string | null | number): number | null => {
    if (gap == null) return null
    if (typeof gap === 'number') return gap
    // String gaps like "+1.234", "LAP 5", "1 L"
    const trimmed = gap.replace(/^[+\s]+/, '')
    const num = parseFloat(trimmed)
    return isNaN(num) ? null : num
  }

  // ── process a single live frame ────────────────────────────────────
  const processFrame = useCallback((frame: LiveFrame) => {
    const drivers: Record<string, DriverData> = {}
    const prevPos = prevPositions.current

    let newFastestLapDriver: string | null = null

    for (const d of frame.drivers) {
      if (!d.code) continue

      const previousPosition = prevPos[d.code] ?? d.position ?? 0
      prevPos[d.code] = d.position ?? previousPosition

      // Map tyre compound
      const tyreCompound: TyreCompound = d.tyre
        ? (TYRE_MAP[d.tyre] ?? TYRE_MAP[d.tyre.toUpperCase()] ?? 'M')
        : 'M'

      // Map tyre history
      const tyreHistory: TyreCompound[] = (d.tyreHistory ?? []).map(
        t => TYRE_MAP[t] ?? TYRE_MAP[t?.toUpperCase()] ?? 'M'
      )

      // Fastest lap tracking
      if (d.fastestLap) {
        newFastestLapDriver = d.code
      }

      const drsVal = d.drs ?? 0

      drivers[d.code] = {
        x: d.x,
        y: d.y,
        speed: d.speed ?? 0,
        gear: d.gear ?? 0,
        drs: drsVal,
        throttle: d.throttle ?? 0,
        brake: d.brake ? 1 : 0,
        batteryPct: null,
        overtake_mode_active: false,
        straight_mode_active: false,
        boostMode: false,
        tyre: tyreCompound,
        tyreAge: d.tyreAge ?? 0,
        position: d.position ?? 0,
        previousPosition,
        gapAhead: '',
        gapBehind: '',
        gapToLeader: parseGap(d.gapToLeader),
        interval: parseGap(d.interval),
        isOut: d.isOut,
        teamColor: d.teamColor || DRIVER_COLOR_FALLBACK[d.code] || '#999',
        team: d.team || '',
        fullName: d.code,
        code: d.code,
        sector1: d.sector1 ?? null,
        sector2: d.sector2 ?? null,
        sector3: d.sector3 ?? null,
        sector1Color: (d.sector1Color as any) ?? null,
        sector2Color: (d.sector2Color as any) ?? null,
        sector3Color: (d.sector3Color as any) ?? null,
        last_lap_time: null,
        bestSector1: null,
        bestSector2: null,
        bestSector3: null,
        isBestSector1: false,
        isBestSector2: false,
        isBestSector3: false,
        fastestLap: d.fastestLap ?? false,
        tyreHistory,
        pitCount: d.pitCount ?? 0,
        gridPosition: d.gridPosition ?? null,
        underInvestigation: d.underInvestigation != null ? true : null,
        isDRS: drsVal >= 10,
        pitPrediction: d.pitPrediction != null
          ? { predicted_position: d.pitPrediction, margin_ahead: null, margin_behind: null, free_air: false }
          : null,
      }
    }

    // ── update stores ────────────────────────────────────────────────
    setDrivers(drivers)

    useReplayStore.setState({
      currentLap: frame.lap,
      currentTimestamp: frame.timestamp,
      sessionLoaded: true,
      mode: 'live',
      isPlaying: true,
    })

    // Track status from weather.flag
    const flag = frame.weather?.flag ?? 'GREEN'
    const mappedStatus = FLAG_TO_STATUS[flag] ?? 'GREEN'
    useUIStore.setState({ trackStatus: mappedStatus })

    // Update fastest lap
    if (newFastestLapDriver) {
      useDriverStore.setState({
        fastestLapDriver: newFastestLapDriver,
      })
    }
  }, [setDrivers])

  // ── connect / disconnect ───────────────────────────────────────────
  const connect = useCallback(() => {
    if (!sessionInfo) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    intentionalDisconnect.current = false
    setSessionEnded(false)
    updateStatus('connecting')

    const { year, round, type } = sessionInfo
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/ws/live-f1/${year}/${round}/${type}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      updateStatus('ready')
      // Send initial delay
      if (delayRef.current > 0) {
        ws.send(JSON.stringify({ command: 'delay', seconds: delayRef.current }))
      }
    }

    ws.onmessage = (ev) => {
      let msg: ServerMsg
      try {
        msg = JSON.parse(ev.data)
      } catch {
        return
      }

      if (msg.type === 'ready') {
        updateStatus('ready')
        useReplayStore.setState({
          sessionLoaded: true,
          mode: 'live',
          isPlaying: true,
        })
        return
      }

      if (msg.type === 'frame') {
        processFrame(msg as LiveFrame)
        return
      }

      if (msg.type === 'delay_ack') {
        // Delay confirmed by server
        return
      }

      if (msg.type === 'session_ended') {
        setSessionEnded(true)
        return
      }

      if (msg.type === 'finished') {
        setSessionEnded(true)
        return
      }

      if (msg.type === 'error') {
        console.error('[LiveF1] Error:', (msg as any).detail ?? (msg as any).message)
        return
      }
    }

    ws.onclose = () => {
      updateStatus('disconnected')
      wsRef.current = null
      if (!intentionalDisconnect.current && sessionInfo) {
        reconnectTimer.current = setTimeout(connect, RECONNECT_MS)
      }
    }

    ws.onerror = () => {
      // onclose will fire after onerror
    }
  }, [sessionInfo, processFrame, updateStatus])

  const disconnect = useCallback(() => {
    intentionalDisconnect.current = true
    clearTimeout(reconnectTimer.current)
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    updateStatus('disconnected')
  }, [updateStatus])

  const send = useCallback((msg: any) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(typeof msg === 'string' ? msg : JSON.stringify(msg))
    }
  }, [])

  // ── auto-connect when sessionInfo changes ──────────────────────────
  useEffect(() => {
    if (sessionInfo) {
      connect()
    } else {
      disconnect()
    }

    return () => {
      disconnect()
    }
  }, [sessionInfo]) // eslint-disable-line react-hooks/exhaustive-deps

  return {
    connectionStatus: socketStatus as string,
    isConnected: socketStatus === 'ready',
    send,
    sessionEnded,
  }
}
