import { useEffect, useRef, useCallback, useState } from 'react'
import { useDriverStore, type DriverData, type TyreCompound } from '../store/driverStore'
import { useReplayStore } from '../store/replayStore'
import { useUIStore, type TrackStatus } from '../store/uiStore'
import DRIVER_COLOR_FALLBACK from '../utils/driverColors'

// ── constants ────────────────────────────────────────────────────────────

const RECONNECT_MS = 5_000
const FASTEST_LAP_BANNER_MS = 5_000

const TYRE_MAP: Record<number, TyreCompound> = {
  0: 'S', 1: 'M', 2: 'H', 3: 'I', 4: 'W',
}

const FLAG_TO_STATUS: Record<string, TrackStatus> = {
  GREEN: 'GREEN',
  YELLOW: 'YELLOW',
  SAFETY_CAR: 'SC',
  SC_ENDING: 'SC',
  VSC: 'VSC',
  VSC_ENDING: 'VSC',
  RED: 'RED',
}

// ── types ────────────────────────────────────────────────────────────────

interface IncomingDriver {
  code: string
  position: number
  x: number
  y: number
  speed: number
  gear: number
  drs: number
  throttle: number
  brake: number
  tyre: number
  tyre_age: number
  is_out: boolean
  sector1?: number | null
  sector2?: number | null
  sector3?: number | null
  last_lap_time?: number | null
  gap_to_leader?: number | null
  interval?: number | null
  tyre_history?: string[] | null
  pit_count?: number | null
  grid_position?: number | null
  under_investigation?: boolean | null
  pit_prediction?: {
    predicted_position: number
    margin_ahead: number | null
    margin_behind: number | null
    free_air: boolean
  } | null
}

interface FrameMsg {
  type: 'frame'
  timestamp: number
  lap: number
  drivers: IncomingDriver[]
  weather: {
    air_temp: number | null
    track_temp: number | null
    rainfall: boolean
    humidity?: number | null
    wind_speed?: number | null
    wind_direction?: number | null
    flag: string
  }
  race_control?: {
    current_flag: string
    sc_deployed: boolean
    yellow_sectors?: number[]
    messages: {
      Time: string
      Category: string
      Message: string
      Flag: string
      Sector: number | null
    }[]
  }
}

interface ReadyMsg {
  type: 'ready'
  total_frames: number
  total_laps: number
  total_duration: number
  driver_info?: Record<string, { color: string, team: string }>
}

type ServerMsg =
  | FrameMsg
  | ReadyMsg
  | { type: 'ack'; action: string; [k: string]: unknown }
  | { type: 'finished' }
  | { type: 'status'; message?: string; status?: string }
  | { type: 'error'; detail: string }
  | { type: 'ping' }

export type SocketStatus = 'disconnected' | 'connecting' | 'preparing' | 'ready'

export interface ControlMessage {
  action: 'play' | 'pause' | 'seek' | 'speed' | 'rewind'
  value?: number
  timestamp?: number
}

// ── hook ─────────────────────────────────────────────────────────────────

