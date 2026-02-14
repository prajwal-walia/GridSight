import { create } from 'zustand'

export type TyreCompound = 'S' | 'M' | 'H' | 'I' | 'W'

export interface DriverData {
  x: number
  y: number
  speed: number
  gear: number
  drs: number
  throttle: number
  brake: number
  batteryPct: number | null
  overtake_mode_active: boolean
  straight_mode_active: boolean
  boostMode: boolean
  tyre: TyreCompound
  tyreAge: number
  position: number
  previousPosition: number
  gapAhead: string
  gapBehind: string
  gapToLeader: number | null
  interval: number | null
  tyreHistory: TyreCompound[] | null
  pitCount: number | null
  gridPosition: number | null
  underInvestigation: boolean | null
  pitPrediction: {
    predicted_position: number
    margin_ahead: number | null
    margin_behind: number | null
    free_air: boolean
  } | null
  sector1: number | null
  sector2: number | null
  sector3: number | null
  sector1Color: 'purple' | 'green' | 'yellow' | null
  sector2Color: 'purple' | 'green' | 'yellow' | null
  sector3Color: 'purple' | 'green' | 'yellow' | null
  last_lap_time: number | null
  bestSector1: number | null
  bestSector2: number | null
  bestSector3: number | null
  isBestSector1: boolean
  isBestSector2: boolean
  isBestSector3: boolean
  teamColor: string
  team: string
  fullName: string
  code: string
  isOut: boolean
  isDRS: boolean
  fastestLap: boolean
}

export interface OvertakeEvent {
  time: number
  driver: string
  from: number
  to: number
}

export interface DriverState {
  drivers: Record<string, DriverData>
  driverInfo: Record<string, { color: string, team: string }>
  selectedDriver: string | null
  overtakeEvents: OvertakeEvent[]
  fastestLapDriver: string | null
  fastestLapTime: number | null
  fastestLapNumber: number | null

  sessionBestS1: number | null
  sessionBestS2: number | null
  sessionBestS3: number | null

  liveTrack: { x: number; y: number }[] | null

  setDrivers: (drivers: Record<string, DriverData>) => void
  selectDriver: (code: string | null) => void
  addOvertake: (event: OvertakeEvent) => void
  setFastestLap: (driver: string, time: number, lap: number) => void
  setDriverInfo: (info: Record<string, { color: string, team: string }>) => void
  setLiveTrack: (coords: { x: number; y: number }[]) => void
}

export const useDriverStore = create<DriverState>((set) => ({
  drivers: {},
  driverInfo: {},
  selectedDriver: null,
  overtakeEvents: [],
  fastestLapDriver: null,
  fastestLapTime: null,
  fastestLapNumber: null,
  sessionBestS1: null,
  sessionBestS2: null,
  sessionBestS3: null,
  liveTrack: null,

  setDrivers: (drivers) => set({ drivers }),

  selectDriver: (code) => set({ selectedDriver: code }),

  addOvertake: (event) =>
    set((s) => ({ overtakeEvents: [...s.overtakeEvents, event] })),

  setFastestLap: (driver, time, lap) =>
    set({ fastestLapDriver: driver, fastestLapTime: time, fastestLapNumber: lap }),

  setDriverInfo: (info) => set({ driverInfo: info }),

  setLiveTrack: (coords) => set({ liveTrack: coords }),
}))
