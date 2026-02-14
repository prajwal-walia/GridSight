import { create } from 'zustand'

export type TrackStatus = 'GREEN' | 'YELLOW' | 'SC' | 'VSC' | 'RED'

export interface WeatherData {
  air_temp: number | null
  track_temp: number | null
  rainfall: boolean
  humidity: number | null
  wind_speed: number | null
  wind_direction: number | null
}

export interface Panels {
  leaderboard: boolean
  telemetry: boolean
  weather: boolean
  driverInfo: boolean
  speedTrap: boolean
  overtakes: boolean
  progressBar: boolean
  hud: boolean
  raceControl: boolean
}

export interface SpeedTrapEntry {
  code: string
  speed: number
}

export interface SpeedTrap {
  p1: SpeedTrapEntry
  p2: SpeedTrapEntry
  p3: SpeedTrapEntry
}

interface UIState {
  panels: Panels
  showFastestLapBanner: boolean
  trackStatus: TrackStatus
  raceDirectorMessages: string[]
  speedTrap: SpeedTrap
  weather: WeatherData

  togglePanel: (panel: keyof Panels) => void
  toggleAllHUD: () => void
  setTrackStatus: (status: TrackStatus) => void
  setFastestLapBanner: (show: boolean) => void
  addRaceDirectorMessage: (msg: string) => void
  updateSpeedTrap: (trap: SpeedTrap) => void
  setWeather: (weather: WeatherData) => void
}

export const useUIStore = create<UIState>((set) => ({
  panels: {
    leaderboard: true,
    telemetry: true,
    weather: true,
    driverInfo: true,
    speedTrap: false,
    overtakes: false,
    progressBar: true,
    hud: true,
    raceControl: false,
  },

  showFastestLapBanner: false,
  trackStatus: 'GREEN',
  raceDirectorMessages: [],

  weather: {
    air_temp: null,
    track_temp: null,
    rainfall: false,
    humidity: null,
    wind_speed: null,
    wind_direction: null,
  },

  speedTrap: {
    p1: { code: '', speed: 0 },
    p2: { code: '', speed: 0 },
    p3: { code: '', speed: 0 },
  },

  togglePanel: (panel) =>
    set((s) => ({
      panels: { ...s.panels, [panel]: !s.panels[panel] },
    })),

  toggleAllHUD: () =>
    set((s) => {
      const allOff = !s.panels.hud
      return {
        panels: {
          leaderboard: allOff,
          telemetry: allOff,
          weather: allOff,
          driverInfo: allOff,
          speedTrap: allOff,
          overtakes: allOff,
          progressBar: allOff,
          hud: allOff,
          raceControl: allOff,
        },
      }
    }),

  setTrackStatus: (status) => set({ trackStatus: status }),

  setFastestLapBanner: (show) => set({ showFastestLapBanner: show }),

  addRaceDirectorMessage: (msg) =>
    set((s) => ({
      raceDirectorMessages: [...s.raceDirectorMessages, msg],
    })),

  updateSpeedTrap: (trap) => set({ speedTrap: trap }),

  setWeather: (weather) => set({ weather }),
}))
