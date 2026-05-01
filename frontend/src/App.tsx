import { useState, useCallback, useEffect } from 'react'
import { useReplaySocket } from './hooks/useReplaySocket'
import { useLiveSocket } from './hooks/useLiveSocket'
import { useSimReplaySocket } from './hooks/useSimReplaySocket'
import { useLiveF1Socket } from './hooks/useLiveF1Socket'
import { useReplayStore } from './store/replayStore'
import { useUIStore } from './store/uiStore'

import TrackMapCanvas from './components/trackmap/TrackMapCanvas'
import Leaderboard from './components/leaderboard/Leaderboard'
import QualifyingLeaderboard from './components/qualifying/QualifyingLeaderboard'
import DriverInfoPanel from './components/telemetry/DriverInfoPanel'
import TelemetryPanel from './components/telemetry/TelemetryPanel'
import WeatherPanel from './components/weather/WeatherPanel'
import PlaybackControls from './components/controls/PlaybackControls'
import ProgressBar from './components/controls/ProgressBar'
import SessionSelector from './components/controls/SessionSelector'
import InsightsMenu from './components/controls/InsightsMenu'
import FastestLapBanner from './components/overlays/FastestLapBanner'
import TrackStatusBanner from './components/overlays/TrackStatusBanner'
import OvertakeFeed from './components/overlays/OvertakeFeed'
import SpeedTrap from './components/overlays/SpeedTrap'
import PiPWindow from './components/layout/PiPWindow'
import MobileLayout from './components/layout/MobileLayout'
import { Wifi, WifiOff, Monitor, Radio, ExternalLink, Maximize, Minimize, Square, Save } from 'lucide-react'
import { useFullscreen } from './hooks/useFullscreen'
import { useBreakpoint } from './hooks/useBreakpoint'

/* ═══════════════════════════════════════════════════════════════════════
   Top Bar (compact session info + connection status)
   ═══════════════════════════════════════════════════════════════════════ */

