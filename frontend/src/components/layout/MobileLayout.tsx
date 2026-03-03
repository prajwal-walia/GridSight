import { useState } from 'react'
import TrackMapCanvas from '../trackmap/TrackMapCanvas'
import Leaderboard from '../leaderboard/Leaderboard'
import QualifyingLeaderboard from '../qualifying/QualifyingLeaderboard'
import DriverInfoPanel from '../telemetry/DriverInfoPanel'
import TelemetryPanel from '../telemetry/TelemetryPanel'
import WeatherPanel from '../weather/WeatherPanel'
import PlaybackControls from '../controls/PlaybackControls'
import ProgressBar from '../controls/ProgressBar'
import { Map, Users, Activity, CloudSun } from 'lucide-react'
import { useReplayStore } from '../../store/replayStore'
import type { ControlMessage } from '../../hooks/useReplaySocket'

type Tab = 'track' | 'grid' | 'telemetry' | 'weather'

interface Props {
  year: number
  round: number
  sessionType: string
  send: (msg: ControlMessage) => void
  isConnected: boolean
}

export default function MobileLayout({ year, round, sessionType, send, isConnected }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('track')
  const isQualifying = sessionType === 'Q'
  const mode = useReplayStore(s => s.mode)

  const tabs: { id: Tab; icon: any; label: string }[] = [
    { id: 'track', icon: Map, label: 'Track' },
    { id: 'grid', icon: Users, label: 'Grid' },
    { id: 'telemetry', icon: Activity, label: 'Data' },
    { id: 'weather', icon: CloudSun, label: 'Weather' }
  ]

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-[#0A0A0F]">
      
      {/* ── Top controls ────────────────────────────────────────── */}
      {mode === 'replay' && (
        <div className="shrink-0 border-b border-[#1E1E2E] flex flex-col">
          <ProgressBar send={send} />
          <PlaybackControls send={send} isConnected={isConnected} compact />
        </div>
      )}
      
      {/* ── Main Tab Content ────────────────────────────────────── */}
      <div className="flex-1 min-h-0 relative overflow-hidden">
        {activeTab === 'track' && (
          <div className="absolute inset-0 flex flex-col" style={{ flex: 1, height: '100%' }}>
            <TrackMapCanvas year={year} round={round} sessionType={sessionType} />
          </div>
        )}
        
        {activeTab === 'grid' && (
          <div className="absolute inset-0 overflow-y-auto gs-scrollbar">
            {isQualifying ? <QualifyingLeaderboard /> : <Leaderboard />}
          </div>
        )}

        {activeTab === 'telemetry' && (
          <div className="absolute inset-0 overflow-y-auto space-y-1 p-1 bg-[#12121A] gs-scrollbar">
            <DriverInfoPanel />
            <TelemetryPanel />
          </div>
        )}

        {activeTab === 'weather' && (
          <div className="absolute inset-0 p-1 bg-[#12121A]">
            <WeatherPanel />
          </div>
        )}
      </div>

      {/* ── Bottom Tab Bar ──────────────────────────────────────── */}
      <div 
        className="shrink-0 bg-[#12121A] border-t border-[#1E1E2E] flex justify-around items-center"
        style={{ paddingBottom: 'max(env(safe-area-inset-bottom), 8px)' }}
      >
        {tabs.map(tab => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex flex-col items-center justify-center pt-3 pb-2 transition-colors relative ${
                isActive ? 'text-[#E10600]' : 'text-[#8A8A9A] hover:text-gray-300'
              }`}
            >
              {isActive && <div className="absolute top-0 left-0 right-0 h-[2px] bg-[#E10600]" />}
              <Icon size={20} className="mb-1" strokeWidth={isActive ? 2.5 : 2} />
              <span className="text-[10px] font-bold tracking-wider">{tab.label}</span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
