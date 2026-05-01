import { useState, useEffect, useRef } from 'react'
import { useUIStore } from '../../store/uiStore'
import { useReplayStore } from '../../store/replayStore'

function getFlagColor(flag: string | undefined): string {
  if (!flag) return '#6b7280'
  const target = flag.toUpperCase()
  if (target.includes('GREEN') || target.includes('CLEAR')) return '#22c55e'
  if (target.includes('YELLOW')) return '#eab308'
  if (target.includes('RED')) return '#ef4444'
  if (target.includes('BLUE')) return '#3b82f6'
  return '#e86100' // orange
}

interface ActiveMsg {
  id: string
  msg: any
  addedAt: number
}

function isPersistent(msg: any, trackStatus: string): boolean {
  const m = msg.Message.toUpperCase()
  if (trackStatus === 'SC' && m.includes('SAFETY CAR') && !m.includes('IN THIS LAP')) return true
  if (trackStatus === 'VSC' && m.includes('VIRTUAL SAFETY CAR')) return true
  if (trackStatus === 'RED' && m.includes('RED FLAG')) return true
  return false
}

export default function RaceControlPanel() {
  const messages = useReplayStore(s => s.raceControl.messages)
  const trackStatus = useUIStore(s => s.trackStatus)

  const [active, setActive] = useState<ActiveMsg[]>([])
  const seenIds = useRef<Set<string>>(new Set())

  // Ingest new msgs
  const isInitialMount = useRef(true)
  useEffect(() => {
    const now = Date.now()
    const newMsgs = messages.filter(m => {
      const id = `${m.Time}-${m.Message}`
      if (!seenIds.current.has(id)) {
        seenIds.current.add(id)
        return true
      }
      return false
    })

    if (isInitialMount.current) {
      isInitialMount.current = false
      // Only keep the genuinely persistent ones from the past on initial mount
      const currentTrackStatus = useUIStore.getState().trackStatus
      const persistentOnly = newMsgs.filter(m => isPersistent(m, currentTrackStatus))
      if (persistentOnly.length > 0) {
         setActive(persistentOnly.map(m => ({ id: `${m.Time}-${m.Message}`, msg: m, addedAt: now })))
      }
      return
    }

    if (newMsgs.length > 0) {
      const additions = newMsgs.map(m => ({ id: `${m.Time}-${m.Message}`, msg: m, addedAt: now }))
      setActive(prev => [...prev, ...additions])
    }
  }, [messages])

  // Process auto-dismiss + persistent
  useEffect(() => {
    const timer = setInterval(() => {
      const now = Date.now()
      setActive(prev => prev.filter(a => {
        if (isPersistent(a.msg, trackStatus)) return true
        return now - a.addedAt < 12000
      }))
    }, 1000)
    return () => clearInterval(timer)
  }, [trackStatus])

  const displayMsgs = active.slice(-3).reverse()

  if (displayMsgs.length === 0) return null

  return (
    <div className="absolute top-2 left-2 z-40 flex flex-col gap-1 w-full max-w-[280px] pointer-events-none">
      <style>{`
        @keyframes rcSlideIn {
          from { opacity: 0; transform: translateY(-10px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .rc-toast {
          animation: rcSlideIn 0.3s ease-out forwards;
        }
      `}</style>
      
      {displayMsgs.map(item => {
        const m = item.msg
        const color = getFlagColor(m.Flag)
        return (
          <div
            key={item.id}
            className="rc-toast overflow-hidden rounded-lg pointer-events-auto flex shadow-lg"
            style={{ background: 'rgba(10, 10, 15, 0.9)', padding: '6px 10px', borderLeft: `4px solid ${color}` }}
          >
            <div className="flex-1 flex flex-col min-w-0">
              <div className="flex justify-between items-start mb-0.5">
                <span className="text-[10px] font-bold tracking-wider" style={{ color }}>
                  {m.Category || 'RACE CONTROL'}
                </span>
                <span className="text-[10px] text-gray-500 font-mono leading-none mt-0.5">
                  {m.Time}
                </span>
              </div>
              <div className="text-white text-[11px] leading-snug break-words">
                {m.Message}
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
