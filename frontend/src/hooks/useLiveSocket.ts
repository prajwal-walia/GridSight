import { useState, useEffect, useRef, useCallback } from 'react'
import { useReplayStore } from '../store/replayStore'
import { useDriverStore, type DriverData, type TyreCompound } from '../store/driverStore'
import { useUIStore, type TrackStatus } from '../store/uiStore'
import type { ControlMessage } from './useReplaySocket'
import { queryClient } from '../main'
import { pushTelemetryPoint, clearTelemetryBuffers } from './useLiveTelemetry'

// ── Tyre + flag maps (match useReplaySocket) ────────────────────────────

const TYRE_MAP: Record<string, TyreCompound> = {
  S: 'S', M: 'M', H: 'H', I: 'I', W: 'W',
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

interface SimDriver {
  code: string
  position: number
  x: number
  y: number
  speed: number
  gear: number
  drs: boolean
  throttle: number
  brake: number
  tyre: string
  tyreAge: number
  isOut: boolean
  teamColor: string
  gapToLeader: number
  fastestLap: boolean
  s1?: number
  s2?: number
  fullName?: string
  team?: string
  currentLap?: number
  lastLapMs?: number
  pitStatus?: number
  totalDistance?: number
}

interface SimFrame {
  type: 'frame'
  timestamp: number
  lap: number
  drivers: SimDriver[]
  weather: {
    air_temp: number
    track_temp: number
    rainfall: boolean
    flag: string
  }
}

interface ReadyMsg {
  type: 'ready'
  mode: string
  recording_filename?: string
}

interface SessionInfoMsg {
  type: 'session_info'
  sessionType: string
  sessionTypeId: number
  trackName: string
  totalLaps: number
  trackLength: number
  numActiveCars: number
}

type SimMsg = SimFrame | ReadyMsg | SessionInfoMsg | { type: 'live_disconnected' } | { type: 'error'; message?: string } | { type: 'track_change'; circuit: string; year: number } | { type: 'live_track'; coords: { x: number; y: number }[] }

// ── hook ─────────────────────────────────────────────────────────────────

export function useLiveSocket(active: boolean) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connectionStatus, setConnectionStatus] = useState<
    'disconnected' | 'connecting' | 'connected' | 'error'
  >('disconnected')
  const [recordingFilename, setRecordingFilename] = useState<string | null>(null)
  const [gameConnected, setGameConnected] = useState(false)
  const [liveSessionInfo, setLiveSessionInfo] = useState<SessionInfoMsg | null>(null)

  useEffect(() => {
    if (!active) {
      setConnectionStatus('disconnected')
      setGameConnected(false)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      return
    }

    setConnectionStatus('connecting')

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/live`
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      setConnectionStatus('connecting') // wait for ready msg
    }

    ws.onmessage = (e) => {
      try {
        const msg: SimMsg = JSON.parse(e.data)

        if (msg.type === 'ready') {
          setConnectionStatus('connected')
          setRecordingFilename((msg as ReadyMsg).recording_filename || null)

          // Set mode to live + mark session as loaded
          useReplayStore.getState().setMode('live')
          useReplayStore.setState({
            sessionLoaded: true,
            totalLaps: 0,
            totalDuration: 0,
            isPlaying: true,
          })
          return
        }

        if (msg.type === 'session_info') {
          const info = msg as SessionInfoMsg
          setLiveSessionInfo(info)

          // Map game sessionType to our store's SessionType
          const isRace = info.sessionTypeId >= 10 && info.sessionTypeId <= 12
          const isQual = info.sessionTypeId >= 5 && info.sessionTypeId <= 9
          const storeType = isRace ? 'R' : isQual ? 'Q' : 'R'

          useReplayStore.setState({
            sessionType: storeType,
            totalLaps: info.totalLaps,
          })
          return
        }

        if (msg.type === 'live_disconnected') {
          setGameConnected(false)
          return
        }

        if (msg.type === 'error') {
          setConnectionStatus('error')
          return
        }

        if (msg.type === 'track_change') {
          const { circuit, year } = msg
          console.log('[LiveSocket] track_change received:', circuit)
          console.log('[LiveSocket] fetching track from:', `/api/sessions/circuit/${circuit}/track`)
          fetch(`/api/sessions/circuit/${encodeURIComponent(circuit)}/track`)
            .then(res => res.json())
            .then(trackData => {
              const state = useReplayStore.getState()
              const rYear = state.year || year || 2024
              const rRound = 1 // Default fallback from App.tsx when in simLiveActive
              const rType = state.sessionType || 'R'
              
              // Seed the query cache directly so TrackMapCanvas re-renders with new geometry
              queryClient.setQueryData(['track', rYear, rRound, rType], trackData)
            })
            .catch(err => console.error("Failed to load dynamic track geometry:", err))
          return
        }

        if (msg.type === 'live_track') {
          const coords = (msg as { type: 'live_track'; coords: { x: number; y: number }[] }).coords
          console.log(`[LiveSocket] live_track received: ${coords.length} coords`)
          useDriverStore.getState().setLiveTrack(coords)
          return
        }

        if (msg.type === 'frame') {
          setGameConnected(true)
          const frame = msg as SimFrame

          // ── Build DriverData records ──────────────────────────────
          const currentDrivers = useDriverStore.getState().drivers
          const newDrivers: Record<string, DriverData> = {}

          for (const d of frame.drivers) {
            const prev = currentDrivers[d.code]
            newDrivers[d.code] = {
              x: d.x,
              y: d.y,
              speed: d.speed,
              gear: d.gear,
              drs: d.drs ? 1 : 0,
              throttle: d.throttle,
              brake: d.brake,
              batteryPct: (d as any).battery_pct ?? null,
              overtake_mode_active: (d as any).overtake_mode_active ?? false,
              straight_mode_active: (d as any).straight_mode_active ?? false,
              boostMode: false,
              tyre: TYRE_MAP[d.tyre] ?? 'S',
              tyreAge: d.tyreAge ?? 0,
              position: d.position,
              previousPosition: prev?.position ?? d.position,
              gapAhead: '',
              gapBehind: '',
              gapToLeader: d.gapToLeader ?? null,
              interval: null,
              tyreHistory: null,
              pitCount: null,
              gridPosition: null,
              underInvestigation: null,
              pitPrediction: null,
              sector1: d.s1 ?? null,
              sector2: d.s2 ?? null,
              sector3: null,
              sector1Color: null,
              sector2Color: null,
              sector3Color: null,
              last_lap_time: d.lastLapMs ? d.lastLapMs / 1000 : null,
              bestSector1: null,
              bestSector2: null,
              bestSector3: null,
              isBestSector1: false,
              isBestSector2: false,
              isBestSector3: false,
              teamColor: d.teamColor || '#E10600',
              team: d.team || 'Player',
              fullName: d.fullName || d.code,
              code: d.code,
              isOut: d.isOut,
              isDRS: d.drs,
              fastestLap: d.fastestLap,
            }
          }

          // ── Push to stores ────────────────────────────────────────
          useDriverStore.getState().setDrivers(newDrivers)

          useReplayStore.getState().setMode('live')
          useReplayStore.getState().seek(frame.timestamp)
          useReplayStore.setState({
            currentLap: frame.lap,
          })

          // ── Track status ──────────────────────────────────────────
          if (frame.weather?.flag) {
            const mapped = FLAG_TO_STATUS[frame.weather.flag]
            if (mapped) useUIStore.getState().setTrackStatus(mapped)
          }

          // ── Push to live telemetry buffer ──────────────────────────
          const now = Date.now()
          for (const d of frame.drivers) {
            pushTelemetryPoint(d.code, {
              t: now,
              speed: d.speed,
              throttle: d.throttle,
              brake: d.brake,
              gear: d.gear,
            })
          }

          // ── Weather ───────────────────────────────────────────────
          if (frame.weather) {
            useUIStore.getState().setWeather({
              air_temp: frame.weather.air_temp,
              track_temp: frame.weather.track_temp,
              rainfall: frame.weather.rainfall,
              humidity: null,
              wind_speed: null,
              wind_direction: null,
            })
          }
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      setConnectionStatus('disconnected')
      setGameConnected(false)
      clearTelemetryBuffers()
    }

    ws.onerror = () => {
      setConnectionStatus('error')
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [active])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setConnectionStatus('disconnected')
    setGameConnected(false)
  }, [])

  const send = useCallback((_cmd: ControlMessage) => {
    // Cannot send commands to live sim feed
  }, [])

  return {
    connectionStatus,
    isConnected: connectionStatus === 'connected',
    gameConnected,
    recordingFilename,
    liveSessionInfo,
    disconnect,
    send,
  }
}
