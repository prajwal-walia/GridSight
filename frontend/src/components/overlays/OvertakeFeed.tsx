import { useEffect, useState, useRef } from 'react'
import { useDriverStore, type OvertakeEvent } from '../../store/driverStore'

/* ── types ────────────────────────────────────────────────────────────── */

interface FeedEntry {
  id: number
  event: OvertakeEvent
  opacity: number
}

let nextId = 0

/* ── component ────────────────────────────────────────────────────────── */

export default function OvertakeFeed() {
  const overtakeEvents = useDriverStore(s => s.overtakeEvents)
  const drivers = useDriverStore(s => s.drivers)
  const [entries, setEntries] = useState<FeedEntry[]>([])
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())
  const prevLen = useRef(0)

  // watch for new overtake events
  useEffect(() => {
    if (overtakeEvents.length > prevLen.current) {
      const newEvents = overtakeEvents.slice(prevLen.current)
      prevLen.current = overtakeEvents.length

      for (const event of newEvents) {
        const id = nextId++

        setEntries(prev => {
          const updated = [...prev, { id, event, opacity: 1 }]
          // keep only last 5
          return updated.slice(-5)
        })

        // fade out after 6s
        const timer = setTimeout(() => {
          setEntries(prev =>
            prev.map(e => (e.id === id ? { ...e, opacity: 0 } : e))
          )
          // remove after fade animation completes
          const removeTimer = setTimeout(() => {
            setEntries(prev => prev.filter(e => e.id !== id))
            timersRef.current.delete(id)
          }, 500)
          timersRef.current.set(id + 100000, removeTimer)
        }, 6000)

        timersRef.current.set(id, timer)
      }
    }
  }, [overtakeEvents])

  // cleanup
  useEffect(() => {
    return () => {
      timersRef.current.forEach(t => clearTimeout(t))
    }
  }, [])

  if (entries.length === 0) return null

  return (
    <div
      className="fixed bottom-16 right-3 z-40 flex flex-col gap-1"
      style={{ maxWidth: 260 }}
    >
      {entries.map(entry => {
        const { event } = entry
        const driverData = drivers[event.driver]
        const teamColor = driverData?.teamColor || '#e2e2e2'

        return (
          <div
            key={entry.id}
            className="flex items-center gap-2 px-3 py-1.5 rounded-md"
            style={{
              background: 'rgba(18, 18, 26, 0.92)',
              backdropFilter: 'blur(8px)',
              border: '1px solid #1E1E2E',
              opacity: entry.opacity,
              transition: 'opacity 0.5s ease',
            }}
          >
            <span className="text-green-400 text-xs font-bold">▲</span>
            <span
              className="text-xs font-extrabold"
              style={{ color: teamColor }}
            >
              {event.driver}
            </span>
            <span className="text-gray-500 text-[10px]">
              P{event.from} → P{event.to}
            </span>
          </div>
        )
      })}
    </div>
  )
}
