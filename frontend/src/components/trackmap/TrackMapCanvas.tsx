import { useEffect, useRef, useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useDriverStore } from '../../store/driverStore'
import { useUIStore, type TrackStatus } from '../../store/uiStore'
import { useReplayStore } from '../../store/replayStore'
import LiveTelemetryStrip from '../telemetry/LiveTelemetryStrip'
import RaceControlPanel from '../overlays/RaceControlPanel'

/* ═══════════════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════════════ */

interface TrackCoord { x: number; y: number }
interface DRSZone   { start: number; end: number }
interface DRSZoneXY { start_x: number; start_y: number; end_x: number; end_y: number }
interface SectorPoint { sector: number; x: number; y: number }

interface TrackData {
  coords: TrackCoord[]
  rotation: number
  drs_zones: DRSZone[]
  drs_zones_xy?: DRSZoneXY[]
  sector_points?: SectorPoint[]
  pit_entry?: TrackCoord
  pit_exit?: TrackCoord
  x_min: number; x_max: number
  y_min: number; y_max: number
}

interface Props {
  year: number
  round: number
  sessionType: string
}

/* ═══════════════════════════════════════════════════════════════════════
   Constants
   ═══════════════════════════════════════════════════════════════════════ */

const PADDING = 60
const TRACK_OUTER = 8
const TRACK_SURFACE = 6
const TRACK_CENTER = 4

// Interpolation config: slightly longer than the 250ms server interval
// so the dot is always still moving when the next target arrives
const BASE_INTERP_MS = 350

const STATUS_GLOW: Record<TrackStatus, string> = {
  GREEN:  'rgba(0,255,100,0.06)',
  YELLOW: 'rgba(255,255,0,0.18)',
  SC:     'rgba(255,165,0,0.18)',
  VSC:    'rgba(255,165,0,0.12)',
  RED:    'rgba(255,0,0,0.22)',
}

const STATUS_BORDER: Record<TrackStatus, string> = {
  GREEN:  'rgba(0,255,100,0.15)',
  YELLOW: 'rgba(255,255,0,0.6)',
  SC:     'rgba(255,165,0,0.6)',
  VSC:    'rgba(255,165,0,0.4)',
  RED:    'rgba(255,0,0,0.7)',
}

/* ═══════════════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════════════ */

/** Map a value from [srcMin, srcMax] → [0, 1]. */
function norm(v: number, lo: number, hi: number) {
  const r = hi - lo
  return r === 0 ? 0.5 : (v - lo) / r
}

interface Xf { scale: number; ox: number; oy: number; cx: number; cy: number; rad: number }

function computeXf(w: number, h: number, rotation: number): Xf {
  const avail = Math.min(w - 2 * PADDING, h - 2 * PADDING)
  const scale = Math.max(avail, 1)
  return {
    scale,
    ox: (w - scale) / 2,
    oy: (h - scale) / 2,
    cx: w / 2,
    cy: h / 2,
    rad: (rotation * Math.PI) / 180,
  }
}

function toCanvas(nx: number, ny: number, xf: Xf): [number, number] {
  return [xf.ox + nx * xf.scale, xf.oy + ny * xf.scale]
}

/* ═══════════════════════════════════════════════════════════════════════
   Draw helpers
   ═══════════════════════════════════════════════════════════════════════ */

function drawTrackPath(
  ctx: CanvasRenderingContext2D, coords: TrackCoord[], xf: Xf,
  color: string, width: number,
) {
  if (coords.length < 2) return
  ctx.beginPath()
  const [sx, sy] = toCanvas(coords[0].x, coords[0].y, xf)
  ctx.moveTo(sx, sy)
  for (let i = 1; i < coords.length; i++) {
    const [px, py] = toCanvas(coords[i].x, coords[i].y, xf)
    ctx.lineTo(px, py)
  }
  ctx.closePath()
  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.stroke()
}

function drawTrackSegment(
  ctx: CanvasRenderingContext2D, coords: TrackCoord[], xf: Xf,
  color: string, width: number, startIndex: number, endIndex: number
) {
  if (coords.length < 2) return
  ctx.beginPath()
  let current = startIndex
  const [sx, sy] = toCanvas(coords[current].x, coords[current].y, xf)
  ctx.moveTo(sx, sy)

  let steps = 0
  const n = coords.length
  while (current !== endIndex && steps < n) {
    current = (current + 1) % n
    const [px, py] = toCanvas(coords[current].x, coords[current].y, xf)
    ctx.lineTo(px, py)
    steps++
  }

  ctx.strokeStyle = color
  ctx.lineWidth = width
  ctx.lineJoin = 'round'
  ctx.lineCap = 'round'
  ctx.stroke()
}

