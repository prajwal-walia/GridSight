import { useState, useEffect, useRef, useCallback } from 'react'
import { useReplayStore } from '../store/replayStore'
import { useDriverStore, type DriverData, type TyreCompound } from '../store/driverStore'
import { useUIStore, type TrackStatus } from '../store/uiStore'

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
  fullName?: string
  team?: string
  currentLap?: number
  lastLapMs?: number
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

/**
 * Hook for replaying a saved sim session via /ws/sim-replay/{filename}.
 * Connects to the WebSocket, sends "play" immediately, and feeds frames
 * into the driver store just like useLiveSocket does.
 */
export function useSimReplaySocket(filename: string | null) {
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<'idle' | 'connecting' | 'playing' | 'finished' | 'error'>('idle')

  useEffect(() => {
    if (!filename) {
      setStatus('idle')
      return
    }

    setStatus('connecting')

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/sim-replay/${encodeURIComponent(filename)}`
    console.log('[SimReplay] Connecting to:', wsUrl)
    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => {
      console.log('[SimReplay] WebSocket open')
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)

        if (msg.type === 'ready') {
          console.log('[SimReplay] Ready:', msg)
          // Auto-play immediately
          ws.send(JSON.stringify({ action: 'play' }))
          
          useReplayStore.getState().setMode('replay')
          useReplayStore.setState({
            sessionLoaded: true,
            totalLaps: msg.total_laps || 0,
            totalDuration: msg.total_duration || 0,
            isPlaying: true,
          })
          setStatus('playing')
          return
        }

        if (msg.type === 'ack') {
          console.log('[SimReplay] Ack:', msg.action)
          return
        }

        if (msg.type === 'finished') {
          setStatus('finished')
          return
        }

        if (msg.type === 'error') {
          console.error('[SimReplay] Error:', msg.detail)
          setStatus('error')
          return
        }

        // Must be a frame
        if (msg.type === 'frame' && msg.drivers) {
          const frame = msg as SimFrame

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
              batteryPct: null,
              overtake_mode_active: false,
              straight_mode_active: false,
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
              sector1: null,
              sector2: null,
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

          useDriverStore.getState().setDrivers(newDrivers)
          useReplayStore.getState().seek(frame.timestamp)
          useReplayStore.setState({ currentLap: frame.lap })

          if (frame.weather?.flag) {
            const mapped = FLAG_TO_STATUS[frame.weather.flag]
            if (mapped) useUIStore.getState().setTrackStatus(mapped)
          }

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
      console.log('[SimReplay] WebSocket closed')
      if (status !== 'finished') setStatus('idle')
    }

    ws.onerror = () => {
      setStatus('error')
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [filename])

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setStatus('idle')
  }, [])

  return { status, disconnect }
}