function TopBar({
  year, round, sessionType, connectionStatus, isConnected, onReset, isMobile,
  simLiveActive, gameConnected, onStopSim, liveSessionInfo, isRecording, onToggleRecording
}: {
  year: number; round: number; sessionType: string
  connectionStatus: string
  isConnected: boolean
  onReset: () => void
  isMobile?: boolean
  simLiveActive?: boolean
  gameConnected?: boolean
  onStopSim?: () => void
  liveSessionInfo?: { sessionType: string; trackName: string; numActiveCars: number } | null
  isRecording?: boolean
  onToggleRecording?: () => void
}) {
  const mode = useReplayStore(s => s.mode)
  const [networkInfo, setNetworkInfo] = useState<{ ips: string[], port: number } | null>(null)

  useEffect(() => {
    if (mode === 'live') {
      fetch('/api/live/network-info')
        .then(res => res.json())
        .then(data => setNetworkInfo(data))
        .catch(() => {})
    }
  }, [mode])

  return (
    <div
      className="flex items-center gap-3 px-4 py-1.5 shrink-0"
      style={{ background: '#0A0A0F', borderBottom: '1px solid #1E1E2E' }}
    >
      {/* logo */}
      <span
        className="text-lg font-extrabold tracking-wider cursor-pointer"
        style={{ color: '#E10600' }}
        onClick={onReset}
        title="Back to session selector"
      >
        GRIDSIGHT
      </span>

      <div className="w-px h-5" style={{ background: '#1E1E2E' }} />

      {/* mode badge */}
      <div className="flex items-center gap-1 text-[10px] font-bold group relative cursor-help">
        {mode === 'replay' ? (
          <><Monitor size={12} className="text-blue-400" /><span className="text-blue-400">REPLAY</span></>
        ) : simLiveActive ? (
          <>
            <div className="flex items-center gap-1.5">
              <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
              <span className="text-red-500 font-extrabold tracking-widest">REC</span>
            </div>
            {gameConnected && liveSessionInfo ? (
              <span className="text-green-400 ml-2">F1 25 — {liveSessionInfo.sessionType}</span>
            ) : gameConnected ? (
              <span className="text-green-400 ml-2">F1 25</span>
            ) : null}
            {networkInfo && (
              <div className="absolute top-full left-0 mt-1 w-48 p-2 bg-[#1A1A27] border border-gray-700 rounded shadow-lg text-[9px] text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                <div className="font-bold text-white mb-1">Local Network</div>
                {networkInfo.ips.map(ip => <div key={ip}>{ip}</div>)}
                <div className="mt-1 text-gray-500">Port: {networkInfo.port}</div>
              </div>
            )}
          </>
        ) : (
          <>
            <Radio size={12} className="text-green-400 animate-pulse" />
            <span className="text-green-400">LIVE</span>
            {networkInfo && (
              <div className="absolute top-full left-0 mt-1 w-48 p-2 bg-[#1A1A27] border border-gray-700 rounded shadow-lg text-[9px] text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity z-50 pointer-events-none">
                <div className="font-bold text-white mb-1">Local Network</div>
                {networkInfo.ips.map(ip => <div key={ip}>{ip}</div>)}
                <div className="mt-1 text-gray-500">Port: {networkInfo.port}</div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="w-px h-5" style={{ background: '#1E1E2E' }} />

      {/* session info */}
      <span className="text-xs text-gray-400 font-mono">
        {simLiveActive
          ? (liveSessionInfo
              ? `F1 25 — ${liveSessionInfo.sessionType} at ${liveSessionInfo.trackName} · ${liveSessionInfo.numActiveCars} cars`
              : 'F1 25 SIM')
          : `${year} R${round}${!isMobile ? ` — ${sessionType}` : ''}`
        }
      </span>

      {/* spacer */}
      <div className="flex-1" />

      {/* Stop sim button */}
      {simLiveActive && onStopSim && (
        <button
          onClick={onStopSim}
          className="flex items-center gap-1.5 px-3 py-1 rounded text-[10px] font-bold tracking-widest bg-red-600/20 text-red-400 hover:bg-red-600/40 transition-colors border border-red-500/30 mr-2"
        >
          <Square size={10} fill="currentColor" />
          STOP
        </button>
      )}

      {/* REC toggle button */}
      {simLiveActive && onToggleRecording && (
        <button
          onClick={onToggleRecording}
          className={`flex items-center gap-1.5 px-3 py-1 rounded text-[10px] font-bold tracking-widest transition-colors border mr-2 ${
            isRecording
              ? 'bg-red-600/30 text-red-400 border-red-500/50 hover:bg-red-600/50'
              : 'bg-[#1A1A27] text-gray-400 border-[#2A2A37] hover:bg-[#2A2A37] hover:text-white'
          }`}
        >
          <div className={`w-2 h-2 rounded-full ${isRecording ? 'bg-red-500 animate-pulse' : 'bg-gray-500'}`} />
          {isRecording ? 'STOP REC' : '⏺ REC'}
        </button>
      )}

      {/* insights menu toggle */}
      <div className="mr-2">
         <InsightsMenu />
      </div>

      {/* connection status */}
      <div className="flex items-center gap-1 text-[10px]">
        {isConnected ? (
          <><Wifi size={12} className="text-green-400" /><span className="text-green-400">{isMobile ? '●' : 'CONNECTED'}</span></>
        ) : connectionStatus === 'connecting' || connectionStatus === 'preparing' ? (
          <><Wifi size={12} className="text-yellow-400 animate-pulse" /><span className="text-yellow-400">{isMobile ? '●' : 'CONNECTING'}</span></>
        ) : (
          <><WifiOff size={12} className="text-gray-500" /><span className="text-gray-500">{isMobile ? '○' : 'OFFLINE'}</span></>
        )}
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   Race Layout (CSS Grid)
   ═══════════════════════════════════════════════════════════════════════ */

function RaceLayout({
  year, round, sessionType, send, isConnected, onOpenPip
}: {
  year: number; round: number; sessionType: string
  send: (msg: any) => void
  isConnected: boolean
  onOpenPip: () => void
}) {
  const panels = useUIStore(s => s.panels)
  const mode = useReplayStore(s => s.mode)
  const { isFullscreen, toggle } = useFullscreen()

  return (
    <div className="flex-1 flex overflow-hidden relative">
      {/* ── LEFT column (260px) ─────────────────────────────────── */}
      {panels.leaderboard && !isFullscreen && (
        <div
          className="shrink-0 flex flex-col h-full border-r"
          style={{ width: 260, borderColor: '#1E1E2E' }}
        >
          <div className="flex-1 min-h-0">
            <Leaderboard />
          </div>
          {panels.weather && (
            <div className="shrink-0 border-t overflow-hidden" style={{ height: 160, borderColor: '#1E1E2E' }}>
              <WeatherPanel />
            </div>
          )}
        </div>
      )}

      {/* ── CENTER (flex-1) ─────────────────────────────────────── */}
      <div className="flex-1 min-w-0 flex flex-col relative">
        {!isFullscreen && (
          <div className="flex items-center justify-between px-3 py-1.5 shrink-0 border-b" style={{ borderColor: '#1E1E2E' }}>
            <div className="flex items-center gap-2 text-[10px] font-extrabold tracking-widest text-gray-500">
              TRACK MAP
            </div>
            <div className="flex items-center gap-3">
              <button 
                 onClick={onOpenPip}
                 className="text-gray-400 hover:text-white transition-colors"
                 title="Open Picture-in-Picture Track Map"
              >
                <ExternalLink size={14} />
              </button>
              <button 
                 onClick={toggle}
                 className="text-gray-400 hover:text-white transition-colors"
                 title="Toggle Fullscreen (F / F11)"
              >
                <Maximize size={14} />
              </button>
            </div>
          </div>
        )}
        
        {/* Fullscreen exit button */}
        {isFullscreen && (
          <button 
             onClick={toggle}
             className="absolute top-4 right-4 z-50 bg-[#12121A]/80 p-2 rounded-md border border-[#1E1E2E] text-gray-400 hover:text-white transition-colors backdrop-blur-md"
             title="Exit Fullscreen (Esc / F)"
          >
            <Minimize size={16} />
          </button>
        )}

        {/* track map fills available space */}
        <div className="flex-1 min-h-0 relative">
          <TrackMapCanvas year={year} round={round} sessionType={sessionType} />
        </div>

        {/* playback controls + progress bar */}
        {panels.progressBar && !isFullscreen && mode === 'replay' && (
          <div className="shrink-0 border-t" style={{ borderColor: '#1E1E2E' }}>
            <PlaybackControls send={send} isConnected={isConnected} />
            <ProgressBar send={send} />
          </div>
        )}
      </div>

      {/* ── RIGHT column (320px) ────────────────────────────────── */}
      {!isFullscreen && (
        <div
          className="shrink-0 space-y-1 p-1 border-l flex flex-col"
          style={{ width: 320, borderColor: '#1E1E2E', height: '100%', overflow: 'hidden' }}
        >
          {panels.driverInfo && (
            <div className="shrink-0" style={{ maxHeight: 400 }}>
              <DriverInfoPanel />
            </div>
          )}
          {panels.telemetry && (
            <div className="flex-1 min-h-0 overflow-y-auto border border-[#1E1E2E] rounded bg-[#0A0A0F] scrollable">
              <TelemetryPanel />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   Qualifying Layout
   ═══════════════════════════════════════════════════════════════════════ */

function QualifyingLayout({
  year, round, sessionType, send, isConnected, onOpenPip
}: {
  year: number; round: number; sessionType: string
  send: (msg: any) => void
  isConnected: boolean
  onOpenPip: () => void
}) {
  const panels = useUIStore(s => s.panels)
  const mode = useReplayStore(s => s.mode)
  const { isFullscreen, toggle } = useFullscreen()

  return (
    <div className="flex-1 flex overflow-hidden">
      {/* ── LEFT column ──────────────────────────────────────────── */}
      {!isFullscreen && (
        <div
          className="shrink-0 flex flex-col overflow-hidden border-r"
          style={{ width: 260, borderColor: '#1E1E2E' }}
        >
          <div className="flex items-center justify-between px-3 py-1.5 shrink-0 border-b" style={{ borderColor: '#1E1E2E' }}>
            <div className="flex items-center gap-2 text-[10px] font-extrabold tracking-widest text-gray-500">
              TRACK MAP
            </div>
            <div className="flex items-center gap-3">
              <button 
                 onClick={onOpenPip}
                 className="text-gray-400 hover:text-white transition-colors"
                 title="Open Picture-in-Picture Track Map"
              >
                <ExternalLink size={14} />
              </button>
              <button 
                 onClick={toggle}
                 className="text-gray-400 hover:text-white transition-colors"
                 title="Toggle Fullscreen (F / F11)"
              >
                <Maximize size={14} />
              </button>
            </div>
          </div>
          {/* mini track map */}
          <div className="shrink-0 relative border-b" style={{ height: 240, borderColor: '#1E1E2E' }}>
            <TrackMapCanvas year={year} round={round} sessionType={sessionType} />
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 p-1 scrollable">
            {panels.weather && <WeatherPanel />}
            {panels.driverInfo && <DriverInfoPanel />}
          </div>
        </div>
      )}

      {/* ── CENTER: telemetry (full height, large charts) ────────── */}
      <div className="flex-1 min-w-0 flex flex-col relative">
        {/* Fullscreen track map overrides center if fullscreen */}
        {isFullscreen && (
          <button 
             onClick={toggle}
             className="absolute top-4 right-4 z-50 bg-[#12121A]/80 p-2 rounded-md border border-[#1E1E2E] text-gray-400 hover:text-white transition-colors backdrop-blur-md"
             title="Exit Fullscreen (Esc / F)"
          >
            <Minimize size={16} />
          </button>
        )}

        {isFullscreen ? (
          <div className="flex-1 relative bg-[#0A0A0F]">
            <TrackMapCanvas year={year} round={round} sessionType={sessionType} />
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-1 scrollable">
            {panels.telemetry && <TelemetryPanel />}
          </div>
        )}

        {/* playback controls */}
        {panels.progressBar && mode === 'replay' && !isFullscreen &&  (
          <div className="shrink-0 border-t" style={{ borderColor: '#1E1E2E' }}>
            <PlaybackControls send={send} isConnected={isConnected} />
            <ProgressBar send={send} />
          </div>
        )}
      </div>

      {/* ── RIGHT: qualifying leaderboard ─────────────────────────── */}
      {panels.leaderboard && !isFullscreen && (
        <div
          className="shrink-0 overflow-hidden border-l"
          style={{ width: 300, borderColor: '#1E1E2E' }}
        >
          <QualifyingLeaderboard />
        </div>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   App
   ═══════════════════════════════════════════════════════════════════════ */

export default function App() {
  const [session, setSession] = useState<{
    year: number; round: number; type: string
  } | null>(null)
  
  // App mode tracking: if a live feed is requested, standard replay is bypassed
  const [liveSessionRequested, setLiveSessionRequested] = useState<{year:number; round:number; type:string} | null>(null)
  const [liveDelay, setLiveDelay] = useState(0)
  const [pipOpen, setPipOpen] = useState(false)

  // ── F1 25 SIM live mode ────────────────────────────────────────────
  const [simLiveActive, setSimLiveActive] = useState(false)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [stoppedFilename, setStoppedFilename] = useState<string | null>(null)
  const [isRecording, setIsRecording] = useState(false)
  const [simReplayFilename, setSimReplayFilename] = useState<string | null>(null)

  // Use the matching socket based on the mode requested
  const sessionId = session && !liveSessionRequested && !simLiveActive ? `${session.year}_${session.round}_${session.type}` : null

  const replaySocket = useReplaySocket(sessionId)
  const simSocket = useLiveSocket(simLiveActive)
  const simReplay = useSimReplaySocket(simReplayFilename)
  // Live F1 SignalR socket — connects when liveSessionRequested is set
  const liveF1Socket = useLiveF1Socket(liveSessionRequested, liveDelay)
  // Determine which socket is "active" for the dashboard
  const activeSocket = simLiveActive ? simSocket : liveSessionRequested ? liveF1Socket : replaySocket
  
  const sessionLoaded = useReplayStore(s => s.sessionLoaded)
  const sessionType = useReplayStore(s => s.sessionType)
  const mode = useReplayStore(s => s.mode)
  const panels = useUIStore(s => s.panels)

  const isMobile = useBreakpoint() === 'mobile'
  const [liveStatus, setLiveStatus] = useState<any>(null)
  const [networkInfo, setNetworkInfo] = useState<{ ips: string[], port: number } | null>(null)

  useEffect(() => {
    // Poll live status when on session selector
    if (!session && !liveSessionRequested && !simLiveActive) {
      const checkLive = async () => {
        try {
          const r = await fetch('/api/live/status')
          const d = await r.json()
          setLiveStatus(d)
        } catch(e) {}
      }
      checkLive()
      const iv = setInterval(checkLive, 60000)
      return () => clearInterval(iv)
    }
  }, [session, liveSessionRequested, simLiveActive])

  useEffect(() => {
    if (mode === 'live') {
      fetch('/api/live/network-info')
        .then(res => res.json())
        .then(data => setNetworkInfo(data))
        .catch(() => {})
    }
  }, [mode])

  // Clear live status if connected
  useEffect(() => {
    if (session || liveSessionRequested || simLiveActive) setLiveStatus(null)
  }, [session, liveSessionRequested, simLiveActive])

  const handleSessionSelected = useCallback((year: number, round: number, type: string) => {
    setSession({ year, round, type })
  }, [])

  const handleReset = useCallback(() => {
    setSession(null)
    setLiveSessionRequested(null)
    setLiveDelay(0)
    setSimLiveActive(false)
    setSimReplayFilename(null)
    setShowSaveDialog(false)
    useReplayStore.setState({ sessionLoaded: false, mode: 'replay' })
  }, [])

  // ── Start F1 25 sim live ───────────────────────────────────────────
  const handleSimLiveStart = useCallback(() => {
    setSimLiveActive(true)
    setSimReplayFilename(null)
    setShowSaveDialog(false)
    setStoppedFilename(null)
  }, [])

  // ── Stop F1 25 sim live ────────────────────────────────────────────
  const handleStopSim = useCallback(() => {
    // Grab the recording filename before disconnecting
    const fname = simSocket.recordingFilename
    simSocket.disconnect()
    setSimLiveActive(false)
    useReplayStore.setState({ isPlaying: false, mode: 'replay' })
    if (fname) {
      setStoppedFilename(fname)
      setShowSaveDialog(true)
      setSaveName('')
    } else {
      handleReset()
    }
  }, [simSocket, handleReset])

  // ── Toggle recording ──────────────────────────────────────────────
  const handleToggleRecording = useCallback(async () => {
    try {
      if (isRecording) {
        await fetch('/api/sim/record/stop', { method: 'POST' })
        setIsRecording(false)
      } else {
        await fetch('/api/sim/record/start', { method: 'POST' })
        setIsRecording(true)
      }
    } catch (e) {
      console.error('Failed to toggle recording:', e)
    }
  }, [isRecording])

  // ── Save session ──────────────────────────────────────────────────
  const handleSaveSession = useCallback(async () => {
    if (!stoppedFilename || !saveName.trim()) return
    try {
      await fetch(`/api/sim/sessions/${encodeURIComponent(stoppedFilename)}/save?name=${encodeURIComponent(saveName.trim())}`, { method: 'POST' })
    } catch (e) {
      console.error('Failed to save session:', e)
    }
    setShowSaveDialog(false)
    handleReset()
  }, [stoppedFilename, saveName, handleReset])

  const isQualifying = sessionType === 'Q'

  /* ── Save session dialog ────────────────────────────────────────── */
  if (showSaveDialog) {
    return (
      <div className="fixed inset-0 z-[100] flex items-center justify-center" style={{ background: '#0A0A0F' }}>
        <div
          className="w-full max-w-md rounded-xl overflow-hidden p-6"
          style={{
            background: '#12121A',
            border: '1px solid #1E1E2E',
            boxShadow: '0 0 80px rgba(225,6,0,0.08)',
          }}
        >
          <h1 className="text-2xl font-extrabold tracking-[0.15em] text-center mb-6" style={{ color: '#E10600' }}>
            SAVE SESSION
          </h1>
          <p className="text-gray-400 text-xs mb-4 text-center">
            Your F1 25 sim session has been recorded. Give it a name to save, or discard.
          </p>
          <input
            type="text"
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            placeholder="e.g. Monza Hotlap"
            className="w-full py-2.5 px-3 rounded-md text-sm text-white border-none outline-none mb-4"
            style={{ background: '#1A1A27' }}
            autoFocus
            onKeyDown={(e) => e.key === 'Enter' && handleSaveSession()}
          />
          <div className="flex gap-3">
            <button
              onClick={handleSaveSession}
              disabled={!saveName.trim()}
              className="flex-1 py-3 rounded-md text-sm font-extrabold tracking-[0.15em] transition-all disabled:opacity-30 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              style={{
                background: saveName.trim() ? 'linear-gradient(135deg, #E10600, #B00500)' : '#1A1A27',
                color: '#fff',
                boxShadow: saveName.trim() ? '0 4px 20px rgba(225,6,0,0.3)' : 'none',
              }}
            >
              <Save size={14} />
              SAVE
            </button>
            <button
              onClick={handleReset}
              className="px-6 py-3 rounded-md text-sm font-bold tracking-wider transition-all bg-[#1A1A27] text-gray-400 hover:text-white hover:bg-[#2A2A37]"
            >
              DISCARD
            </button>
          </div>
        </div>
      </div>
    )
  }

  /* ── show session selector if no session loaded ─────────────────── */
  if ((!session && !liveSessionRequested && !simLiveActive) || (!sessionLoaded && !liveSessionRequested && !simLiveActive)) {
    return (
      <>
        {/* Helper overlay for live status from fastf1 */}
        {liveStatus?.live && !session && !liveSessionRequested && (
          <div className="fixed top-4 left-1/2 -translate-x-1/2 z-[200] bg-green-500/20 border border-green-500 rounded p-4 shadow-2xl backdrop-blur flex items-center gap-4 cursor-pointer hover:bg-green-500/30 transition-colors"
                onClick={() => setLiveSessionRequested({ year: liveStatus.year, round: liveStatus.round, type: liveStatus.session_type })}
          >
            <div className="w-3 h-3 bg-green-500 rounded-full animate-pulse" />
            <div>
              <div className="text-white font-bold tracking-wider">LIVE F1 SESSION DETECTED</div>
              <div className="text-sm text-green-100">{liveStatus.event_name} - {liveStatus.session_type}</div>
            </div>
            <button className="bg-green-600 text-white text-xs font-bold px-3 py-1.5 rounded ml-2">CONNECT</button>
          </div>
        )}
        <SessionSelector 
          onSessionSelected={handleSessionSelected} 
          onLiveSelected={(y, r, t, delay) => {
            setLiveDelay(delay ?? 0)
            setLiveSessionRequested({ year: y, round: r, type: t })
          }}
          onSimLiveStart={handleSimLiveStart}
          onSimReplay={(filename) => {
            setSimReplayFilename(filename)
            // The useSimReplaySocket hook will auto-connect and auto-play
          }}
          liveSessionInfo={simSocket.liveSessionInfo}
        />
      </>
    )
  }

  const activeSession = liveSessionRequested || session

  /* ── main dashboard ─────────────────────────────────────────────── */
  return (
    <div className="flex flex-col h-screen overflow-hidden" style={{ background: '#0A0A0F' }}>
      {/* ── fixed overlays ──────────────────────────────────────── */}
      <FastestLapBanner />
      {panels.overtakes && <OvertakeFeed />}

      {/* SESSION ENDED — REPLAY indicator for live F1 */}
      {liveSessionRequested && liveF1Socket.sessionEnded && (
        <div className="fixed top-12 left-1/2 -translate-x-1/2 z-[60] px-6 py-2.5 rounded-lg shadow-2xl border border-amber-500/40 flex items-center gap-3"
             style={{ background: 'linear-gradient(135deg, rgba(245,158,11,0.15), rgba(217,119,6,0.1))', backdropFilter: 'blur(12px)' }}>
          <div className="w-2.5 h-2.5 bg-amber-500 rounded-full animate-pulse" />
          <span className="text-amber-400 text-xs font-extrabold tracking-[0.2em]">SESSION ENDED — REPLAY</span>
        </div>
      )}

      {/* speed trap — top-right */}
      {panels.speedTrap && (
        <div className="fixed top-12 right-3 z-30" style={{ width: 200 }}>
          <SpeedTrap />
        </div>
      )}

      {/* track status — top center */}
      <div className="fixed top-10 left-1/2 -translate-x-1/2 z-30 w-[600px] max-w-[80vw]">
        <TrackStatusBanner />
      </div>

      {/* ── top bar ─────────────────────────────────────────────── */}
      <TopBar
        year={activeSession?.year || 2024}
        round={activeSession?.round || 1}
        sessionType={activeSession?.type || 'R'}
        connectionStatus={activeSocket.connectionStatus}
        isConnected={activeSocket.isConnected}
        onReset={handleReset}
        isMobile={isMobile}
        simLiveActive={simLiveActive}
        gameConnected={simLiveActive ? simSocket.gameConnected : false}
        onStopSim={simLiveActive ? handleStopSim : undefined}
        liveSessionInfo={simLiveActive ? simSocket.liveSessionInfo : null}
        isRecording={isRecording}
        onToggleRecording={simLiveActive ? handleToggleRecording : undefined}
      />

      {/* Connect F1 25 helper panel (shown when sim is live but game hasn't sent data yet) */}
      {simLiveActive && !simSocket.gameConnected && networkInfo && networkInfo.ips && (
        <div className="bg-[#12121A] border-b border-[#1E1E2E] px-4 py-2 shrink-0 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <Radio size={14} className="text-red-500 animate-pulse" />
            <span className="font-bold text-white tracking-widest">WAITING FOR F1 25</span>
            <span className="ml-2">Set your game's Telemetry to: IP <strong className="text-white bg-[#1A1A27] px-1 rounded">{networkInfo.ips[0] || '127.0.0.1'}</strong> / Port <strong className="text-white bg-[#1A1A27] px-1 rounded">{networkInfo.port}</strong></span>
          </div>
        </div>
      )}

      {/* ── layout (Race or Qualifying or Mobile) ─────────────────── */}
      {isMobile ? (
        <MobileLayout
          year={activeSession?.year || 2024}
          round={activeSession?.round || 1}
          sessionType={activeSession?.type || 'R'}
          send={activeSocket.send}
          isConnected={activeSocket.isConnected}
        />
      ) : isQualifying && !simLiveActive ? (
        <QualifyingLayout
          year={activeSession?.year || 2024}
          round={activeSession?.round || 1}
          sessionType={activeSession?.type || 'R'}
          send={activeSocket.send}
          isConnected={activeSocket.isConnected}
          onOpenPip={() => setPipOpen(true)}
        />
      ) : (
        <RaceLayout
          year={activeSession?.year || 2024}
          round={activeSession?.round || 1}
          sessionType={activeSession?.type || 'R'}
          send={activeSocket.send}
          isConnected={activeSocket.isConnected}
          onOpenPip={() => setPipOpen(true)}
        />
      )}

      {/* ── PiP Window ──────────────────────────────────────────────── */}
      {pipOpen && (
        <PiPWindow onClose={() => setPipOpen(false)}>
           <div className="flex flex-col h-full overflow-hidden" style={{ background: '#0A0A0F' }}>
              <div className="shrink-0 flex w-full justify-center" style={{ background: '#0A0A0F' }}>
                 <TrackStatusBanner />
              </div>
              <div className="flex-1 min-h-0 relative border-b" style={{ borderColor: '#1E1E2E' }}>
                 <TrackMapCanvas year={activeSession?.year || 2024} round={activeSession?.round || 1} sessionType={activeSession?.type || 'R'} />
              </div>
              <div className="shrink-0 overflow-y-auto" style={{ height: 200, background: '#12121A' }}>
                 <Leaderboard compact />
              </div>
           </div>
        </PiPWindow>
      )}
    </div>
  )
}

