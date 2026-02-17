import { useState, useEffect, useCallback } from 'react'
import { Loader2, Gamepad, Play, Trash2, Clock, Film } from 'lucide-react'

/* ── types ────────────────────────────────────────────────────────────── */

interface RoundInfo {
  round_number: number
  event_name: string
  date: string
  country: string
}

interface SessionTypeInfo {
  key: string
  name: string
}

interface SimSession {
  filename: string
  track: string
  date: string
  duration: number
  frame_count: number
  lap_count: number
  size_bytes: number
}

interface Props {
  onSessionSelected: (year: number, round: number, type: string) => void
  onLiveSelected?: (year: number, round: number, type: string, delay?: number) => void
  onSimLiveStart?: () => void
  onSimReplay?: (filename: string) => void
  liveSessionInfo?: { sessionType: string; trackName: string; numActiveCars: number } | null
}

/* ── component ────────────────────────────────────────────────────────── */

export default function SessionSelector({ onSessionSelected, onLiveSelected, onSimLiveStart, onSimReplay, liveSessionInfo }: Props) {
  const [year, setYear] = useState(2024)
  const [rounds, setRounds] = useState<RoundInfo[]>([])
  const [selectedRound, setSelectedRound] = useState<number | null>(null)
  const [types, setTypes] = useState<SessionTypeInfo[]>([])
  const [selectedType, setSelectedType] = useState<string | null>(null)
  const [isPolling, setIsPolling] = useState(false)
  const [pollData, setPollData] = useState<{status: string, progress?: number} | null>(null)
  const [loadingRounds, setLoadingRounds] = useState(false)
  const [loadingTypes, setLoadingTypes] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [years, setYears] = useState<number[]>([2023, 2024, 2025, 2026])
  const [toast, setToast] = useState<string | null>(null)

  const [liveRealStatus, setLiveRealStatus] = useState<any>(null)
  const [networkInfo, setNetworkInfo] = useState<{ ips: string[], port: number } | null>(null)
  const [f125Connected, setF125Connected] = useState(false)
  const [savedSessions, setSavedSessions] = useState<SimSession[]>([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const [liveDelay, setLiveDelay] = useState(0)
  
  useEffect(() => {
    fetch('/api/live/status')
      .then(r => r.json())
      .then(d => setLiveRealStatus(d))
      .catch(() => {})

    fetch('/api/live/network-info')
      .then(r => r.json())
      .then(d => setNetworkInfo(d))
      .catch(() => {})

    // Fetch saved sim sessions
    setLoadingSessions(true)
    fetch('/api/sim/sessions')
      .then(r => r.json())
      .then(d => {
        setSavedSessions(d.sessions ?? [])
        setLoadingSessions(false)
      })
      .catch(() => setLoadingSessions(false))
  }, [])

  // Clear any existing errors when selection changes
  useEffect(() => {
    setError(null)
  }, [year, selectedRound, selectedType])

  /* ── fetch years on mount ───────────────────────────────────────── */
  useEffect(() => {
    fetch('/api/sessions/years')
      .then(r => r.json())
      .then(data => {
        if (data.years && Array.isArray(data.years)) {
          setYears(data.years)
        } else if (Array.isArray(data)) {
          setYears(data)
        }
      })
      .catch(() => {
        // fallback to hardcoded if API fails
        setYears([2023, 2024, 2025, 2026])
      })
  }, [])

  /* ── 2026 regulations toast ─────────────────────────────────────── */
  useEffect(() => {
    if (year >= 2026 && rounds.length > 0) {
      setToast('2026 Regulations Active — Active Aero era, Straight Mode replaces DRS')
      const t = setTimeout(() => setToast(null), 5000)
      return () => clearTimeout(t)
    }
  }, [year, rounds.length])

  /* ── fetch rounds when year changes ─────────────────────────────── */
  useEffect(() => {
    setLoadingRounds(true)
    setRounds([])
    setSelectedRound(null)
    setTypes([])
    setSelectedType(null)
    setError(null)

    fetch(`/api/sessions/${year}/rounds`)
      .then(r => {
        if (!r.ok) throw new Error(`Failed to load schedule for ${year}`)
        return r.json()
      })
      .then(data => {
        setRounds(data.rounds ?? [])
        setLoadingRounds(false)
      })
      .catch(() => {
        setError('Failed to load schedule. Please try again.')
        setLoadingRounds(false)
      })
  }, [year])

  /* ── fetch types when round changes ─────────────────────────────── */
  useEffect(() => {
    if (selectedRound == null) return
    setLoadingTypes(true)
    setTypes([])
    setSelectedType(null)

    fetch(`/api/sessions/${year}/${selectedRound}/types`)
      .then(r => {
        if (!r.ok) throw new Error('Failed to load session types')
        return r.json()
      })
      .then(data => {
        setTypes(data.types ?? [])
        setLoadingTypes(false)
      })
      .catch(() => {
        setError('Failed to load session types. Please try again.')
        setLoadingTypes(false)
      })
  }, [year, selectedRound])

  /* ── load session ───────────────────────────────────────────────── */
  const handleLoad = useCallback(() => {
    if (selectedRound == null || !selectedType) return
    setError(null)
    setIsPolling(true)
    setPollData(null)
  }, [selectedRound, selectedType])

  /* ── poll status ────────────────────────────────────────────────── */
  useEffect(() => {
    if (!isPolling) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    let triggeredPreload = false

    const poll = async () => {
      try {
        const res = await fetch(`/api/sessions/${year}/${selectedRound}/${selectedType}/status`)
        if (!res.ok) throw new Error('Status check failed')
        const data = await res.json()
        if (disposed) return

        setPollData(data)

        if (data.status === 'cached') {
           setIsPolling(false)
           onSessionSelected(year, selectedRound!, selectedType!)
        } else if (data.status === 'error') {
           // We intentionally do not clear isPolling here. 
           // The overlay will show the error state with a retry button.
        } else if (data.status === 'not_cached') {
           if (!triggeredPreload) {
             triggeredPreload = true
             fetch('/api/cache/preload', {
               method: 'POST',
               headers: { 'Content-Type': 'application/json' },
               body: JSON.stringify({ year, round: selectedRound, type: selectedType })
             }).catch(console.error)
           }
           timer = setTimeout(poll, 2000)
        } else {
           // loading
           timer = setTimeout(poll, 2000)
        }
      } catch {
        if (disposed) return
        setPollData({ status: 'error' })
      }
    }

    poll()
    return () => {
      disposed = true
      clearTimeout(timer)
    }
  }, [isPolling, year, selectedRound, selectedType, onSessionSelected])

  const selectedRoundInfo = rounds.find(r => r.round_number === selectedRound)

  /* ── grouping logic ─────────────────────────────────────────────── */
  type EraKey = 'v6_hybrid' | 'ground_effect' | 'active_aero'
  
  const getEra = (y: number): EraKey => {
    if (y <= 2021) return 'v6_hybrid'
    if (y <= 2025) return 'ground_effect'
    return 'active_aero'
  }

  const eraColors: Record<EraKey, string> = {
    v6_hybrid: '#3B82F6',
    ground_effect: '#14B8A6',
    active_aero: '#A855F7',
  }

  const eraLabels: Record<EraKey, string> = {
    v6_hybrid: 'V6 HYBRID',
    ground_effect: 'GROUND EFFECT',
    active_aero: 'ACTIVE AERO',
  }

  const groupedYears = years.reduce((acc, y) => {
    const era = getEra(y)
    if (!acc[era]) acc[era] = []
    acc[era].push(y)
    return acc
  }, {} as Record<EraKey, number[]>)

  const eraOrder: EraKey[] = ['v6_hybrid', 'ground_effect', 'active_aero']

  /* ── render ─────────────────────────────────────────────────────── */

  if (isPolling || pollData?.status === 'cached') {
    const st = pollData?.status

    return (
      <div className="fixed inset-0 z-[100] flex flex-col items-center justify-center p-8 text-center" style={{ background: '#0A0A0F' }}>
        <h1 className="text-4xl font-extrabold tracking-[0.25em] mb-12" style={{ color: '#E10600' }}>
          GRIDSIGHT
        </h1>

        {st === 'error' ? (
          <div className="flex flex-col items-center gap-6">
            <span className="text-red-500 text-lg font-bold tracking-wider">
              Session unavailable — try a different round
            </span>
            <button
              onClick={() => {
                setIsPolling(false)
                setPollData(null)
                setError(null)
              }}
              className="px-6 py-3 rounded-md text-sm font-extrabold tracking-[0.2em] transition-all bg-[#1A1A27] text-white hover:bg-[#2A2A37]"
            >
              SELECT ANOTHER SESSION
            </button>
          </div>
        ) : (
          <>
            <Loader2 size={60} className="text-[#E10600] animate-spin mb-6" />

            <div className="flex flex-col gap-2">
              {(!pollData || st === 'checking') && (
                <span className="text-white text-lg font-bold tracking-wider animate-pulse">
                  Checking cache status…
                </span>
              )}

              {st === 'not_cached' && (
                <span className="text-white text-lg font-bold tracking-wider animate-pulse">
                  Downloading session data — this may take 2-3 minutes on first load
                </span>
              )}

              {st === 'loading' && (
                <span className="text-white text-lg font-bold tracking-wider animate-pulse">
                  Loading telemetry... {pollData?.progress ?? 0}%
                </span>
              )}

              {st === 'cached' && (
                <span className="text-white text-lg font-bold tracking-wider animate-pulse">
                  Connecting...
                </span>
              )}

              <span className="text-gray-500 text-sm mt-4">
                {year} R{selectedRound} — {selectedRoundInfo?.event_name ?? ''} — {selectedType}
              </span>
            </div>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-[100] flex flex-col md:flex-row items-center justify-start md:justify-center px-4 py-8 md:p-0 gap-6 md:gap-8 overflow-y-auto w-full" style={{ background: '#0A0A0F' }}>
      {toast && (
        <div className="fixed top-8 left-1/2 -translate-x-1/2 z-[200] px-6 py-3 rounded-lg shadow-2xl animate-pulse text-white text-sm font-bold tracking-wider border border-white/20" style={{ background: '#A855F7' }}>
          {toast}
        </div>
      )}

      <div
        className="w-full max-w-lg rounded-xl overflow-hidden shrink-0"
        style={{
          background: '#12121A',
          border: '1px solid #1E1E2E',
          boxShadow: '0 0 80px rgba(225,6,0,0.08)',
        }}
      >
        {/* ── header ──────────────────────────────────────────────── */}
        <div className="px-4 md:px-6 pt-5 md:pt-6 pb-3 md:pb-4 text-center">
          <h1
            className="text-[28px] md:text-3xl font-extrabold tracking-[0.25em]"
            style={{ color: '#E10600' }}
          >
            GRIDSIGHT
          </h1>
          <p className="text-gray-500 text-[11px] md:text-xs mt-1 tracking-widest">
            F1 TELEMETRY DASHBOARD
          </p>
        </div>

        <div className="px-4 md:px-6 pb-5 md:pb-6 space-y-4">
          {/* ── year ──────────────────────────────────────────────── */}
          <div>
            <label className="text-[10px] text-gray-500 font-bold tracking-widest block mb-2 md:mb-3">SEASON</label>
            <div className="flex justify-between gap-2 md:gap-4">
              {eraOrder.map(era => {
                const yearsInEra = groupedYears[era]
                if (!yearsInEra || yearsInEra.length === 0) return null
                
                return (
                  <div key={era} className="flex flex-col border-l-2 pl-2 md:pl-3 flex-1 min-w-0" style={{ borderColor: eraColors[era] }}>
                    <span className="text-[9px] font-bold tracking-widest mb-1.5 md:mb-2 truncate" style={{ color: eraColors[era] }}>
                      {eraLabels[era]}
                    </span>
                    <div className="grid grid-cols-2 min-[350px]:grid-cols-3 md:flex md:flex-wrap gap-1 md:gap-1.5">
                      {yearsInEra.map((y) => (
                        <button
                          key={y}
                          onClick={() => setYear(y)}
                          className="py-1.5 md:px-2.5 w-full md:w-auto md:min-w-[3rem] rounded-md text-[14px] font-bold transition-all hover:brightness-125"
                          style={{
                            background: year === y ? '#E10600' : '#12121A',
                            color: '#fff',
                            border: year === y ? '1px solid #E10600' : '1px solid #1E1E2E'
                          }}
                        >
                          {y}
                        </button>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* ── round ─────────────────────────────────────────────── */}
          <div>
            <label className="text-[10px] text-gray-500 font-bold tracking-widest block mb-1">GRAND PRIX</label>
            {loadingRounds ? (
              <div className="flex items-center gap-2 py-3 text-gray-500 text-xs">
                <Loader2 size={14} className="animate-spin" /> Loading schedule…
              </div>
            ) : (
              <select
                value={selectedRound ?? ''}
                onChange={e => setSelectedRound(Number(e.target.value) || null)}
                className="w-full py-2.5 px-3 rounded-md text-sm text-white border-none outline-none cursor-pointer"
                style={{ background: '#1A1A27' }}
              >
                <option value="">Select Grand Prix…</option>
                {rounds.map(r => (
                  <option key={r.round_number} value={r.round_number}>
                    R{r.round_number} — {r.event_name} ({r.country}) — {r.date}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* ── session type ──────────────────────────────────────── */}
          {selectedRound != null && (
            <div>
              <label className="text-[10px] text-gray-500 font-bold tracking-widest block mb-1">SESSION</label>
              {loadingTypes ? (
                <div className="flex items-center gap-2 py-3 text-gray-500 text-xs">
                  <Loader2 size={14} className="animate-spin" /> Loading sessions…
                </div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {types.map(t => (
                    <button
                      key={t.key}
                      onClick={() => setSelectedType(t.key)}
                      className="px-3 py-2 rounded-md text-xs font-bold transition-colors"
                      style={{
                        background: selectedType === t.key ? '#E10600' : '#1A1A27',
                        color: selectedType === t.key ? '#fff' : '#666',
                      }}
                    >
                      {t.name}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── error ─────────────────────────────────────────────── */}
          {error && (
            <div className="text-red-400 text-xs bg-red-900/20 px-3 py-2 rounded-md">{error}</div>
          )}

          {/* ── load button ───────────────────────────────────────── */}
          <button
            onClick={handleLoad}
            disabled={selectedRound == null || !selectedType}
            className="w-full py-3 rounded-md text-sm font-extrabold tracking-[0.2em] transition-all disabled:opacity-30 disabled:cursor-not-allowed"
            style={{
              background: selectedRound != null && selectedType
                ? 'linear-gradient(135deg, #E10600, #B00500)'
                : '#1A1A27',
              color: '#fff',
              boxShadow: selectedRound != null && selectedType
                ? '0 4px 20px rgba(225,6,0,0.3)'
                : 'none',
            }}
          >
            LOAD SESSION
          </button>
        </div>
      </div>

      {/* ── LIVE SECTIONS ────────────────────────────────────────────── */}
      <div className="w-full max-w-lg flex flex-col gap-4 shrink-0">
        {/* LIVE RACE */}
        <div className="rounded-xl p-3 md:p-5 border border-[#1E1E2E]" style={{ background: '#12121A' }}>
          <div className="hidden md:flex items-center justify-between mb-2">
            <h2 className="text-xs font-bold tracking-[0.15em] text-gray-500">LIVE RACE</h2>
          </div>
          {liveRealStatus?.live ? (
            <div className="flex flex-col gap-3 md:mt-4">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse shrink-0" />
                <span className="text-green-500 font-bold text-xs md:text-sm whitespace-nowrap">● LIVE NOW</span>
                <div className="text-white font-mono text-xs md:text-sm truncate ml-2">
                  {liveRealStatus.event_name} — {liveRealStatus.session_type}
                </div>
              </div>

              {/* Delay slider */}
              <div className="bg-[#1A1A27] rounded-lg px-3 py-2.5">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] text-gray-500 font-bold tracking-widest">BROADCAST DELAY</span>
                  <span className="text-xs font-mono text-white">{liveDelay}s</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={60}
                  step={5}
                  value={liveDelay}
                  onChange={e => setLiveDelay(Number(e.target.value))}
                  className="w-full h-1.5 rounded-full appearance-none cursor-pointer"
                  style={{
                    background: `linear-gradient(to right, #E10600 ${(liveDelay / 60) * 100}%, #2A2A37 ${(liveDelay / 60) * 100}%)`,
                  }}
                />
                <div className="flex justify-between text-[9px] text-gray-600 mt-1">
                  <span>0s</span>
                  <span>30s</span>
                  <span>60s</span>
                </div>
              </div>

              <button
                onClick={() => onLiveSelected?.(liveRealStatus.year, liveRealStatus.round, liveRealStatus.session_type, liveDelay)}
                className="w-full px-4 py-2.5 rounded bg-green-600/20 text-green-400 font-bold tracking-widest text-[10px] hover:bg-green-600/40 transition-colors border border-green-500/30"
              >
                {liveDelay > 0 ? `CONNECT WITH ${liveDelay}s DELAY` : 'CONNECT LIVE'}
              </button>
            </div>
          ) : liveRealStatus?.starts_in_minutes != null && liveRealStatus.starts_in_minutes < 60 ? (
            <div className="text-white text-[11px] md:text-sm animate-pulse mt-0 md:mt-2">
              Session starting in {liveRealStatus.starts_in_minutes} minutes
            </div>
          ) : (
            <div className="text-gray-500 text-[11px] md:text-sm mt-0 md:mt-2">
              No live session — check back on race weekends
            </div>
          )}
        </div>

        {/* F1 25 SIMULATOR */}
        <div className="rounded-xl p-3 md:p-5 border border-[#1E1E2E]" style={{ background: '#12121A' }}>
          <div className="flex items-center gap-2 mb-0 md:mb-3">
            <Gamepad size={16} className="text-gray-400 hidden md:block" />
            <h2 className="text-[10px] md:text-xs font-bold tracking-[0.15em] text-gray-500">F1 25 SIMULATOR</h2>
          </div>
          {f125Connected ? (
            <div className="flex flex-col gap-1.5 mt-2 md:mt-4 bg-green-900/20 p-2 md:p-3 rounded border border-green-500/20">
              <div className="flex items-center gap-2">
                <div className="w-2.5 h-2.5 bg-green-500 rounded-full animate-pulse" />
                <span className="text-green-500 font-bold tracking-widest text-[11px]">
                  {liveSessionInfo
                    ? `● F1 25 Connected — ${liveSessionInfo.sessionType} at ${liveSessionInfo.trackName}`
                    : 'F1 25 CONNECTED'
                  }
                </span>
              </div>
              {liveSessionInfo && (
                <span className="text-green-400/70 text-[10px] font-mono ml-[18px]">
                  {liveSessionInfo.numActiveCars} cars
                </span>
              )}
            </div>
          ) : (
            <>
              {networkInfo && (
                <div className="text-gray-400 text-[10px] md:text-xs mb-3 md:mb-4 bg-[#1A1A27] p-2 md:p-3 rounded font-mono">
                  IP: <strong className="text-white">{networkInfo.ips[0] || '127.0.0.1'}</strong> PORT: <strong className="text-white">{networkInfo.port}</strong>
                </div>
              )}
              <button
                onClick={() => {
                  if (onSimLiveStart) {
                    onSimLiveStart()
                  }
                }}
                className="w-full px-4 py-2 rounded text-blue-400 font-bold tracking-widest text-[10px] bg-blue-500/10 hover:bg-blue-500/20 transition-colors border border-blue-500/30"
              >
                START SIM SESSION
              </button>
            </>
          )}
        </div>

        {/* SAVED SIM SESSIONS */}
        {(savedSessions.length > 0 || loadingSessions) && (
          <div className="rounded-xl p-3 md:p-5 border border-[#1E1E2E]" style={{ background: '#12121A' }}>
            <div className="flex items-center gap-2 mb-2 md:mb-3">
              <Film size={16} className="text-gray-400 hidden md:block" />
              <h2 className="text-[10px] md:text-xs font-bold tracking-[0.15em] text-gray-500">SAVED SIM SESSIONS</h2>
            </div>
            {loadingSessions ? (
              <div className="flex items-center gap-2 py-3 text-gray-500 text-xs">
                <Loader2 size={14} className="animate-spin" /> Loading sessions…
              </div>
            ) : savedSessions.length === 0 ? (
              <div className="text-gray-600 text-xs">No saved sessions</div>
            ) : (
              <div className="space-y-2 max-h-[240px] overflow-y-auto scrollable pr-1">
                {savedSessions.map(s => (
                  <div
                    key={s.filename}
                    className="flex items-center justify-between gap-3 bg-[#1A1A27] rounded-lg px-3 py-2 group hover:bg-[#22222F] transition-colors"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-white text-xs font-bold truncate">{s.track}</div>
                      <div className="flex items-center gap-3 text-[10px] text-gray-500 mt-0.5">
                        <span className="flex items-center gap-1">
                          <Clock size={10} />
                          {s.duration > 60 ? `${Math.floor(s.duration / 60)}m ${Math.round(s.duration % 60)}s` : `${Math.round(s.duration)}s`}
                        </span>
                        <span>{s.lap_count} laps</span>
                        <span>{new Date(s.date).toLocaleDateString()}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => onSimReplay?.(s.filename)}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded text-[10px] font-bold tracking-widest bg-blue-500/10 text-blue-400 hover:bg-blue-500/25 transition-colors border border-blue-500/20"
                      >
                        <Play size={10} fill="currentColor" />
                        REPLAY
                      </button>
                      <button
                        onClick={async () => {
                          if (!confirm(`Delete session "${s.track}"?`)) return
                          await fetch(`/api/sim/sessions/${encodeURIComponent(s.filename)}`, { method: 'DELETE' })
                          setSavedSessions(prev => prev.filter(x => x.filename !== s.filename))
                        }}
                        className="p-1.5 rounded text-gray-500 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                        title="Delete session"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