export function useReplaySocket(sessionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const prevPositions = useRef<Record<string, number>>({})
  const topSpeeds = useRef<{ code: string; speed: number }[]>([])
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const intentionalDisconnect = useRef(false)
  const [socketStatus, setSocketStatus] = useState<SocketStatus>('disconnected')
  const statusRef = useRef<SocketStatus>('disconnected')

  const updateStatus = useCallback((s: SocketStatus) => {
    statusRef.current = s
    setSocketStatus(s)
  }, [])

  // ── store accessors (non-reactive for perf) ────────────────────────
  const setDrivers = useDriverStore.getState().setDrivers
  const addOvertake = useDriverStore.getState().addOvertake
  const setFastestLap = useDriverStore.getState().setFastestLap

  const seekStore = useReplayStore.getState().seek
  const setSession = useReplayStore.getState().setSession

  const setTrackStatus = useUIStore.getState().setTrackStatus
  const setFastestLapBanner = useUIStore.getState().setFastestLapBanner
  const updateSpeedTrap = useUIStore.getState().updateSpeedTrap
  const setWeather = useUIStore.getState().setWeather

  // ── frame processor ────────────────────────────────────────────────
  const processFrame = useCallback((frame: FrameMsg) => {
    const dStore = useDriverStore.getState()
    const oldDrivers = dStore.drivers
    let { sessionBestS1, sessionBestS2, sessionBestS3, fastestLapTime, driverInfo } = dStore

    let newFastestLapDriver: string | null = null
    let newFastestLapTime: number | null = null
    let newFastestLapNum: number | null = null

    const drivers: Record<string, DriverData> = {}
    const prev = prevPositions.current

    for (const d of frame.drivers) {
      const prevPos = prev[d.code] ?? d.position

      // ── overtake detection ───────────────────────────────────────
      if (prevPos !== d.position && d.position < prevPos) {
        addOvertake({
          time: frame.timestamp,
          driver: d.code,
          from: prevPos,
          to: d.position,
        })
      }

      // ── speed trap tracking ──────────────────────────────────────
      const existing = topSpeeds.current.find((e) => e.code === d.code)
      if (!existing) {
        topSpeeds.current.push({ code: d.code, speed: d.speed })
      } else if (d.speed > existing.speed) {
        existing.speed = d.speed
      }


      const old = oldDrivers[d.code] || ({} as DriverData)

      let s1Color = old.sector1Color || null
      let s2Color = old.sector2Color || null
      let s3Color = old.sector3Color || null
      
      let bestS1 = old.bestSector1 || null
      let bestS2 = old.bestSector2 || null
      let bestS3 = old.bestSector3 || null

      const s1 = d.sector1 ?? null
      if (s1 !== null && s1 !== old.sector1) {
        if (sessionBestS1 === null || s1 < sessionBestS1) {
          sessionBestS1 = s1
          s1Color = 'purple'
          bestS1 = s1
        } else if (bestS1 === null || s1 < bestS1) {
          s1Color = 'green'
          bestS1 = s1
        } else {
          s1Color = 'yellow'
        }
      }

      const s2 = d.sector2 ?? null
      if (s2 !== null && s2 !== old.sector2) {
        if (sessionBestS2 === null || s2 < sessionBestS2) {
          sessionBestS2 = s2
          s2Color = 'purple'
          bestS2 = s2
        } else if (bestS2 === null || s2 < bestS2) {
          s2Color = 'green'
          bestS2 = s2
        } else {
          s2Color = 'yellow'
        }
      }

      const s3 = d.sector3 ?? null
      if (s3 !== null && s3 !== old.sector3) {
        if (sessionBestS3 === null || s3 < sessionBestS3) {
          sessionBestS3 = s3
          s3Color = 'purple'
          bestS3 = s3
        } else if (bestS3 === null || s3 < bestS3) {
          s3Color = 'green'
          bestS3 = s3
        } else {
          s3Color = 'yellow'
        }
      }

      // ── fastest lap check ──────────────────────────────────────
      const lapTime = d.last_lap_time ?? null
      if (lapTime !== null && lapTime !== old.last_lap_time) {
        if (fastestLapTime === null || lapTime < fastestLapTime) {
          fastestLapTime = lapTime
          newFastestLapDriver = d.code
          newFastestLapTime = lapTime
          newFastestLapNum = frame.lap
        }
      }

      // ── build DriverData ─────────────────────────────────────────
      drivers[d.code] = {
        x: d.x,
        y: d.y,
        speed: d.speed,
        gear: d.gear,
        drs: d.drs,
        throttle: d.throttle,
        brake: d.brake,
        tyre: TYRE_MAP[d.tyre] ?? 'M',
        tyreAge: d.tyre_age,
        position: d.position,
        previousPosition: prevPos,
        gapAhead: '',
        gapBehind: '',
        gapToLeader: d.gap_to_leader ?? null,
        interval: d.interval ?? null,
        tyreHistory: d.tyre_history as TyreCompound[] | null ?? null,
        pitCount: d.pit_count ?? null,
        gridPosition: d.grid_position ?? null,
        underInvestigation: d.under_investigation ?? null,
        pitPrediction: d.pit_prediction ?? null,
        sector1: s1,
        sector2: s2,
        sector3: s3,
        last_lap_time: lapTime,
        sector1Color: s1Color,
        sector2Color: s2Color,
        sector3Color: s3Color,
        bestSector1: bestS1,
        bestSector2: bestS2,
        bestSector3: bestS3,
        isBestSector1: false,
        isBestSector2: false,
        isBestSector3: false,
        teamColor: driverInfo[d.code]?.color || (d as any).teamColor || DRIVER_COLOR_FALLBACK[d.code] || '#FFFFFF',
        team: driverInfo[d.code]?.team || d.code,
        fullName: d.code,
        isOut: d.is_out,
        isDRS: d.drs >= 10,
        fastestLap: false,
      }

      prev[d.code] = d.position
    }

    // ── fastest lap detection (lowest speed-based proxy isn't ideal,
    //    but the backend doesn't yet send per-lap times in frames;
    //    this will light up on the first speed record) ────────────────
    if (newFastestLapDriver && newFastestLapTime !== null && newFastestLapNum !== null) {
      setFastestLap(newFastestLapDriver, newFastestLapTime, newFastestLapNum)
      setFastestLapBanner(true)
      clearTimeout(bannerTimer.current)
      bannerTimer.current = setTimeout(() => setFastestLapBanner(false), FASTEST_LAP_BANNER_MS)
    }

    // Stamp fastestLap: true on the driver who holds the fastest lap
    const flDriver = newFastestLapDriver || dStore.fastestLapDriver
    if (flDriver && drivers[flDriver]) {
      drivers[flDriver].fastestLap = true
    }

    // ── push to stores ─────────────────────────────────────────────
    useDriverStore.setState({ sessionBestS1, sessionBestS2, sessionBestS3 })
    setDrivers(drivers)
    seekStore(frame.timestamp)
    useReplayStore.setState({ currentLap: frame.lap })

    // ── track status ───────────────────────────────────────────────
    if (frame.weather?.flag) {
      const mapped = FLAG_TO_STATUS[frame.weather.flag]
      if (mapped) setTrackStatus(mapped)
    }

    // ── race control ───────────────────────────────────────────────
    if (frame.race_control) {
      useReplayStore.getState().setRaceControl(frame.race_control)
    }

    // ── weather data ────────────────────────────────────────────────
    if (frame.weather) {
      setWeather({
        air_temp: frame.weather.air_temp,
        track_temp: frame.weather.track_temp,
        rainfall: frame.weather.rainfall,
        humidity: frame.weather.humidity ?? null,
        wind_speed: frame.weather.wind_speed ?? null,
        wind_direction: frame.weather.wind_direction ?? null,
      })
    }

    // ── update speed trap (top 3) ──────────────────────────────────
    const sorted = [...topSpeeds.current].sort((a, b) => b.speed - a.speed)
    if (sorted.length >= 3) {
      updateSpeedTrap({
        p1: sorted[0],
        p2: sorted[1],
        p3: sorted[2],
      })
    }
  }, [setDrivers, addOvertake, seekStore, setTrackStatus, updateSpeedTrap, setWeather])

  // ── send helper ────────────────────────────────────────────────────
  const send = useCallback((msg: ControlMessage) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  }, [])

  // ── connect / reconnect ────────────────────────────────────────────
  useEffect(() => {
    if (!sessionId) {
      intentionalDisconnect.current = true
      return
    }

    intentionalDisconnect.current = false
    let disposed = false

    function connect() {
      if (disposed) return

      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = window.location.host // Vite proxy handles /ws → backend
      const url = `${proto}://${host}/ws/replay/${sessionId}`

      updateStatus('connecting')
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (disposed) { ws.close(); return }
        updateStatus('connecting')
        prevPositions.current = {}
        topSpeeds.current = []
      }

      ws.onmessage = (ev) => {
        let msg: ServerMsg
        try { msg = JSON.parse(ev.data) } catch { return }

        console.log(`[ws] received type: ${msg.type}`, msg)

        switch (msg.type) {
          case 'ping':
            ws.send(JSON.stringify({ action: 'pong' }))
            break

          case 'status':
            if (msg.status === 'preparing') {
              updateStatus('preparing')
            }
            break

          case 'ready':
            if (msg.driver_info) {
              useDriverStore.getState().setDriverInfo(msg.driver_info)
            }
            setSession({
              totalDuration: msg.total_duration,
              totalLaps: msg.total_laps,
              sessionType: 'R',
              year: parseInt(sessionId!.split('_')[0]) || 2024,
              round: parseInt(sessionId!.split('_')[1]) || 1,
            })
            updateStatus('ready')
            break

          case 'frame':
            if (statusRef.current === 'ready') {
              processFrame(msg as FrameMsg)
            }
            break

          case 'finished':
            useReplayStore.setState({ isPlaying: false })
            break

          default:
            break
        }
      }

      ws.onclose = () => {
        if (disposed) return
        updateStatus('disconnected')
        wsRef.current = null
        if (!intentionalDisconnect.current) {
          reconnectTimer.current = setTimeout(connect, RECONNECT_MS)
        }
      }

      ws.onerror = () => {
        // onclose will fire right after
      }
    }

    connect()

    return () => {
      disposed = true
      intentionalDisconnect.current = true
      clearTimeout(reconnectTimer.current)
      clearTimeout(bannerTimer.current)
      wsRef.current?.close()
      wsRef.current = null
      updateStatus('disconnected')
    }
  }, [sessionId, processFrame, setSession, updateStatus])

  // ── public surface ─────────────────────────────────────────────────
  return {
    isConnected: socketStatus === 'ready',
    socketStatus,
    connectionStatus: socketStatus, // backwards compatibility if needed
    send,

    /** Fire the fastest-lap banner (can be called externally or from frame logic). */
    triggerFastestLapBanner: useCallback((driver: string, time: number, lap: number) => {
      setFastestLap(driver, time, lap)
      setFastestLapBanner(true)
      clearTimeout(bannerTimer.current)
      bannerTimer.current = setTimeout(() => setFastestLapBanner(false), FASTEST_LAP_BANNER_MS)
    }, [setFastestLap, setFastestLapBanner]),
  }
}