function getClosestIndex(coords: TrackCoord[], x: number, y: number): number {
  let best = 0
  let bestDist = Infinity
  for (let i = 0; i < coords.length; i++) {
    const d = Math.hypot(coords[i].x - x, coords[i].y - y)
    if (d < bestDist) {
      bestDist = d
      best = i
    }
  }
  return best
}

function drawDRSXY(
  ctx: CanvasRenderingContext2D, coords: TrackCoord[], zonesXY: DRSZoneXY[], xf: Xf,
) {
  const n = coords.length
  for (const z of zonesXY) {
    const iStart = getClosestIndex(coords, z.start_x, z.start_y)
    const iEnd   = getClosestIndex(coords, z.end_x, z.end_y)

    ctx.beginPath()
    let current = iStart
    const [sx, sy] = toCanvas(coords[current].x, coords[current].y, xf)
    ctx.moveTo(sx, sy)

    let steps = 0
    while (current !== iEnd && steps < n) {
      current = (current + 1) % n
      const [px, py] = toCanvas(coords[current].x, coords[current].y, xf)
      ctx.lineTo(px, py)
      steps++
    }

    ctx.strokeStyle = '#00FF88'
    ctx.lineWidth = 6
    ctx.lineCap = 'round'
    ctx.stroke()

    // Add small "DRS" label
    ctx.font = 'bold 10px Inter, system-ui, sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    
    // Background pill
    const tw = ctx.measureText('DRS').width
    ctx.fillStyle = '#111111'
    ctx.beginPath()
    ctx.roundRect(sx - tw / 2 - 4, sy - 18, tw + 8, 14, 4)
    ctx.fill()
    ctx.lineWidth = 1
    ctx.strokeStyle = '#00FF88'
    ctx.stroke()

    ctx.fillStyle = '#ffffff'
    ctx.fillText('DRS', sx, sy - 11)
  }
}

function drawSectorMarkers(
  ctx: CanvasRenderingContext2D, coords: TrackCoord[], sectors: SectorPoint[], xf: Xf
) {
  for (const s of sectors) {
    const idx = getClosestIndex(coords, s.x, s.y)
    const p1 = coords[Math.max(0, idx - 1)]
    const p2 = coords[Math.min(coords.length - 1, idx + 1)]
    
    const [c1x, c1y] = toCanvas(p1.x, p1.y, xf)
    const [c2x, c2y] = toCanvas(p2.x, p2.y, xf)
    
    const dx = c2x - c1x
    const dy = c2y - c1y
    const len = Math.hypot(dx, dy) || 1
    const ppx = (-dy / len) * 12
    const ppy = (dx / len) * 12

    const [sx, sy] = toCanvas(s.x, s.y, xf)

    // Tick mark
    ctx.beginPath()
    ctx.moveTo(sx - ppx, sy - ppy)
    ctx.lineTo(sx + ppx, sy + ppy)
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 2
    ctx.stroke()

    // Label pill
    const txt = `S${s.sector}`
    ctx.font = 'bold 10px Inter, system-ui, sans-serif'
    const tw = ctx.measureText(txt).width
    
    const lx = sx + ppx * 1.6
    const ly = sy + ppy * 1.6

    ctx.fillStyle = 'rgba(0, 0, 0, 0.7)'
    ctx.beginPath()
    ctx.roundRect(lx - tw / 2 - 4, ly - 7, tw + 8, 14, 4)
    ctx.fill()
    
    ctx.fillStyle = '#ffffff'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(txt, lx, ly)
  }
}

function drawStartFinish(ctx: CanvasRenderingContext2D, coords: TrackCoord[], xf: Xf) {
  if (coords.length < 2) return
  const [ax, ay] = toCanvas(coords[0].x, coords[0].y, xf)
  const [bx, by] = toCanvas(coords[1].x, coords[1].y, xf)
  // perpendicular
  const dx = bx - ax, dy = by - ay
  const len = Math.hypot(dx, dy) || 1
  const px = (-dy / len) * 10, py = (dx / len) * 10
  ctx.beginPath()
  ctx.moveTo(ax - px, ay - py)
  ctx.lineTo(ax + px, ay + py)
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = 3
  ctx.stroke()

  ctx.font = 'bold 9px Inter, system-ui, sans-serif'
  ctx.fillStyle = '#ffffff'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('SF', ax, ay - 14)
}

