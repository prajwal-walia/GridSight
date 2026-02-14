import { create } from 'zustand'
import { queryClient } from '../main'

export type PlaybackSpeed = 0.5 | 1 | 2 | 4 | 8 | 16 | 32 | 64
export type SessionType = 'R' | 'Q' | 'S'
export type AppMode = 'replay' | 'live'

export interface RaceControlMessage {
  Time: string
  Category: string
  Message: string
  Flag: string
  Sector: number | null
}

interface ReplayState {
  isPlaying: boolean
  playbackSpeed: PlaybackSpeed
  currentTimestamp: number
  totalDuration: number
  currentLap: number
  totalLaps: number
  sessionType: SessionType
  mode: AppMode
  sessionLoaded: boolean
  year: number
  round: number
  raceControl: {
    current_flag: string
    sc_deployed: boolean
    yellow_sectors?: number[]
    messages: RaceControlMessage[]
  }

  setPlaying: (playing: boolean) => void
  setSpeed: (speed: PlaybackSpeed) => void
  seek: (timestamp: number) => void
  setMode: (mode: AppMode) => void
  setSession: (opts: {
    totalDuration: number
    totalLaps: number
    sessionType: SessionType
    year: number
    round: number
  }) => void
  setRaceControl: (rc: { current_flag: string, sc_deployed: boolean, yellow_sectors?: number[], messages: RaceControlMessage[] }) => void
}

export const useReplayStore = create<ReplayState>((set) => ({
  isPlaying: false,
  playbackSpeed: 1,
  currentTimestamp: 0,
  totalDuration: 0,
  currentLap: 1,
  totalLaps: 0,
  sessionType: 'R',
  mode: 'replay',
  sessionLoaded: false,
  year: 2024,
  round: 1,
  raceControl: {
    current_flag: 'GREEN',
    sc_deployed: false,
    yellow_sectors: [],
    messages: [],
  },

  setPlaying: (playing) => set({ isPlaying: playing }),

  setSpeed: (speed) => set({ playbackSpeed: speed }),

  seek: (timestamp) => set({ currentTimestamp: timestamp }),

  setMode: (mode) => set({ mode }),

  setSession: ({ totalDuration, totalLaps, sessionType, year, round }) => {
    queryClient.invalidateQueries({ queryKey: ['driver-telemetry'] })
    set({
      totalDuration,
      totalLaps,
      sessionType,
      year,
      round,
      sessionLoaded: true,
      currentTimestamp: 0,
      currentLap: 1,
      isPlaying: false,
      raceControl: { current_flag: 'GREEN', sc_deployed: false, yellow_sectors: [], messages: [] },
    })
  },

  setRaceControl: (rc) => set({ raceControl: rc }),
}))