function drawPitMarkers(ctx: CanvasRenderingContext2D, entry: TrackCoord | undefined, exit: TrackCoord | undefined, xf: Xf) {
  ctx.font = 'bold 8px Inter, system-ui, sans-serif'
  ctx.fillStyle = '#FF8C00'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  if (entry) {
    const [ex, ey] = toCanvas(entry.x, entry.y, xf)
    ctx.fillText('▼', ex, ey)
    ctx.fillText('PIT IN', ex, ey - 10)
  }
  if (exit) {
    const [ex, ey] = toCanvas(exit.x, exit.y, xf)
    ctx.fillText('▲', ex, ey)
    ctx.fillText('PIT OUT', ex, ey + 10)
  }
}


function drawStatusGlow(ctx: CanvasRenderingContext2D, w: number, h: number, status: TrackStatus) {
  const glowW = 18
  // edge glow via 4 gradients
  const color = STATUS_GLOW[status] || STATUS_GLOW.GREEN
  const border = STATUS_BORDER[status] || STATUS_BORDER.GREEN

  // top
  const tg = ctx.createLinearGradient(0, 0, 0, glowW)
  tg.addColorStop(0, color); tg.addColorStop(1, 'transparent')
  ctx.fillStyle = tg; ctx.fillRect(0, 0, w, glowW)
  // bottom
  const bg = ctx.createLinearGradient(0, h, 0, h - glowW)
  bg.addColorStop(0, color); bg.addColorStop(1, 'transparent')
  ctx.fillStyle = bg; ctx.fillRect(0, h - glowW, w, glowW)
  // left
  const lg = ctx.createLinearGradient(0, 0, glowW, 0)
  lg.addColorStop(0, color); lg.addColorStop(1, 'transparent')
  ctx.fillStyle = lg; ctx.fillRect(0, 0, glowW, h)
  // right
  const rg = ctx.createLinearGradient(w, 0, w - glowW, 0)
  rg.addColorStop(0, color); rg.addColorStop(1, 'transparent')
  ctx.fillStyle = rg; ctx.fillRect(w - glowW, 0, glowW, h)
  // border line
  ctx.strokeStyle = border; ctx.lineWidth = 2
  ctx.strokeRect(1, 1, w - 2, h - 2)
}

/* ═══════════════════════════════════════════════════════════════════════
   Interpolation entry per driver
   ═══════════════════════════════════════════════════════════════════════ */

interface PosEntry {
  prevX: number
  prevY: number
  targetX: number
  targetY: number
  startTime: number
  duration: number
}

/* ═══════════════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════════════ */

export default function TrackMapCanvas({ year, round, sessionType }: Props) {
  const canvasRef    = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rafRef       = useRef(0)

  // Timestamp-based interpolation map: code → PosEntry
  const posRef = useRef<Map<string, PosEntry>>(new Map())
  const opacityRef = useRef(1.0)

  // Also track status purely to trigger the useEffect regen
  const currentStatus = useUIStore(s => s.trackStatus)
  const yellowSectorsStr = useReplayStore(s => (s.raceControl.yellow_sectors || []).join(','))
  const replayMode = useReplayStore(s => s.mode)

  const selectDriver = useDriverStore(s => s.selectDriver)
  const liveTrack = useDriverStore(s => s.liveTrack)

  // ── fetch track data ──────────────────────────────────────────────
  const { data: track } = useQuery<TrackData>({
    queryKey: ['track', year, round, sessionType],
    queryFn: () =>
      fetch(`/api/sessions/${year}/${round}/${sessionType}/track`).then(r => r.json()),
    enabled: !!year && !!round && !!sessionType,
    staleTime: Infinity,
  })

  // ── canvas sizing via ResizeObserver ───────────────────────────────
  const [size, setSize] = useState({ w: 800, h: 600 })
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => {
      const { width, height } = e.contentRect
      if (width > 0 && height > 0) setSize({ w: Math.round(width), h: Math.round(height) })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ── animation loop (60fps, no throttle) ───────────────────────────
  useEffect(() => {
    const cvs = canvasRef.current

    // Determine which mode we're in (reactive — re-runs effect on mode change)
    const isLive = replayMode === 'live'

    // For replay mode: we need FastF1 track data
    // For live mode: we need the racing line from the game
    const hasReplayTrack = track && track.coords.length >= 2
    const hasLiveTrack = liveTrack && liveTrack.length >= 2

    if (!cvs || (!hasReplayTrack && !hasLiveTrack)) return

    const ctx = cvs.getContext('2d')!
    const dpr = window.devicePixelRatio || 1

    const w = size.w, h = size.h
    cvs!.width  = w * dpr
    cvs!.height = h * dpr
    cvs!.style.width = `${w}px`
    cvs!.style.height = `${h}px`
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    // ── Choose track outline and bounds based on mode ──────────────
    // In live mode: use liveTrack (racing line in game coords)
    // In replay mode: use FastF1 track data
    let drawCoords: TrackCoord[]
    let boundsXMin: number, boundsXMax: number
    let boundsYMin: number, boundsYMax: number
    let rotation: number

    if (isLive && hasLiveTrack) {
      // Live mode: normalise racing line coords to [0,1]
      const xs = liveTrack!.map(c => c.x)
      const ys = liveTrack!.map(c => c.y)
      boundsXMin = Math.min(...xs)
      boundsXMax = Math.max(...xs)
      boundsYMin = Math.min(...ys)
      boundsYMax = Math.max(...ys)
      const xRange = (boundsXMax - boundsXMin) || 1
      const yRange = (boundsYMax - boundsYMin) || 1
      drawCoords = liveTrack!.map(c => ({
        x: (c.x - boundsXMin) / xRange,
        y: (c.y - boundsYMin) / yRange,
      }))
      rotation = 0 // racing line already oriented correctly
      console.log(`[TrackMap] Live track: ${drawCoords.length} pts, bounds x=[${boundsXMin.toFixed(0)},${boundsXMax.toFixed(0)}] y=[${boundsYMin.toFixed(0)},${boundsYMax.toFixed(0)}]`)
    } else if (isLive && !hasLiveTrack) {
      // Live mode but racing line not yet received — wait
      return
    } else if (hasReplayTrack) {
      drawCoords = track!.coords
      boundsXMin = track!.x_min
      boundsXMax = track!.x_max
      boundsYMin = track!.y_min
      boundsYMax = track!.y_max
      rotation = track!.rotation
    } else {
      return // no track data available
    }

    const xf = computeXf(w, h, rotation)

    // 1. Setup offscreen canvas for track background
    const offscreen = document.createElement('canvas')
    offscreen.width = w * dpr
    offscreen.height = h * dpr
    const offCtx = offscreen.getContext('2d')!
    offCtx.setTransform(dpr, 0, 0, dpr, 0, 0)
    
    // Draw track once to offscreen
    offCtx.save()
    offCtx.translate(xf.cx, xf.cy)
    offCtx.rotate(xf.rad)
    offCtx.translate(-xf.cx, -xf.cy)

    // ── 3 track layers ──────────────────────────────────────────
    drawTrackPath(offCtx, drawCoords, xf, '#3A3A4A', TRACK_OUTER)
    drawTrackPath(offCtx, drawCoords, xf, '#2A2A3A', TRACK_SURFACE)

    if (currentStatus === 'SC' || currentStatus === 'VSC') {
      drawTrackPath(offCtx, drawCoords, xf, '#FFA500', TRACK_CENTER)
    } else if (currentStatus === 'RED') {
      drawTrackPath(offCtx, drawCoords, xf, '#FF0000', TRACK_CENTER)
    }

    const yellowSectors = yellowSectorsStr ? yellowSectorsStr.split(',').map(Number) : []
    if (currentStatus === 'YELLOW' && yellowSectors.length > 0) {
      const yellowSet = new Set(yellowSectors)
      const n = drawCoords.length
      const s1End = Math.floor(n / 3)
      const s2End = Math.floor((2 * n) / 3)
      if (yellowSet.has(1)) drawTrackSegment(offCtx, drawCoords, xf, '#FFD700', 6, 0, s1End)
      if (yellowSet.has(2)) drawTrackSegment(offCtx, drawCoords, xf, '#FFD700', 6, s1End, s2End)
      if (yellowSet.has(3)) drawTrackSegment(offCtx, drawCoords, xf, '#FFD700', 6, s2End, 0)
    }

    // ── start / finish ──────────────────────────────────────────
    drawStartFinish(offCtx, drawCoords, xf)

    // ── DRS zones ───────────────────────────────────────────────
    if (track?.drs_zones_xy && track.drs_zones_xy.length > 0 && !isLive) {
      drawDRSXY(offCtx, drawCoords, track.drs_zones_xy, xf)
    }

    // ── Sector markers ──────────────────────────────────────────
    if (track?.sector_points && track.sector_points.length > 0 && !isLive) {
      drawSectorMarkers(offCtx, drawCoords, track.sector_points, xf)
    }

    // ── Pit markers ─────────────────────────────────────────────
    if (track?.pit_entry || track?.pit_exit) {
      drawPitMarkers(offCtx, track?.pit_entry, track?.pit_exit, xf)
    }

    offCtx.restore()

    function frame() {
      rafRef.current = requestAnimationFrame(frame)

      const now = performance.now()
      const drivers = Object.values(useDriverStore.getState().drivers)
      
      const storeState = useDriverStore.getState()

      const selected = storeState.selectedDriver
      const status = useUIStore.getState().trackStatus
      const isLiveMode = useReplayStore.getState().mode === 'live'
      const posMap = posRef.current

      // Update interpolation targets
      for (const d of drivers) {
        const code = d.code || d.fullName
        const entry = posMap.get(code)

        if (!entry) {
          posMap.set(code, {
            prevX: d.x, prevY: d.y,
            targetX: d.x, targetY: d.y,
            startTime: now,
            duration: BASE_INTERP_MS,
          })
        } else if (entry.targetX !== d.x || entry.targetY !== d.y) {
          const elapsed = now - entry.startTime
          const t = Math.min(elapsed / entry.duration, 1)
          entry.prevX = entry.prevX + (entry.targetX - entry.prevX) * t
          entry.prevY = entry.prevY + (entry.targetY - entry.prevY) * t
          entry.targetX = d.x
          entry.targetY = d.y
          entry.startTime = now
          entry.duration = BASE_INTERP_MS
        }
      }

      // clear
      ctx.clearRect(0, 0, w, h)

      // status glow (behind everything)
      drawStatusGlow(ctx, w, h, status)

      // draw cached track
      if (status === 'SC' || status === 'VSC') {
        const time = now / 1000
        opacityRef.current = 0.8 + 0.2 * Math.sin(time * 2 * Math.PI)
      } else {
        opacityRef.current = 1.0
      }
      ctx.globalAlpha = opacityRef.current
      ctx.drawImage(offscreen, 0, 0, w, h)
      ctx.globalAlpha = 1.0

      // apply rotation around center for drivers
      ctx.save()
      ctx.translate(xf.cx, xf.cy)
      ctx.rotate(xf.rad)
      ctx.translate(-xf.cx, -xf.cy)

      // ── drivers ─────────────────────────────────────────────────
      for (const d of drivers) {
        const code = d.code || d.fullName
        const entry = posRef.current.get(code)

        // Compute interpolated world position
        let ix: number, iy: number
        if (isLiveMode) {
          ix = d.x
          iy = d.y
        } else if (entry) {
          const elapsed = now - entry.startTime
          const t = Math.min(elapsed / entry.duration, 1)
          ix = entry.prevX + (entry.targetX - entry.prevX) * t
          iy = entry.prevY + (entry.targetY - entry.prevY) * t
        } else {
          ix = d.x
          iy = d.y
        }

        // normalise world pos → [0,1]
        // Both modes use the same normalisation against the track bounds.
        // In live mode: bounds come from liveTrack (game coords).
        // In replay mode: bounds come from FastF1 track data.
        const nx = Math.max(0, Math.min(1, norm(ix, boundsXMin, boundsXMax)))
        const ny = Math.max(0, Math.min(1, norm(iy, boundsYMin, boundsYMax)))

        const [cx, cy] = toCanvas(nx, ny, xf)
        const alpha = d.isOut ? 0.4 : 1

        ctx.globalAlpha = alpha

        // selected ring (18px)
        if (code === selected) {
          ctx.beginPath()
          ctx.arc(cx, cy, 18, 0, Math.PI * 2)
          ctx.strokeStyle = '#ffffff'
          ctx.lineWidth = 2
          ctx.stroke()
        }

        // Outer dot (14px)
        ctx.beginPath()
        ctx.arc(cx, cy, 14, 0, Math.PI * 2)
        ctx.fillStyle = d.teamColor || '#999999'
        ctx.fill()

        // Inner white circle (4px)
        ctx.beginPath()
        ctx.arc(cx, cy, 4, 0, Math.PI * 2)
        ctx.fillStyle = '#ffffff'
        ctx.fill()

        // code label
        ctx.font = 'bold 9px Inter, system-ui, sans-serif'
        ctx.textAlign = 'center'
        const label = String(code || '').slice(0, 3)
        const tw = ctx.measureText(label).width
        const textY = cy + 14 + 12

        // Background rect behind text
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)'
        ctx.lineJoin = 'round'
        ctx.lineWidth = 4
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.6)'
        ctx.strokeRect(cx - tw / 2, textY - 8, tw, 9)
        ctx.fillRect(cx - tw / 2, textY - 8, tw, 9)

        ctx.fillStyle = '#ffffff'
        
        if (d.isOut) {
          ctx.fillText(label, cx, textY)
          // strikethrough
          ctx.beginPath()
          ctx.moveTo(cx - tw / 2 - 1, textY - 3)
          ctx.lineTo(cx + tw / 2 + 1, textY - 3)
          ctx.strokeStyle = '#ffffff'
          ctx.lineWidth = 1
          ctx.stroke()
        } else {
          ctx.fillText(label, cx, textY)
        }

        ctx.globalAlpha = 1
      }

      ctx.restore()


    }

    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(rafRef.current)
  }, [size, track, liveTrack, replayMode, currentStatus, yellowSectorsStr])

  // ── click → select driver ─────────────────────────────────────────
  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const isLive = replayMode === 'live'
    const hasLT = liveTrack && liveTrack.length >= 2

    // Determine bounds and rotation for hit-testing
    let bxMin: number, bxMax: number, byMin: number, byMax: number, rot: number
    if (isLive && hasLT) {
      const xs = liveTrack!.map(c => c.x)
      const ys = liveTrack!.map(c => c.y)
      bxMin = Math.min(...xs); bxMax = Math.max(...xs)
      byMin = Math.min(...ys); byMax = Math.max(...ys)
      rot = 0
    } else if (track) {
      bxMin = track.x_min; bxMax = track.x_max
      byMin = track.y_min; byMax = track.y_max
      rot = track.rotation
    } else {
      return
    }

    const cvs = canvasRef.current!
    const rect = cvs.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const xf = computeXf(size.w, size.h, rot)
    const drivers = useDriverStore.getState().drivers
    const now = performance.now()

    // rotate click point back (inverse of canvas rotation)
    const cos = Math.cos(-xf.rad), sin = Math.sin(-xf.rad)
    const dx = mx - xf.cx, dy = my - xf.cy
    const rmx = cos * dx - sin * dy + xf.cx
    const rmy = sin * dx + cos * dy + xf.cy

    let best = '', bestDist = 24 // max hit distance
    for (const code of Object.keys(drivers)) {
      const entry = posRef.current.get(code)
      if (!entry) continue
      // compute interpolated position
      const elapsed = now - entry.startTime
      const t = Math.min(elapsed / entry.duration, 1)
      const ix = entry.prevX + (entry.targetX - entry.prevX) * t
      const iy = entry.prevY + (entry.targetY - entry.prevY) * t
      const nx = norm(ix, bxMin, bxMax)
      const ny = norm(iy, byMin, byMax)
      const [cx, cy] = toCanvas(nx, ny, xf)
      const d = Math.hypot(rmx - cx, rmy - cy)
      if (d < bestDist) { bestDist = d; best = code }
    }
    selectDriver(best || null)
  }, [track, liveTrack, replayMode, size, selectDriver])

  // ── render ────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col w-full h-full bg-[#0A0A0F]">
      <div ref={containerRef} className="flex-1 min-h-0 relative">
        <canvas
          ref={canvasRef}
          width={size.w}
          height={size.h}
          onClick={handleClick}
          className="block absolute inset-0 cursor-crosshair"
        />
        <RaceControlPanel />
      </div>

      <LiveTelemetryStrip />
    </div>
  )
}
